use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use thiserror::Error;

pub const TOOL_NAME: &str = "cliproxyapi";
pub const RELEASE_FILE: &str = "release.json";
pub const CLI_PROXY_SOURCE_DIR: &str = "tools/cliproxyapi";

#[derive(Debug, Error)]
pub enum ManagedToolError {
    #[error("I/O error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("parse {path} ({message})")]
    ManifestParse { path: PathBuf, message: String },
    #[error("invalid release manifest: {path}")]
    ManifestValidation { path: PathBuf },
    #[error("unsupported architecture: {0}")]
    UnsupportedArchitecture(String),
    #[error("CLIProxyAPI has no release asset for {0}")]
    MissingReleaseAsset(String),
    #[error("checksum mismatch for {filename}")]
    ChecksumMismatch { filename: String },
    #[error("download failed with HTTP {status}")]
    DownloadHttp { status: u16 },
    #[error("download error from {url}: {message}")]
    Download { url: String, message: String },
    #[error("archive extraction timed out")]
    ExtractionTimeout,
    #[error("archive extraction failed for {path}: {message}")]
    Extraction { path: PathBuf, message: String },
    #[error("CLIProxyAPI archive is missing {0}")]
    MissingBinary(String),
    #[error("install CLIProxyAPI {version} ({message})")]
    Install { version: String, message: String },
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ReleaseAsset {
    pub name: String,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ReleaseManifest {
    pub repository: String,
    pub version: String,
    pub binary: String,
    pub assets: HashMap<String, ReleaseAsset>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct PreparedManagedTool {
    pub name: String,
    pub command: String,
    pub executable: PathBuf,
    pub version: String,
    pub config_path: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ManagedToolReceipt {
    pub repository: String,
    pub version: String,
    pub asset: String,
    pub sha256: String,
}

/// Pluggable downloader trait for managed tool release archives.
pub trait ManagedToolDownloader: Send + Sync {
    fn download(
        &self,
        url: &str,
        destination: &Path,
        timeout: Duration,
    ) -> Result<(), ManagedToolError>;
}

/// Pluggable archive extractor trait for managed tool release archives.
pub trait ManagedToolExtractor: Send + Sync {
    fn extract(
        &self,
        archive: &Path,
        destination: &Path,
        entry_name: &str,
        timeout: Duration,
    ) -> Result<(), ManagedToolError>;
}

#[derive(Default)]
pub struct ManagedToolRuntime {
    pub arch: Option<String>,
    pub cache_home: Option<PathBuf>,
    pub downloader: Option<Arc<dyn ManagedToolDownloader>>,
    pub extractor: Option<Arc<dyn ManagedToolExtractor>>,
}

/// Validates component name according to `^[A-Za-z0-9._-]+$`.
#[must_use]
pub fn is_valid_component(name: &str) -> bool {
    !name.is_empty()
        && name != "."
        && name != ".."
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-')
}

/// Validates repository name according to `^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$`.
#[must_use]
pub fn is_valid_repository(repo: &str) -> bool {
    let mut parts = repo.split('/');
    let Some(owner) = parts.next() else {
        return false;
    };
    let Some(name) = parts.next() else {
        return false;
    };
    if parts.next().is_some() {
        return false;
    }
    is_valid_component(owner) && is_valid_component(name)
}

/// Validates hex-encoded SHA-256 string (64 lowercase hex chars).
#[must_use]
pub fn is_valid_sha256(hex: &str) -> bool {
    hex.len() == 64
        && hex
            .chars()
            .all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c))
}

/// Resolves and normalizes target CPU architecture.
pub fn supported_arch(arch: &str) -> Result<&'static str, ManagedToolError> {
    match arch {
        "arm64" | "aarch64" => Ok("arm64"),
        "x64" | "x86_64" | "amd64" => Ok("x64"),
        _ => Err(ManagedToolError::UnsupportedArchitecture(arch.to_string())),
    }
}

/// Parses and validates a release manifest JSON file.
pub fn read_manifest(manifest_path: &Path) -> Result<ReleaseManifest, ManagedToolError> {
    let content =
        fs::read_to_string(manifest_path).map_err(|e| ManagedToolError::ManifestParse {
            path: manifest_path.to_path_buf(),
            message: e.to_string(),
        })?;

    let manifest: ReleaseManifest =
        serde_json::from_str(&content).map_err(|e| ManagedToolError::ManifestParse {
            path: manifest_path.to_path_buf(),
            message: e.to_string(),
        })?;

    if !is_valid_repository(&manifest.repository)
        || !is_valid_component(&manifest.version)
        || !is_valid_component(&manifest.binary)
    {
        return Err(ManagedToolError::ManifestValidation {
            path: manifest_path.to_path_buf(),
        });
    }

    for asset in manifest.assets.values() {
        if !is_valid_component(&asset.name) || !is_valid_sha256(&asset.sha256) {
            return Err(ManagedToolError::ManifestValidation {
                path: manifest_path.to_path_buf(),
            });
        }
    }

    Ok(manifest)
}

/// Computes SHA-256 checksum and compares with expected hex digest.
pub fn verify_checksum(archive_path: &Path, expected_hex: &str) -> Result<(), ManagedToolError> {
    use sha2::{Digest, Sha256};

    let mut file = File::open(archive_path).map_err(|e| ManagedToolError::Io {
        path: archive_path.to_path_buf(),
        source: e,
    })?;

    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 8192];
    loop {
        let bytes_read = file.read(&mut buffer).map_err(|e| ManagedToolError::Io {
            path: archive_path.to_path_buf(),
            source: e,
        })?;
        if bytes_read == 0 {
            break;
        }
        if let Some(chunk) = buffer.get(..bytes_read) {
            hasher.update(chunk);
        }
    }

    let actual_hex = hex::encode(hasher.finalize());
    if actual_hex != expected_hex.to_lowercase() {
        let filename = archive_path.file_name().map_or_else(
            || String::from("archive"),
            |n| n.to_string_lossy().into_owned(),
        );
        return Err(ManagedToolError::ChecksumMismatch { filename });
    }

    Ok(())
}

/// Unpacks a `.tar.gz` archive to the destination directory and marks the executable executable.
pub fn extract_tar_gz(
    archive_path: &Path,
    destination_dir: &Path,
    entry_name: &str,
) -> Result<(), ManagedToolError> {
    let file = File::open(archive_path).map_err(|e| ManagedToolError::Io {
        path: archive_path.to_path_buf(),
        source: e,
    })?;
    let gz = flate2::read::GzDecoder::new(file);
    let mut tar = tar::Archive::new(gz);
    tar.unpack(destination_dir)
        .map_err(|e| ManagedToolError::Extraction {
            path: archive_path.to_path_buf(),
            message: e.to_string(),
        })?;

    let binary_path = destination_dir.join(entry_name);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if binary_path.exists() {
            let _ = fs::set_permissions(&binary_path, fs::Permissions::from_mode(0o755));
        }
    }

    Ok(())
}

fn installed_tool_matches(executable: &Path, receipt_path: &Path, expected_receipt: &str) -> bool {
    let Ok(metadata) = fs::symlink_metadata(executable) else {
        return false;
    };
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return false;
    }

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if (metadata.permissions().mode() & 0o111) == 0 {
            return false;
        }
    }

    let Ok(receipt_content) = fs::read_to_string(receipt_path) else {
        return false;
    };
    receipt_content == expected_receipt
}

/// Default downloader using blocking/standard library or reqwest.
pub struct DefaultReqwestDownloader;

impl ManagedToolDownloader for DefaultReqwestDownloader {
    fn download(
        &self,
        url: &str,
        destination: &Path,
        timeout: Duration,
    ) -> Result<(), ManagedToolError> {
        std::thread::scope(|scope| {
            scope
                .spawn(|| {
                    let client = reqwest::blocking::Client::builder()
                        .timeout(timeout)
                        .build()
                        .map_err(|e| ManagedToolError::Download {
                            url: url.to_string(),
                            message: e.to_string(),
                        })?;

                    let response =
                        client
                            .get(url)
                            .send()
                            .map_err(|e| ManagedToolError::Download {
                                url: url.to_string(),
                                message: e.to_string(),
                            })?;

                    if !response.status().is_success() {
                        return Err(ManagedToolError::DownloadHttp {
                            status: response.status().as_u16(),
                        });
                    }

                    let bytes = response.bytes().map_err(|e| ManagedToolError::Download {
                        url: url.to_string(),
                        message: e.to_string(),
                    })?;

                    if let Some(parent) = destination.parent() {
                        fs::create_dir_all(parent).map_err(|e| ManagedToolError::Io {
                            path: parent.to_path_buf(),
                            source: e,
                        })?;
                    }

                    fs::write(destination, bytes).map_err(|e| ManagedToolError::Io {
                        path: destination.to_path_buf(),
                        source: e,
                    })?;

                    Ok(())
                })
                .join()
                .map_err(|_| ManagedToolError::Download {
                    url: url.to_string(),
                    message: "download thread panicked".to_string(),
                })?
        })
    }
}

pub struct DefaultTarExtractor;

impl ManagedToolExtractor for DefaultTarExtractor {
    fn extract(
        &self,
        archive: &Path,
        destination: &Path,
        entry_name: &str,
        _timeout: Duration,
    ) -> Result<(), ManagedToolError> {
        extract_tar_gz(archive, destination, entry_name)
    }
}

/// Prepares the `CLIProxyAPI` managed tool, downloading and verifying its release asset if needed.
#[allow(clippy::too_many_lines)]
pub fn prepare_cli_proxy(
    home: &Path,
    _ssot_home: &Path,
    platform: &str,
    manifest_path: &Path,
    install_timeout: Duration,
    runtime: &ManagedToolRuntime,
) -> Result<PreparedManagedTool, ManagedToolError> {
    let manifest = read_manifest(manifest_path)?;

    let host_arch = runtime.arch.as_deref().unwrap_or(std::env::consts::ARCH);
    let normalized_arch = supported_arch(host_arch)?;
    let platform_key = format!("{platform}-{normalized_arch}");

    let asset = manifest
        .assets
        .get(&platform_key)
        .ok_or_else(|| ManagedToolError::MissingReleaseAsset(platform_key.clone()))?;

    let executable_name = &manifest.binary;
    let cache_home = runtime
        .cache_home
        .clone()
        .or_else(|| std::env::var_os("XDG_CACHE_HOME").map(PathBuf::from))
        .unwrap_or_else(|| home.join(".cache"));

    let install_dir = cache_home
        .join("github-tools")
        .join(TOOL_NAME)
        .join("versions")
        .join(&manifest.version)
        .join(&platform_key);
    let executable = install_dir.join(executable_name);
    let receipt_path = install_dir.join("receipt.json");

    let receipt_data = ManagedToolReceipt {
        repository: manifest.repository.clone(),
        version: manifest.version.clone(),
        asset: asset.name.clone(),
        sha256: asset.sha256.clone(),
    };
    let formatted_receipt = format!(
        "{}\n",
        serde_json::to_string_pretty(&receipt_data).map_err(|e| {
            ManagedToolError::Install {
                version: manifest.version.clone(),
                message: e.to_string(),
            }
        })?
    );

    if !installed_tool_matches(&executable, &receipt_path, &formatted_receipt) {
        let parent_dir = install_dir
            .parent()
            .ok_or_else(|| ManagedToolError::Install {
                version: manifest.version.clone(),
                message: String::from("install dir has no parent"),
            })?;
        fs::create_dir_all(parent_dir).map_err(|e| ManagedToolError::Io {
            path: parent_dir.to_path_buf(),
            source: e,
        })?;

        let _ = fs::remove_dir_all(&install_dir);

        let stage_dir = tempfile::Builder::new()
            .prefix(".stage.")
            .tempdir_in(parent_dir)
            .map_err(|e| ManagedToolError::Io {
                path: parent_dir.to_path_buf(),
                source: e,
            })?;
        let stage_path = stage_dir.path();

        let archive_path = stage_path.join(&asset.name);
        let url = format!(
            "https://github.com/{}/releases/download/v{}/{}",
            manifest.repository, manifest.version, asset.name
        );

        let install_action = || -> Result<(), ManagedToolError> {
            if let Some(downloader) = &runtime.downloader {
                downloader.download(&url, &archive_path, install_timeout)?;
            } else {
                DefaultReqwestDownloader.download(&url, &archive_path, install_timeout)?;
            }

            verify_checksum(&archive_path, &asset.sha256)?;

            if let Some(extractor) = &runtime.extractor {
                extractor.extract(&archive_path, stage_path, executable_name, install_timeout)?;
            } else {
                DefaultTarExtractor.extract(
                    &archive_path,
                    stage_path,
                    executable_name,
                    install_timeout,
                )?;
            }

            let _ = fs::remove_file(&archive_path);

            let staged_exec = stage_path.join(executable_name);
            let metadata = fs::metadata(&staged_exec)
                .map_err(|_| ManagedToolError::MissingBinary(executable_name.clone()))?;
            if !metadata.is_file() {
                return Err(ManagedToolError::MissingBinary(executable_name.clone()));
            }

            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = fs::set_permissions(&staged_exec, fs::Permissions::from_mode(0o755));
            }

            fs::write(stage_path.join("receipt.json"), &formatted_receipt).map_err(|e| {
                ManagedToolError::Io {
                    path: stage_path.join("receipt.json"),
                    source: e,
                }
            })?;

            fs::rename(stage_path, &install_dir).map_err(|e| ManagedToolError::Io {
                path: install_dir.clone(),
                source: e,
            })?;

            Ok(())
        };

        if let Err(err) = install_action() {
            return Err(ManagedToolError::Install {
                version: manifest.version,
                message: err.to_string(),
            });
        }
    }

    Ok(PreparedManagedTool {
        name: String::from(TOOL_NAME),
        command: manifest.binary,
        executable,
        version: manifest.version,
        config_path: home.join(".cli-proxy-api").join("config.yaml"),
    })
}

/// Prepares all managed tools declared under `ssot_home`.
pub fn prepare_managed_tools(
    home: &Path,
    ssot_home: &Path,
    platform: &str,
    install_timeout: Duration,
    runtime: &ManagedToolRuntime,
) -> Result<Vec<PreparedManagedTool>, ManagedToolError> {
    let manifest_path = ssot_home.join(CLI_PROXY_SOURCE_DIR).join(RELEASE_FILE);
    if !manifest_path.exists() {
        return Ok(Vec::new());
    }

    let tool = prepare_cli_proxy(
        home,
        ssot_home,
        platform,
        &manifest_path,
        install_timeout,
        runtime,
    )?;
    Ok(vec![tool])
}

/// Health check: probes whether `CLIProxyAPI` is running at the client base URL.
/// Returns true if a connection to `{client_base_url}/models` is established, false on error/timeout.
#[must_use]
pub fn is_cli_proxy_running(client_base_url: &str, timeout: Duration) -> bool {
    let base = client_base_url.trim_end_matches('/');
    let url = format!("{base}/models");

    std::thread::scope(|scope| {
        scope
            .spawn(|| {
                let Ok(client) = reqwest::blocking::Client::builder()
                    .timeout(timeout)
                    .build()
                else {
                    return false;
                };

                client.get(&url).send().is_ok()
            })
            .join()
            .unwrap_or(false)
    })
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic
)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tempfile::tempdir;

    struct MockDownloader {
        download_count: AtomicUsize,
        content: Vec<u8>,
    }

    impl ManagedToolDownloader for MockDownloader {
        fn download(
            &self,
            _url: &str,
            destination: &Path,
            _timeout: Duration,
        ) -> Result<(), ManagedToolError> {
            self.download_count.fetch_add(1, Ordering::SeqCst);
            if let Some(parent) = destination.parent() {
                fs::create_dir_all(parent).unwrap();
            }
            fs::write(destination, &self.content).unwrap();
            Ok(())
        }
    }

    struct MockExtractor;

    impl ManagedToolExtractor for MockExtractor {
        fn extract(
            &self,
            _archive: &Path,
            destination: &Path,
            entry_name: &str,
            _timeout: Duration,
        ) -> Result<(), ManagedToolError> {
            let exec_path = destination.join(entry_name);
            fs::write(&exec_path, "#!/bin/sh\nexit 0\n").unwrap();
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = fs::set_permissions(&exec_path, fs::Permissions::from_mode(0o755));
            }
            Ok(())
        }
    }

    fn sample_manifest(checksum: &str) -> ReleaseManifest {
        let mut assets = HashMap::new();
        assets.insert(
            String::from("darwin-arm64"),
            ReleaseAsset {
                name: String::from("CLIProxyAPI_7.2.132_darwin_aarch64.tar.gz"),
                sha256: checksum.to_string(),
            },
        );
        ReleaseManifest {
            repository: String::from("router-for-me/CLIProxyAPI"),
            version: String::from("7.2.132"),
            binary: String::from("cli-proxy-api"),
            assets,
        }
    }

    #[test]
    fn test_supported_arch() {
        assert_eq!(supported_arch("arm64").unwrap(), "arm64");
        assert_eq!(supported_arch("aarch64").unwrap(), "arm64");
        assert_eq!(supported_arch("x64").unwrap(), "x64");
        assert_eq!(supported_arch("x86_64").unwrap(), "x64");
        assert_eq!(supported_arch("amd64").unwrap(), "x64");
        assert!(supported_arch("ia32").is_err());
        assert!(supported_arch("mips").is_err());
    }

    #[test]
    fn test_checksum_verification() {
        let tmp = tempdir().unwrap();
        let file_path = tmp.path().join("archive.tar.gz");
        fs::write(&file_path, b"test content").unwrap();

        // sha256("test content") = 94aec9fbed96ec...
        let expected = "6ae8a75555209fd6c44157c0aed8016e7638f8525a20ae616a140da8780dd005";
        assert!(verify_checksum(&file_path, expected).is_err());

        let actual = hex::encode(Sha256::digest(b"test content"));
        assert!(verify_checksum(&file_path, &actual).is_ok());
    }

    #[test]
    fn test_prepare_managed_tools_end_to_end_mocked() {
        let tmp = tempdir().unwrap();
        let home = tmp.path().join("home");
        let ssot_home = tmp.path().join("ssot");
        let cache_home = tmp.path().join("cache");
        fs::create_dir_all(&home).unwrap();
        fs::create_dir_all(&ssot_home).unwrap();

        let archive_bytes = b"fixture archive payload";
        let checksum = hex::encode(Sha256::digest(archive_bytes));

        let manifest = sample_manifest(&checksum);
        let manifest_dir = ssot_home.join(CLI_PROXY_SOURCE_DIR);
        fs::create_dir_all(&manifest_dir).unwrap();
        let manifest_file = manifest_dir.join(RELEASE_FILE);
        fs::write(
            &manifest_file,
            serde_json::to_string_pretty(&manifest).unwrap(),
        )
        .unwrap();

        let downloader = Arc::new(MockDownloader {
            download_count: AtomicUsize::new(0),
            content: archive_bytes.to_vec(),
        });
        let extractor = Arc::new(MockExtractor);

        let runtime = ManagedToolRuntime {
            arch: Some(String::from("arm64")),
            cache_home: Some(cache_home),
            downloader: Some(downloader.clone()),
            extractor: Some(extractor),
        };

        // First run: downloads and extracts
        let prepared_tools = prepare_managed_tools(
            &home,
            &ssot_home,
            "darwin",
            Duration::from_secs(5),
            &runtime,
        )
        .unwrap();

        assert_eq!(prepared_tools.len(), 1);
        let prepared_tool = &prepared_tools[0];
        assert_eq!(prepared_tool.name, "cliproxyapi");
        assert_eq!(prepared_tool.command, "cli-proxy-api");
        assert_eq!(prepared_tool.version, "7.2.132");
        assert!(prepared_tool.executable.exists());
        assert_eq!(downloader.download_count.load(Ordering::SeqCst), 1);

        // Second run: cached, does not download again
        let cached_tools = prepare_managed_tools(
            &home,
            &ssot_home,
            "darwin",
            Duration::from_secs(5),
            &runtime,
        )
        .unwrap();

        assert_eq!(cached_tools.len(), 1);
        assert_eq!(downloader.download_count.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn test_rejects_platform_without_asset() {
        let tmp = tempdir().unwrap();
        let home = tmp.path().join("home");
        let ssot_home = tmp.path().join("ssot");
        fs::create_dir_all(&home).unwrap();

        let manifest = sample_manifest("00".repeat(32).as_str());
        let manifest_dir = ssot_home.join(CLI_PROXY_SOURCE_DIR);
        fs::create_dir_all(&manifest_dir).unwrap();
        fs::write(
            manifest_dir.join(RELEASE_FILE),
            serde_json::to_string(&manifest).unwrap(),
        )
        .unwrap();

        let runtime = ManagedToolRuntime {
            arch: Some(String::from("arm64")),
            ..Default::default()
        };

        let result =
            prepare_managed_tools(&home, &ssot_home, "linux", Duration::from_secs(1), &runtime);
        assert!(result.is_err());
        assert!(
            result
                .unwrap_err()
                .to_string()
                .contains("no release asset for linux-arm64")
        );
    }
}
