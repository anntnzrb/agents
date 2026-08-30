use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::plan::ExtensionDepsHookPlan;

pub const GENERATED_EXTENSION_ENTRY_NAMES: &[&str] =
    &["package.json", "node_modules", "bun.lock", "bun.lockb"];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExtensionHookStateFile {
    pub fingerprint: String,
    #[serde(rename = "generatedEntries")]
    pub generated_entries: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LoadedExtensionHookState {
    pub fingerprint: String,
    pub generated_entries: Vec<String>,
    pub original_count: usize,
    pub should_refresh_state: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PreparedExtensionHookState {
    pub fingerprint: String,
    pub generated_entries: Vec<String>,
    pub preserve_paths: Vec<String>,
    pub should_skip: bool,
    pub should_refresh_state: bool,
}

/// Prepares the execution state for an extension dependency hook.
#[must_use]
pub fn prepare_extension_hook_state(hook: &ExtensionDepsHookPlan) -> PreparedExtensionHookState {
    let fingerprint = fingerprint_tree(&hook.source_root);
    let previous_state = load_extension_hook_state(&hook.state_path);

    let Some(prev) = previous_state else {
        return PreparedExtensionHookState {
            fingerprint,
            generated_entries: Vec::new(),
            preserve_paths: Vec::new(),
            should_skip: false,
            should_refresh_state: false,
        };
    };

    if prev.fingerprint != fingerprint {
        return PreparedExtensionHookState {
            fingerprint,
            generated_entries: Vec::new(),
            preserve_paths: Vec::new(),
            should_skip: false,
            should_refresh_state: false,
        };
    }

    let existing_generated: Vec<String> = prev
        .generated_entries
        .into_iter()
        .filter(|entry_name| hook.root.join(entry_name).exists())
        .collect();

    let should_skip = existing_generated.len() == prev.original_count;
    let should_refresh_state = prev.should_refresh_state;

    let preserve_paths = if should_skip {
        existing_generated
            .iter()
            .map(|entry_name| join_relative(&hook.relative_root, entry_name))
            .collect()
    } else {
        Vec::new()
    };

    PreparedExtensionHookState {
        fingerprint,
        generated_entries: existing_generated,
        preserve_paths,
        should_skip,
        should_refresh_state,
    }
}

/// Records the resulting state of an extension hook to disk.
pub fn record_extension_hook_state(
    hook: &ExtensionDepsHookPlan,
    prepared_state: &PreparedExtensionHookState,
) -> io::Result<()> {
    let generated_entries: Vec<String> = GENERATED_EXTENSION_ENTRY_NAMES
        .iter()
        .filter(|&&entry_name| hook.root.join(entry_name).exists())
        .map(|&entry_name| entry_name.to_string())
        .collect();

    let state = ExtensionHookStateFile {
        fingerprint: prepared_state.fingerprint.clone(),
        generated_entries,
    };

    write_hook_state_file(&hook.state_path, &state)
}

/// Removes the extension hook state file if present.
pub fn clear_extension_hook_state(state_path: &Path) {
    let _ = fs::remove_file(state_path);
}

/// Computes a deterministic SHA-256 fingerprint for a directory tree.
#[must_use]
pub fn fingerprint_tree(root: &Path) -> String {
    let mut hasher = Sha256::new();
    if !root.exists() {
        hasher.update(b"missing");
        return hex::encode(hasher.finalize());
    }

    walk_tree(root, root, &mut hasher);
    hex::encode(hasher.finalize())
}

fn walk_tree(root: &Path, current: &Path, hasher: &mut Sha256) {
    let Ok(entries) = fs::read_dir(current) else {
        return;
    };

    let mut sorted_entries: Vec<fs::DirEntry> = entries.filter_map(Result::ok).collect();
    sorted_entries.sort_by_key(fs::DirEntry::file_name);

    for entry in sorted_entries {
        let file_name = entry.file_name();
        let name = file_name.to_string_lossy();

        if should_skip_entry(&name) {
            continue;
        }

        let absolute = entry.path();
        let Ok(relative) = absolute.strip_prefix(root) else {
            continue;
        };
        let rel_str = normalize_relative_path(relative);

        let Ok(symlink_meta) = entry.metadata() else {
            continue;
        };

        if symlink_meta.file_type().is_symlink() {
            if let Ok(target_meta) = fs::metadata(&absolute) {
                if target_meta.is_dir() {
                    hasher.update(format!("dir:{rel_str}\n").as_bytes());
                    walk_tree(root, &absolute, hasher);
                    continue;
                }
            } else {
                hasher.update(format!("broken:{rel_str}\n").as_bytes());
                continue;
            }
        }

        if symlink_meta.is_dir() {
            hasher.update(format!("dir:{rel_str}\n").as_bytes());
            walk_tree(root, &absolute, hasher);
            continue;
        }

        if symlink_meta.is_file() {
            hasher.update(format!("file:{rel_str}\n").as_bytes());
            if let Ok(bytes) = fs::read(&absolute) {
                hasher.update(&bytes);
            }
            hasher.update(b"\n");
        }
    }
}

fn load_extension_hook_state(path: &Path) -> Option<LoadedExtensionHookState> {
    let content = fs::read_to_string(path).ok()?;
    let parsed: serde_json::Value = json5::from_str(&content).ok()?;

    let obj = parsed.as_object()?;
    let fingerprint = obj.get("fingerprint")?.as_str()?.to_string();
    let entries_arr = obj.get("generatedEntries")?.as_array()?;

    let valid_names: HashSet<&str> = GENERATED_EXTENSION_ENTRY_NAMES.iter().copied().collect();
    let mut normalized_entries = Vec::new();

    for item in entries_arr {
        if let Some(s) = item.as_str()
            && !normalized_entries.contains(&s.to_string())
        {
            normalized_entries.push(s.to_string());
        }
    }
    normalized_entries.sort();

    let original_count = normalized_entries.len();
    let filtered_entries: Vec<String> = normalized_entries
        .into_iter()
        .filter(|e| valid_names.contains(e.as_str()))
        .collect();

    let should_refresh_state = filtered_entries.len() != original_count;

    Some(LoadedExtensionHookState {
        fingerprint,
        generated_entries: filtered_entries,
        original_count,
        should_refresh_state,
    })
}

fn write_hook_state_file(path: &Path, state: &ExtensionHookStateFile) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }

    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let base = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("hook-state.json");
    let pid = std::process::id();
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis());

    let temp_path = parent.join(format!(".{base}.{pid}.{nonce:x}.tmp"));

    let content = serde_json::to_string_pretty(state)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, format!("serialize state: {e}")))?;

    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)?;
    file.set_permissions(fs::Permissions::from_mode(0o644))?;
    file.write_all(content.as_bytes())?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    drop(file);

    if let Err(err) = fs::rename(&temp_path, path) {
        let _ = fs::remove_file(&temp_path);
        return Err(err);
    }

    Ok(())
}

fn should_skip_entry(name: &str) -> bool {
    name == "node_modules" || name == ".git" || name.starts_with('.')
}

fn normalize_relative_path(path: &Path) -> String {
    let mut parts = Vec::new();
    for comp in path.components() {
        if let std::path::Component::Normal(p) = comp {
            parts.push(p.to_string_lossy());
        }
    }
    parts.join("/")
}

fn join_relative(left: &str, right: &str) -> String {
    if left.is_empty() || left == "." {
        right.to_string()
    } else {
        format!("{left}/{right}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_fingerprint_tree_missing_root() {
        let missing = Path::new("/tmp/does_not_exist_agentium_test_root");
        let hash = fingerprint_tree(missing);
        assert_ne!(hash, "");
    }

    #[test]
    fn test_fingerprint_tree_deterministic() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        let file_a = temp.path().join("a.txt");
        let file_b = temp.path().join("b.txt");
        if let Err(e) = fs::write(&file_a, "hello") {
            panic!("write: {e}");
        }
        if let Err(e) = fs::write(&file_b, "world") {
            panic!("write: {e}");
        }

        let hash1 = fingerprint_tree(temp.path());
        let hash2 = fingerprint_tree(temp.path());
        assert_eq!(hash1, hash2);

        if let Err(e) = fs::write(&file_a, "hello modified") {
            panic!("write: {e}");
        }
        let hash3 = fingerprint_tree(temp.path());
        assert_ne!(hash1, hash3);
    }

    #[test]
    fn test_fingerprint_tree_skips_git_and_hidden() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        let git_dir = temp.path().join(".git");
        let hidden_file = temp.path().join(".hidden");
        if let Err(e) = fs::create_dir(&git_dir) {
            panic!("mkdir: {e}");
        }
        if let Err(e) = fs::write(&hidden_file, "secret") {
            panic!("write: {e}");
        }

        let hash_empty = fingerprint_tree(temp.path());

        let visible_file = temp.path().join("visible.txt");
        if let Err(e) = fs::write(&visible_file, "content") {
            panic!("write: {e}");
        }
        let hash_visible = fingerprint_tree(temp.path());
        assert_ne!(hash_empty, hash_visible);
    }

    #[test]
    fn test_hook_state_uses_legacy_generated_entries_key() {
        let state = ExtensionHookStateFile {
            fingerprint: "fingerprint".to_string(),
            generated_entries: vec!["package.json".to_string()],
        };

        let encoded = serde_json::to_value(state).unwrap();
        assert_eq!(
            encoded
                .get("generatedEntries")
                .and_then(|value| value.as_array()),
            Some(&vec![serde_json::json!("package.json")]),
        );
        assert!(encoded.get("generated_entries").is_none());
    }
}
