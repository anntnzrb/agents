use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value};
use wait_timeout::ChildExt;
use walkdir::WalkDir;

use super::{SyncEnv, command_exists, err, read_pipe, rm_entry};

const PACKAGE_SOURCE_FILE: &str = "packages.json";
const PACKAGE_CACHE_SUBDIR: &str = ".local/share/agents/pi-packages";
const RESOURCE_KEYS: [&str; 4] = ["extensions", "skills", "prompts", "themes"];

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct PackageManifest {
    pub(super) packages: Vec<String>,
}

pub(super) fn bootstrap_packages(sync_env: &SyncEnv) -> bool {
    let manifest_path = sync_env
        .tools_home
        .join("pi")
        .join("agent")
        .join(PACKAGE_SOURCE_FILE);
    let manifest = match read_package_manifest(&manifest_path) {
        Ok(manifest) => manifest,
        Err(message) => {
            err(&format!("package bootstrap failed: {message}"));
            return false;
        }
    };

    let runtime_settings_path = sync_env
        .tools
        .iter()
        .find(|tool| tool.name == "pi")
        .map(|tool| tool.root().join("settings.json"))
        .unwrap_or_else(|| {
            sync_env
                .tools_home
                .join("pi")
                .join("agent")
                .join("settings.json")
        });
    let cache_root = sync_env.home.join(PACKAGE_CACHE_SUBDIR);

    let mut installed_paths = Vec::new();
    let mut success = true;
    for source in &manifest.packages {
        match ensure_package(source, &cache_root, sync_env.install_timeout) {
            Ok(Some(path)) => installed_paths.push(path),
            Ok(None) => {}
            Err(message) => {
                err(&format!("package bootstrap failed for {source}: {message}"));
                success = false;
            }
        }
    }

    if let Err(message) = patch_runtime_settings(&runtime_settings_path, &installed_paths) {
        err(&format!("package settings patch failed: {message}"));
        success = false;
    }

    success
}

pub(super) fn read_package_manifest(path: &Path) -> Result<PackageManifest, String> {
    let content = match fs::read_to_string(path) {
        Ok(content) => content,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Ok(PackageManifest {
                packages: Vec::new(),
            });
        }
        Err(error) => return Err(format!("{} ({error})", path.display())),
    };

    let value: Value = serde_json::from_str(&content)
        .map_err(|error| format!("invalid JSON in {}: {error}", path.display()))?;
    let object = value
        .as_object()
        .ok_or_else(|| format!("{} must contain a JSON object", path.display()))?;
    let packages_value = object
        .get("packages")
        .ok_or_else(|| format!("{} missing \"packages\" array", path.display()))?;
    let packages_array = packages_value
        .as_array()
        .ok_or_else(|| format!("{} field \"packages\" must be an array", path.display()))?;

    let mut seen = HashSet::new();
    let mut packages = Vec::new();
    for entry in packages_array {
        let source = entry
            .as_str()
            .ok_or_else(|| format!("{} package entries must be strings", path.display()))?
            .trim();
        if source.is_empty() {
            return Err(format!(
                "{} package entries must not be empty",
                path.display()
            ));
        }
        if seen.insert(source.to_string()) {
            packages.push(source.to_string());
        }
    }

    Ok(PackageManifest { packages })
}

pub(super) fn package_cache_dir(cache_root: &Path, source: &str) -> PathBuf {
    let slug = source_slug(source);
    cache_root.join(format!("{slug}-{:016x}", fnv1a64(source)))
}

fn source_slug(source: &str) -> String {
    let trimmed = source.trim().trim_end_matches('/');
    let normalized = trimmed.strip_suffix(".git").unwrap_or(trimmed);
    let tail = normalized
        .split(['/', ':'])
        .filter(|part| !part.is_empty())
        .rev()
        .take(2)
        .collect::<Vec<_>>();
    let joined = if tail.is_empty() {
        "package".to_string()
    } else {
        tail.into_iter().rev().collect::<Vec<_>>().join("-")
    };

    let sanitized = joined
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>();
    let compact = sanitized
        .split('-')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("-");
    if compact.is_empty() {
        "package".to_string()
    } else {
        compact
    }
}

fn fnv1a64(input: &str) -> u64 {
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in input.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

fn ensure_package(
    source: &str,
    cache_root: &Path,
    timeout: Duration,
) -> Result<Option<PathBuf>, String> {
    let final_dir = package_cache_dir(cache_root, source);
    if package_is_healthy(&final_dir)? {
        return Ok(Some(final_dir));
    }

    fs::create_dir_all(cache_root)
        .map_err(|error| format!("create cache root {} ({error})", cache_root.display()))?;
    let staging_dir = staging_dir_for(&final_dir);
    rm_entry(&staging_dir)
        .map_err(|error| format!("clear staging dir {} ({error})", staging_dir.display()))?;
    fs::create_dir_all(staging_dir.parent().unwrap_or(cache_root))
        .map_err(|error| format!("create staging parent {} ({error})", staging_dir.display()))?;

    if !clone_package(source, &staging_dir, timeout) {
        let _ = rm_entry(&staging_dir);
        return Err("clone failed".to_string());
    }
    if !install_package_deps(&staging_dir, timeout) {
        let _ = rm_entry(&staging_dir);
        return Err("dependency install failed".to_string());
    }

    let mut healthy = package_is_healthy(&staging_dir)?;
    if !healthy && package_has_build_script(&staging_dir)? {
        if !run_package_build(&staging_dir, timeout) {
            let _ = rm_entry(&staging_dir);
            return Err("build failed".to_string());
        }
        if !install_inferred_import_packages(&staging_dir, timeout) {
            let _ = rm_entry(&staging_dir);
            return Err("install inferred packages after build failed".to_string());
        }
        healthy = package_is_healthy(&staging_dir)?;
    }

    if !healthy {
        let _ = rm_entry(&staging_dir);
        return Err("package resources failed validation".to_string());
    }

    replace_dir_atomically(&staging_dir, &final_dir)
        .map_err(|error| format!("activate package {} ({error})", final_dir.display()))?;
    Ok(Some(final_dir))
}

fn staging_dir_for(final_dir: &Path) -> PathBuf {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let pid = std::process::id();
    final_dir.with_extension(format!("staging-{pid}-{now}"))
}

fn replace_dir_atomically(src: &Path, dst: &Path) -> io::Result<()> {
    let backup = dst.with_extension("backup");
    rm_entry(&backup)?;
    if dst.exists() {
        fs::rename(dst, &backup)?;
    }
    match fs::rename(src, dst) {
        Ok(()) => {
            let _ = rm_entry(&backup);
            Ok(())
        }
        Err(error) => {
            if backup.exists() {
                let _ = fs::rename(&backup, dst);
            }
            Err(error)
        }
    }
}

fn package_is_healthy(dir: &Path) -> Result<bool, String> {
    if !dir.is_dir() {
        return Ok(false);
    }
    if !missing_package_roots(dir)?.is_empty() {
        return Ok(false);
    }

    let package_json_path = dir.join("package.json");
    if package_json_path.is_file() {
        let package_json = read_json_file(&package_json_path)?;
        if let Some(pi) = package_json.get("pi") {
            if let Some(result) = validate_pi_manifest(dir, pi)? {
                return Ok(result);
            }
        }
    }

    Ok(RESOURCE_KEYS.iter().any(|key| dir.join(key).exists()))
}

fn validate_pi_manifest(dir: &Path, pi: &Value) -> Result<Option<bool>, String> {
    let Some(object) = pi.as_object() else {
        return Ok(None);
    };

    let mut has_entries = false;
    for key in RESOURCE_KEYS {
        let Some(entries) = object.get(key).and_then(Value::as_array) else {
            continue;
        };
        for entry in entries {
            let Some(path) = entry.as_str() else {
                continue;
            };
            if is_pattern_entry(path) {
                continue;
            }
            has_entries = true;
            if !dir.join(path).exists() {
                return Ok(Some(false));
            }
        }
    }

    if has_entries {
        Ok(Some(true))
    } else {
        Ok(None)
    }
}

fn is_pattern_entry(value: &str) -> bool {
    value.starts_with('!')
        || value.starts_with('+')
        || value.starts_with('-')
        || value.contains('*')
        || value.contains('?')
}

fn package_has_build_script(dir: &Path) -> Result<bool, String> {
    let package_json_path = dir.join("package.json");
    if !package_json_path.is_file() {
        return Ok(false);
    }
    let package_json = read_json_file(&package_json_path)?;
    Ok(package_json
        .get("scripts")
        .and_then(Value::as_object)
        .is_some_and(|scripts| scripts.contains_key("build")))
}

fn read_json_file(path: &Path) -> Result<Value, String> {
    let content =
        fs::read_to_string(path).map_err(|error| format!("read {} ({error})", path.display()))?;
    serde_json::from_str(&content).map_err(|error| format!("parse {} ({error})", path.display()))
}

fn clone_package(source: &str, target_dir: &Path, timeout: Duration) -> bool {
    clone_package_with_runner(source, target_dir, command_exists("gh"), |command| {
        run_command(command, None, timeout, "clone")
    })
}

fn clone_package_with_runner<F>(
    source: &str,
    target_dir: &Path,
    gh_available: bool,
    mut runner: F,
) -> bool
where
    F: FnMut(&[String]) -> bool,
{
    for command in clone_commands(source, target_dir, gh_available) {
        if runner(&command) {
            return true;
        }
    }
    false
}

fn clone_commands(source: &str, target_dir: &Path, gh_available: bool) -> Vec<Vec<String>> {
    let mut commands = Vec::new();
    if let Some(slug) = github_repo_slug(source).filter(|_| gh_available) {
        commands.push(vec![
            "gh".to_string(),
            "repo".to_string(),
            "clone".to_string(),
            slug,
            target_dir.to_string_lossy().to_string(),
            "--".to_string(),
            "--depth=1".to_string(),
        ]);
    }
    commands.push(vec![
        "git".to_string(),
        "clone".to_string(),
        "--depth=1".to_string(),
        source.to_string(),
        target_dir.to_string_lossy().to_string(),
    ]);
    commands
}

fn github_repo_slug(source: &str) -> Option<String> {
    let trimmed = source.trim();
    let normalized = trimmed.strip_suffix(".git").unwrap_or(trimmed);
    if let Some(rest) = normalized.strip_prefix("https://github.com/") {
        return split_owner_repo(rest);
    }
    if let Some(rest) = normalized.strip_prefix("http://github.com/") {
        return split_owner_repo(rest);
    }
    if let Some(rest) = normalized.strip_prefix("git@github.com:") {
        return split_owner_repo(rest);
    }
    None
}

fn split_owner_repo(rest: &str) -> Option<String> {
    let parts = rest
        .split('/')
        .filter(|part| !part.is_empty())
        .take(2)
        .collect::<Vec<_>>();
    if parts.len() != 2 {
        return None;
    }
    Some(format!("{}/{}", parts[0], parts[1]))
}

fn install_package_deps(dir: &Path, timeout: Duration) -> bool {
    if !dir.join("package.json").is_file() {
        return true;
    }
    let Some(tool) = js_runner() else {
        err(&format!(
            "no JS package manager available for {}",
            dir.display()
        ));
        return false;
    };
    let install_command = vec![tool.to_string(), "install".to_string()];
    if !run_command(&install_command, Some(dir), timeout, "install") {
        return false;
    }
    install_inferred_import_packages(dir, timeout)
}

pub(super) fn install_inferred_import_packages(dir: &Path, timeout: Duration) -> bool {
    let missing = match missing_package_roots(dir) {
        Ok(missing) => missing,
        Err(message) => {
            err(&format!(
                "dependency scan failed in {}: {message}",
                dir.display()
            ));
            return false;
        }
    };
    if missing.is_empty() {
        return true;
    }
    if !ensure_install_project(dir) {
        return false;
    }

    let Some(tool) = js_runner() else {
        err(&format!(
            "no JS package manager available for inferred imports in {}",
            dir.display()
        ));
        return false;
    };
    let command = if tool == "bun" {
        let mut command = vec![tool.to_string(), "add".to_string(), "--no-save".to_string()];
        command.extend(missing);
        command
    } else {
        let mut command = vec![
            tool.to_string(),
            "install".to_string(),
            "--no-save".to_string(),
        ];
        command.extend(missing);
        command
    };
    run_command(&command, Some(dir), timeout, "install inferred packages")
}

fn ensure_install_project(dir: &Path) -> bool {
    let package_json = dir.join("package.json");
    if package_json.is_file() {
        return true;
    }
    match fs::write(
        &package_json,
        "{\n  \"name\": \"pi-extension-deps\",\n  \"private\": true\n}\n",
    ) {
        Ok(()) => true,
        Err(error) => {
            err(&format!("write {} ({error})", package_json.display()));
            false
        }
    }
}

fn missing_package_roots(dir: &Path) -> Result<Vec<String>, String> {
    let mut missing = HashSet::new();
    for file in package_source_files(dir) {
        let content = fs::read_to_string(&file)
            .map_err(|error| format!("read {} ({error})", file.display()))?;
        for specifier in extract_import_specifiers(&content) {
            let Some(package_root) = package_root_from_specifier(&specifier) else {
                continue;
            };
            if package_root_is_builtin(&package_root) {
                continue;
            }
            if !dir.join("node_modules").join(&package_root).exists() {
                missing.insert(package_root);
            }
        }
    }
    let mut missing = missing.into_iter().collect::<Vec<_>>();
    missing.sort();
    Ok(missing)
}

fn package_source_files(root: &Path) -> Vec<PathBuf> {
    if !root.is_dir() {
        return Vec::new();
    }
    WalkDir::new(root)
        .follow_links(true)
        .into_iter()
        .filter_entry(|entry| {
            let name = entry.file_name().to_string_lossy();
            !(entry.file_type().is_dir()
                && (name.starts_with('.') || name == "node_modules" || name == ".git"))
        })
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().is_file())
        .filter_map(|entry| {
            let path = entry.into_path();
            let extension = path.extension().and_then(|ext| ext.to_str());
            match extension {
                Some("ts" | "js" | "mts" | "cts" | "mjs" | "cjs") => Some(path),
                _ => None,
            }
        })
        .collect()
}

fn extract_import_specifiers(content: &str) -> Vec<String> {
    const PREFIXES: [&str; 8] = [
        "from \"",
        "from '",
        "import \"",
        "import '",
        "require(\"",
        "require('",
        "import(\"",
        "import('",
    ];

    let mut specifiers = Vec::new();
    for prefix in PREFIXES {
        let quote = prefix.chars().last().unwrap_or('"');
        let mut remainder = content;
        while let Some(index) = remainder.find(prefix) {
            let after_prefix = &remainder[index + prefix.len()..];
            if let Some(end) = after_prefix.find(quote) {
                specifiers.push(after_prefix[..end].to_string());
                remainder = &after_prefix[end + 1..];
            } else {
                break;
            }
        }
    }
    specifiers
}

fn package_root_from_specifier(specifier: &str) -> Option<String> {
    let trimmed = specifier.trim();
    if trimmed.is_empty()
        || trimmed.starts_with('.')
        || trimmed.starts_with('/')
        || trimmed.starts_with("node:")
        || trimmed.starts_with("bun:")
        || trimmed.starts_with("data:")
        || trimmed == "bun"
    {
        return None;
    }

    if let Some(stripped) = trimmed.strip_prefix('@') {
        let parts = stripped.split('/').collect::<Vec<_>>();
        if parts.len() < 2 {
            return None;
        }
        return Some(format!("@{}/{}", parts[0], parts[1]));
    }

    trimmed.split('/').next().map(ToString::to_string)
}

fn package_root_is_builtin(package_root: &str) -> bool {
    matches!(
        package_root,
        "assert"
            | "buffer"
            | "child_process"
            | "cluster"
            | "console"
            | "constants"
            | "crypto"
            | "dgram"
            | "diagnostics_channel"
            | "dns"
            | "domain"
            | "events"
            | "fs"
            | "http"
            | "http2"
            | "https"
            | "inspector"
            | "module"
            | "net"
            | "os"
            | "path"
            | "perf_hooks"
            | "process"
            | "punycode"
            | "querystring"
            | "readline"
            | "repl"
            | "stream"
            | "string_decoder"
            | "timers"
            | "tls"
            | "tty"
            | "url"
            | "util"
            | "v8"
            | "vm"
            | "worker_threads"
            | "zlib"
    )
}

fn run_package_build(dir: &Path, timeout: Duration) -> bool {
    let Some(tool) = js_runner() else {
        err(&format!(
            "no JS runtime available for build in {}",
            dir.display()
        ));
        return false;
    };
    let command = vec![tool.to_string(), "run".to_string(), "build".to_string()];
    run_command(&command, Some(dir), timeout, "build")
}

fn js_runner() -> Option<&'static str> {
    if command_exists("bun") {
        return Some("bun");
    }
    if command_exists("npm") {
        return Some("npm");
    }
    None
}

fn run_command(command: &[String], cwd: Option<&Path>, timeout: Duration, action: &str) -> bool {
    let mut child = match Command::new(&command[0])
        .args(&command[1..])
        .current_dir(cwd.unwrap_or_else(|| Path::new(".")))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            err(&format!("missing command for {action}: {}", command[0]));
            return false;
        }
        Err(error) => panic!("{error}"),
    };

    let stdout = child
        .stdout
        .take()
        .unwrap_or_else(|| panic!("missing stdout pipe for {}", command[0]));
    let stderr = child
        .stderr
        .take()
        .unwrap_or_else(|| panic!("missing stderr pipe for {}", command[0]));
    let stdout_handle = thread::spawn(move || read_pipe(stdout));
    let stderr_handle = thread::spawn(move || read_pipe(stderr));

    match child.wait_timeout(timeout) {
        Ok(Some(status)) => {
            let stdout_text =
                String::from_utf8_lossy(&stdout_handle.join().unwrap_or_default()).into_owned();
            let stderr_text =
                String::from_utf8_lossy(&stderr_handle.join().unwrap_or_default()).into_owned();
            if status.success() {
                return true;
            }
            let detail = if !stderr_text.trim().is_empty() {
                stderr_text.trim().to_string()
            } else if !stdout_text.trim().is_empty() {
                stdout_text.trim().to_string()
            } else {
                "unknown error".to_string()
            };
            err(&format!(
                "{action} failed: {} ({detail})",
                command.join(" ")
            ));
            false
        }
        Ok(None) => {
            let _ = child.kill();
            let _ = child.wait();
            let _ = stdout_handle.join();
            let _ = stderr_handle.join();
            err(&format!("{action} timed out: {}", command.join(" ")));
            false
        }
        Err(error) => panic!("{error}"),
    }
}

pub(super) fn patch_runtime_settings(path: &Path, package_paths: &[PathBuf]) -> Result<(), String> {
    let current = match fs::read_to_string(path) {
        Ok(content) => content,
        Err(error) if error.kind() == io::ErrorKind::NotFound => "{}".to_string(),
        Err(error) => return Err(format!("read {} ({error})", path.display())),
    };
    let mut value: Value = serde_json::from_str(&current)
        .map_err(|error| format!("parse {} ({error})", path.display()))?;
    if !value.is_object() {
        value = Value::Object(Map::new());
    }
    let object = value
        .as_object_mut()
        .ok_or_else(|| format!("{} must contain a JSON object", path.display()))?;
    object.insert(
        "packages".to_string(),
        Value::Array(
            package_paths
                .iter()
                .map(|path| Value::String(path.to_string_lossy().to_string()))
                .collect(),
        ),
    );

    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("create {} ({error})", parent.display()))?;
    }
    let content = serde_json::to_string_pretty(&value)
        .map_err(|error| format!("serialize {} ({error})", path.display()))?;
    fs::write(path, format!("{content}\n"))
        .map_err(|error| format!("write {} ({error})", path.display()))
}

#[cfg(test)]
pub(super) fn github_slug_for_tests(source: &str) -> Option<String> {
    github_repo_slug(source)
}

#[cfg(test)]
pub(super) fn command_for_tests(source: &str, target_dir: &Path) -> Vec<String> {
    clone_commands(source, target_dir, true)
        .into_iter()
        .next()
        .unwrap_or_else(|| panic!("missing clone command"))
}

#[cfg(test)]
pub(super) fn clone_attempts_for_tests(
    source: &str,
    target_dir: &Path,
    gh_available: bool,
    outcomes: &[bool],
) -> (bool, Vec<Vec<String>>) {
    let mut attempts = Vec::new();
    let mut outcomes = outcomes.iter().copied();
    let result = clone_package_with_runner(source, target_dir, gh_available, |command| {
        attempts.push(command.to_vec());
        outcomes.next().unwrap_or(false)
    });
    (result, attempts)
}

#[cfg(test)]
pub(super) fn validate_package_for_tests(dir: &Path) -> Result<bool, String> {
    package_is_healthy(dir)
}
