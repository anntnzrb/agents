use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;
use walkdir::WalkDir;

use super::RESOURCE_KEYS;

pub(super) fn package_is_healthy(dir: &Path) -> Result<bool, String> {
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

pub(super) fn package_has_build_script(dir: &Path) -> Result<bool, String> {
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

pub(super) fn missing_package_roots(dir: &Path) -> Result<Vec<String>, String> {
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

fn read_json_file(path: &Path) -> Result<Value, String> {
    let content =
        fs::read_to_string(path).map_err(|error| format!("read {} ({error})", path.display()))?;
    serde_json::from_str(&content).map_err(|error| format!("parse {} ({error})", path.display()))
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

#[cfg(test)]
pub(super) fn validate_package_for_tests(dir: &Path) -> Result<bool, String> {
    package_is_healthy(dir)
}
