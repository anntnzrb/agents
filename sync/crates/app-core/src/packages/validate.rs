use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;

use super::PackageError;

/// Recognized resource subdirectories for Pi packages.
pub const RESOURCE_KEYS: [&str; 4] = ["extensions", "skills", "prompts", "themes"];

static BUILTIN_PACKAGE_ROOTS: &[&str] = &[
    "assert",
    "buffer",
    "child_process",
    "cluster",
    "console",
    "constants",
    "crypto",
    "dgram",
    "diagnostics_channel",
    "dns",
    "domain",
    "events",
    "fs",
    "http",
    "http2",
    "https",
    "inspector",
    "module",
    "net",
    "os",
    "path",
    "perf_hooks",
    "process",
    "punycode",
    "querystring",
    "readline",
    "repl",
    "stream",
    "string_decoder",
    "timers",
    "tls",
    "tty",
    "url",
    "util",
    "v8",
    "vm",
    "worker_threads",
    "zlib",
];

#[allow(clippy::expect_used)]
static IMPORT_EXPORT_FROM_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r#"(?m)(?:import|export)\s+(?:type\s+)?(?:[\s\w*$,{}]*?\s+from\s+)?["']([^"'\r\n]+)["']"#,
    )
    .expect("valid import/export pattern")
});

#[allow(clippy::expect_used)]
static REQUIRE_IMPORT_CALL_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?m)(?:require|import)\s*\(\s*["']([^"'\r\n]+)["']\s*\)"#)
        .expect("valid require/import call pattern")
});

#[allow(clippy::expect_used)]
static VALID_PACKAGE_ROOT_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)^(@[a-z0-9_.-]+/)?([a-z0-9_.-]+)$").expect("valid package root pattern")
});

/// Extracts all import/export/require specifiers from JS/TS source code content.
#[must_use]
pub fn extract_import_specifiers(content: &str) -> Vec<String> {
    let mut specifiers = Vec::new();
    for captures in IMPORT_EXPORT_FROM_PATTERN.captures_iter(content) {
        if let Some(matched) = captures.get(1) {
            specifiers.push(matched.as_str().to_owned());
        }
    }
    for captures in REQUIRE_IMPORT_CALL_PATTERN.captures_iter(content) {
        if let Some(matched) = captures.get(1) {
            specifiers.push(matched.as_str().to_owned());
        }
    }
    specifiers
}

/// Extracts a clean npm package root name from an import specifier string.
#[must_use]
pub fn package_root_from_specifier(specifier: &str) -> Option<String> {
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

    let root = if let Some(after_at) = trimmed.strip_prefix('@') {
        let mut parts = after_at.split('/');
        let scope = parts.next()?;
        let pkg = parts.next()?;
        if scope.is_empty() || pkg.is_empty() {
            return None;
        }
        format!("@{scope}/{pkg}")
    } else {
        let mut parts = trimmed.split('/');
        let pkg = parts.next()?;
        if pkg.is_empty() {
            return None;
        }
        pkg.to_owned()
    };

    if VALID_PACKAGE_ROOT_PATTERN.is_match(&root) {
        Some(root)
    } else {
        None
    }
}

/// Checks if a package root is a Node.js builtin module.
#[must_use]
pub fn package_root_is_builtin(package_root: &str) -> bool {
    BUILTIN_PACKAGE_ROOTS.contains(&package_root)
}

/// Recursively discovers all JavaScript and TypeScript source files in a directory.
#[must_use]
pub fn package_source_files(root: &Path) -> Vec<PathBuf> {
    if !root.is_dir() {
        return Vec::new();
    }

    let mut files = Vec::new();
    for entry in walkdir::WalkDir::new(root).follow_links(true) {
        let Ok(entry) = entry else {
            continue;
        };
        let path = entry.path();
        let Ok(rel_path) = path.strip_prefix(root) else {
            continue;
        };

        let mut skip = false;
        for component in rel_path.components() {
            let s = component.as_os_str().to_string_lossy();
            if s == "node_modules" || s == ".git" {
                skip = true;
                break;
            }
        }
        if skip {
            continue;
        }

        if entry.file_type().is_file()
            && let Some(ext) = path.extension().and_then(|e| e.to_str())
            && matches!(ext, "ts" | "js" | "mts" | "cts" | "mjs" | "cjs")
        {
            files.push(path.to_path_buf());
        }
    }
    files
}

/// Identifies missing npm package dependencies imported by source files under the directory.
pub fn missing_package_roots(dir: &Path) -> Result<Vec<String>, PackageError> {
    if !dir.is_dir() {
        return Ok(Vec::new());
    }

    let mut missing = BTreeSet::new();
    for file in package_source_files(dir) {
        let content = fs::read_to_string(&file)?;
        for specifier in extract_import_specifiers(&content) {
            if let Some(root) = package_root_from_specifier(&specifier)
                && !package_root_is_builtin(&root)
                && !dir.join("node_modules").join(&root).exists()
            {
                missing.insert(root);
            }
        }
    }
    Ok(missing.into_iter().collect())
}

fn is_pattern_entry(value: &str) -> bool {
    value.starts_with('!')
        || value.starts_with('+')
        || value.starts_with('-')
        || value.contains('*')
        || value.contains('?')
}

fn validate_pi_manifest(
    dir: &Path,
    pi: &serde_json::Map<String, serde_json::Value>,
) -> Option<bool> {
    let mut has_entries = false;
    for key in RESOURCE_KEYS {
        if let Some(serde_json::Value::Array(entries)) = pi.get(key) {
            for entry in entries {
                if let Some(entry_str) = entry.as_str() {
                    if is_pattern_entry(entry_str) {
                        continue;
                    }
                    has_entries = true;
                    if !dir.join(entry_str).exists() {
                        return Some(false);
                    }
                }
            }
        }
    }

    if has_entries { Some(true) } else { None }
}

/// Checks whether `package.json` contains a `"build"` script.
pub fn package_has_build_script(dir: &Path) -> Result<bool, PackageError> {
    let package_json_path = dir.join("package.json");
    if !package_json_path.is_file() {
        return Ok(false);
    }

    let content = fs::read_to_string(&package_json_path)?;
    let value: serde_json::Value =
        json5::from_str(&content).or_else(|_| serde_json::from_str(&content))?;

    Ok(value
        .get("scripts")
        .and_then(|s| s.as_object())
        .is_some_and(|scripts| scripts.contains_key("build")))
}

/// Validates whether a package has no missing dependencies and contains valid resources.
pub fn package_is_healthy(dir: &Path) -> Result<bool, PackageError> {
    if !dir.is_dir() {
        return Ok(false);
    }

    let missing = missing_package_roots(dir)?;
    if !missing.is_empty() {
        return Ok(false);
    }

    let package_json_path = dir.join("package.json");
    if package_json_path.is_file() {
        let content = fs::read_to_string(&package_json_path)?;
        let value: serde_json::Value =
            json5::from_str(&content).or_else(|_| serde_json::from_str(&content))?;

        if let Some(pi) = value.get("pi").and_then(|p| p.as_object())
            && let Some(validated) = validate_pi_manifest(dir, pi)
        {
            return Ok(validated);
        }
    }

    Ok(RESOURCE_KEYS.iter().any(|key| dir.join(key).exists()))
}

/// Test alias matching legacy TypeScript helper `validatePackageForTests`.
pub fn validate_package_for_tests(dir: &Path) -> Result<bool, PackageError> {
    package_is_healthy(dir)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_extract_import_specifiers() {
        let sample = r#"
import fs from "node:fs";
import { createCommitTools } from "@oh-my-pi/pi-coding-agent";
export { helper } from "external-lib";
const code = 'file.content.includes("rename from ")';
const prose = "from lodash";
const dynamic = await import("dynamic-pkg");
const required = require("req-pkg");
"#;
        let extracted = extract_import_specifiers(sample);
        assert_eq!(
            extracted,
            vec![
                "node:fs",
                "@oh-my-pi/pi-coding-agent",
                "external-lib",
                "dynamic-pkg",
                "req-pkg"
            ]
        );
    }

    #[test]
    fn test_package_root_from_specifier() {
        assert_eq!(
            package_root_from_specifier("@oh-my-pi/pi-coding-agent"),
            Some("@oh-my-pi/pi-coding-agent".to_owned())
        );
        assert_eq!(
            package_root_from_specifier("@oh-my-pi/pi-coding-agent/sub/path"),
            Some("@oh-my-pi/pi-coding-agent".to_owned())
        );
        assert_eq!(
            package_root_from_specifier("lodash/debounce"),
            Some("lodash".to_owned())
        );
        assert_eq!(package_root_from_specifier("node:fs"), None);
        assert_eq!(package_root_from_specifier("./local"), None);
        assert_eq!(package_root_from_specifier("/absolute"), None);
        assert_eq!(package_root_from_specifier("bun"), None);
    }

    #[test]
    fn test_missing_package_roots() {
        let dir = tempdir().unwrap();
        let src = dir.path().join("src");
        fs::create_dir_all(&src).unwrap();
        fs::write(
            src.join("index.ts"),
            r#"
import { test } from "@oh-my-pi/pi-coding-agent";
const check = file.content.includes("\nrename from ") || file.content.startsWith("rename from ");
"#,
        )
        .unwrap();

        let missing = missing_package_roots(dir.path()).unwrap();
        assert_eq!(missing, vec!["@oh-my-pi/pi-coding-agent"]);

        fs::create_dir_all(dir.path().join("node_modules/@oh-my-pi/pi-coding-agent")).unwrap();
        let resolved = missing_package_roots(dir.path()).unwrap();
        assert_eq!(resolved, Vec::<String>::new());
    }

    #[test]
    fn test_package_is_healthy_manifest_and_conventional() {
        let dir = tempdir().unwrap();
        assert!(!package_is_healthy(dir.path()).unwrap());

        let skills_dir = dir.path().join("skills");
        fs::create_dir_all(&skills_dir).unwrap();
        fs::write(skills_dir.join("my-skill.txt"), "hello").unwrap();
        assert!(package_is_healthy(dir.path()).unwrap());
    }
}
