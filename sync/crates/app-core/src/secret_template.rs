use regex::Regex;
use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

#[cfg(unix)]
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};

/// Private mode for secrets and sensitive configuration (0600).
pub const SECRET_OUTPUT_MODE: u32 = 0o600;

#[allow(clippy::expect_used)]
static PLACEHOLDER_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\$\{([^{}]+)\}").expect("valid placeholder regex"));

#[allow(clippy::expect_used)]
static SECRET_NAME_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Z][A-Z0-9_]*$").expect("valid secret name regex"));

/// Errors encountered when reading secrets, rendering templates, or synchronizing secret files.
#[derive(Debug, Error)]
pub enum SecretTemplateError {
    #[error("read {label} {path}: {source}")]
    ReadText {
        label: &'static str,
        path: PathBuf,
        #[source]
        source: io::Error,
    },

    #[error("parse secrets {path} ({message})")]
    ParseSecrets { path: PathBuf, message: String },

    #[error("invalid secrets file: {path} (expected object)")]
    ExpectedObject { path: PathBuf },

    #[error("invalid secret entry: {message}")]
    InvalidSecretEntry { message: String },

    #[error("invalid secret placeholder: {0}")]
    InvalidPlaceholder(String),

    #[error("missing secret: {0}")]
    MissingSecret(String),

    #[error("json serialize error: {0}")]
    JsonSerialize(String),

    #[error("render secret template {src} -> {dst} ({message})")]
    RenderSync {
        src: PathBuf,
        dst: PathBuf,
        message: String,
    },

    #[error("io error: {0}")]
    Io(#[from] io::Error),
}

/// Renders a secret template by replacing all `${UPPER_SNAKE}` placeholders with their
/// JSON-safe escaped secret string values.
///
/// Returns an error if any placeholder has an invalid format or if a secret is missing/empty.
pub fn render_secret_template<S: std::hash::BuildHasher>(
    template: &str,
    secrets: &HashMap<String, String, S>,
) -> Result<String, SecretTemplateError> {
    let mut result = String::with_capacity(template.len());
    let mut last_idx = 0;

    for caps in PLACEHOLDER_RE.captures_iter(template) {
        let (Some(full_match), Some(raw_capture)) = (caps.get(0), caps.get(1)) else {
            continue;
        };
        let raw_name = raw_capture.as_str();

        if let Some(prefix) = template.get(last_idx..full_match.start()) {
            result.push_str(prefix);
        }

        if !SECRET_NAME_RE.is_match(raw_name) {
            return Err(SecretTemplateError::InvalidPlaceholder(
                raw_name.to_string(),
            ));
        }

        let value = match secrets.get(raw_name) {
            Some(v) if !v.is_empty() => v,
            _ => return Err(SecretTemplateError::MissingSecret(raw_name.to_string())),
        };

        let escaped = serde_json::to_string(value)
            .map_err(|err| SecretTemplateError::JsonSerialize(err.to_string()))?;
        result.push_str(&escaped);

        last_idx = full_match.end();
    }

    if let Some(tail) = template.get(last_idx..) {
        result.push_str(tail);
    }
    Ok(result)
}

/// Reads and validates a JSON/JSONC secrets file into a map of secret names to secret values.
///
/// Keys must conform to `^[A-Z][A-Z0-9_]*$` and values must be non-empty strings.
pub fn read_secrets_file(
    path: impl AsRef<Path>,
) -> Result<HashMap<String, String>, SecretTemplateError> {
    let path = path.as_ref();
    let content = fs::read_to_string(path).map_err(|source| SecretTemplateError::ReadText {
        label: "secrets",
        path: path.to_path_buf(),
        source,
    })?;

    let parsed: serde_json::Value =
        json5::from_str(&content).map_err(|err| SecretTemplateError::ParseSecrets {
            path: path.to_path_buf(),
            message: err.to_string(),
        })?;

    let serde_json::Value::Object(object) = parsed else {
        return Err(SecretTemplateError::ExpectedObject {
            path: path.to_path_buf(),
        });
    };

    let mut secrets = HashMap::new();
    for (key, val) in object {
        if !SECRET_NAME_RE.is_match(&key) {
            return Err(SecretTemplateError::InvalidSecretEntry {
                message: format!("key `{key}` does not match uppercase snake_case pattern"),
            });
        }
        match val {
            serde_json::Value::String(s) if !s.is_empty() => {
                secrets.insert(key, s);
            }
            _ => {
                return Err(SecretTemplateError::InvalidSecretEntry {
                    message: format!("value for `{key}` must be a non-empty string"),
                });
            }
        }
    }

    Ok(secrets)
}

/// Reads the template from `src` and secrets from `secrets_path`, renders the template,
/// and writes the output to `dst` with mode 0600 atomically and idempotently.
pub fn sync_secret_template(
    src: impl AsRef<Path>,
    dst: impl AsRef<Path>,
    secrets_path: impl AsRef<Path>,
) -> Result<(), SecretTemplateError> {
    let src = src.as_ref();
    let dst = dst.as_ref();
    let secrets_path = secrets_path.as_ref();

    let template = fs::read_to_string(src).map_err(|source| SecretTemplateError::ReadText {
        label: "template",
        path: src.to_path_buf(),
        source,
    })?;

    let secrets = read_secrets_file(secrets_path)?;
    let content = render_secret_template(&template, &secrets)?;

    if let Err(err) = sync_private_text_file(dst, &content) {
        return Err(SecretTemplateError::RenderSync {
            src: src.to_path_buf(),
            dst: dst.to_path_buf(),
            message: err.to_string(),
        });
    }

    Ok(())
}

/// Atomically and idempotently synchronizes private text content with mode 0600 (owner read/write).
pub fn sync_private_text_file(dst: impl AsRef<Path>, content: &str) -> io::Result<bool> {
    sync_text_file(dst, content, SECRET_OUTPUT_MODE)
}

/// Atomically and idempotently writes `content` to `dst` with target `mode`.
///
/// Skips write if file already exists with exact content and permissions.
pub fn sync_text_file(dst: impl AsRef<Path>, content: &str, mode: u32) -> io::Result<bool> {
    let dst = dst.as_ref();
    if matches_output(dst, content, mode) {
        return Ok(false);
    }

    atomic_write_text_file(dst, content, mode)?;
    Ok(true)
}

/// Atomically writes content to `dst` with specified mode using temporary file and rename.
pub fn atomic_write_text_file(dst: impl AsRef<Path>, content: &str, mode: u32) -> io::Result<()> {
    let dst = dst.as_ref();
    let parent = dst.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;

    let (temp_path, mut file) = create_temp_file(dst, mode)?;
    let write_result = (|| -> io::Result<()> {
        file.write_all(content.as_bytes())?;
        file.flush()?;
        #[cfg(unix)]
        {
            fs::set_permissions(&temp_path, fs::Permissions::from_mode(mode & 0o777))?;
        }
        file.sync_all()?;
        drop(file);
        fs::rename(&temp_path, dst)?;
        Ok(())
    })();

    if write_result.is_err() {
        let _ = fs::remove_file(&temp_path);
    }
    write_result
}

/// Checks if destination file exists, is a regular file (not symlink), has exact content and matching permissions.
pub fn matches_output(path: impl AsRef<Path>, content: &str, mode: u32) -> bool {
    let path = path.as_ref();
    let Ok(meta) = fs::symlink_metadata(path) else {
        return false;
    };

    if meta.file_type().is_symlink() || !meta.is_file() {
        return false;
    }

    #[cfg(unix)]
    {
        if (meta.mode() & 0o777) != (mode & 0o777) {
            return false;
        }
    }

    let mut existing = String::new();
    match File::open(path).and_then(|mut f| f.read_to_string(&mut existing)) {
        Ok(_) => existing == content,
        Err(_) => false,
    }
}

fn create_temp_file(target: &Path, mode: u32) -> io::Result<(PathBuf, File)> {
    let parent = target.parent().unwrap_or_else(|| Path::new("."));
    let file_name = target
        .file_name()
        .map_or_else(|| "config".to_string(), |n| n.to_string_lossy().to_string());
    let pid = std::process::id();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();

    for attempt in 0..16 {
        let temp_name = format!(".{file_name}.{pid}.{now:x}-{attempt}.tmp");
        let temp_path = parent.join(temp_name);

        let mut opts = OpenOptions::new();
        opts.write(true).create_new(true);

        #[cfg(unix)]
        {
            opts.mode(mode & 0o777);
        }

        match opts.open(&temp_path) {
            Ok(file) => return Ok((temp_path, file)),
            Err(err) if err.kind() == io::ErrorKind::AlreadyExists => {}
            Err(err) => return Err(err),
        }
    }

    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        format!(
            "create temporary file near {} (name collision)",
            target.display()
        ),
    ))
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::panic_in_result_fn
)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_render_secret_template_success() {
        let mut secrets = HashMap::new();
        secrets.insert("API_KEY".to_string(), "sk-12345".to_string());
        secrets.insert(
            "BASE_URL".to_string(),
            "https://api.example.com".to_string(),
        );
        secrets.insert(
            "SPECIAL_CHAR".to_string(),
            "value with \"quotes\" and \n newline".to_string(),
        );

        let template = "key: ${API_KEY}\nurl: ${BASE_URL}\nspecial: ${SPECIAL_CHAR}\n";
        let rendered = render_secret_template(template, &secrets).unwrap();

        assert!(rendered.contains("key: \"sk-12345\""));
        assert!(rendered.contains("url: \"https://api.example.com\""));
        assert!(rendered.contains("special: \"value with \\\"quotes\\\" and \\n newline\""));
    }

    #[test]
    fn test_render_secret_template_invalid_placeholder() {
        let secrets = HashMap::new();
        let template = "key: ${invalid_placeholder}\n";
        let err = render_secret_template(template, &secrets).unwrap_err();
        match err {
            SecretTemplateError::InvalidPlaceholder(name) => {
                assert_eq!(name, "invalid_placeholder");
            }
            other => panic!("expected InvalidPlaceholder, got {other:?}"),
        }
    }

    #[test]
    fn test_render_secret_template_missing_secret() {
        let secrets = HashMap::new();
        let template = "key: ${MISSING_KEY}\n";
        let err = render_secret_template(template, &secrets).unwrap_err();
        match err {
            SecretTemplateError::MissingSecret(name) => {
                assert_eq!(name, "MISSING_KEY");
            }
            other => panic!("expected MissingSecret, got {other:?}"),
        }
    }

    #[test]
    fn test_read_secrets_file_jsonc() -> Result<(), Box<dyn std::error::Error>> {
        let dir = tempdir()?;
        let sec_path = dir.path().join("secrets.json");

        // Write JSONC content with comments and trailing comma
        let jsonc = r#"{
            // Main OpenAI key
            "OPENAI_KEY": "sk-test-123",
            /* Anthropic key */
            "ANTHROPIC_KEY": "claude-test-456",
        }"#;
        fs::write(&sec_path, jsonc)?;

        let secrets = read_secrets_file(&sec_path)?;
        assert_eq!(secrets.get("OPENAI_KEY").unwrap(), "sk-test-123");
        assert_eq!(secrets.get("ANTHROPIC_KEY").unwrap(), "claude-test-456");

        Ok(())
    }

    #[test]
    fn test_read_secrets_file_invalid_key() -> Result<(), Box<dyn std::error::Error>> {
        let dir = tempdir()?;
        let sec_path = dir.path().join("secrets.json");

        fs::write(&sec_path, r#"{"invalid-key": "value"}"#)?;
        let err = read_secrets_file(&sec_path).unwrap_err();
        match err {
            SecretTemplateError::InvalidSecretEntry { message: _ } => {}
            other => panic!("expected InvalidSecretEntry, got {other:?}"),
        }

        Ok(())
    }

    #[test]
    fn test_sync_secret_template_end_to_end() -> Result<(), Box<dyn std::error::Error>> {
        let dir = tempdir()?;
        let tmpl_path = dir.path().join("template.env");
        let sec_path = dir.path().join("secrets.json");
        let dst_path = dir.path().join("out.env");

        fs::write(&tmpl_path, "KEY=${SECRET_KEY}\n")?;
        fs::write(&sec_path, r#"{"SECRET_KEY": "super_secret"}"#)?;

        sync_secret_template(&tmpl_path, &dst_path, &sec_path)?;
        assert_eq!(fs::read_to_string(&dst_path)?, "KEY=\"super_secret\"\n");

        #[cfg(unix)]
        {
            let meta = fs::metadata(&dst_path)?;
            assert_eq!(meta.mode() & 0o777, 0o600);
        }

        // Second sync is idempotent
        sync_secret_template(&tmpl_path, &dst_path, &sec_path)?;
        assert_eq!(fs::read_to_string(&dst_path)?, "KEY=\"super_secret\"\n");

        Ok(())
    }
}
