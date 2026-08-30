use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::harness::SyncEnv;
use crate::plan::{PlanError, SyncPlan, build_sync_plan, is_safe_managed_entry_name};
use crate::runtime::fs::rm_entry;

pub use crate::plan::top_level_entry_names;
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ManagedHarnessPlan {
    pub state_path: PathBuf,
    pub cleanup_paths: Vec<PathBuf>,
    pub current_entry_names: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ManagedSyncPlan {
    pub harnesses: Vec<ManagedHarnessPlan>,
}

/// Computes the managed entries plan directly from `SyncEnv`.
pub fn plan_managed_entries(sync_env: &SyncEnv) -> Result<ManagedSyncPlan, PlanError> {
    let sync_plan = build_sync_plan(sync_env)?;
    Ok(plan_managed_entries_for_sync_plan(&sync_plan))
}

/// Computes the cleanup and state recording plan for a built `SyncPlan`.
#[must_use]
pub fn plan_managed_entries_for_sync_plan(sync_plan: &SyncPlan) -> ManagedSyncPlan {
    let harnesses = sync_plan
        .harnesses
        .iter()
        .map(|harness_plan| {
            let current_entry_names = harness_plan.current_entry_names.clone();
            let current_set: HashSet<&str> =
                current_entry_names.iter().map(String::as_str).collect();

            let recorded = load_recorded_entry_names(&harness_plan.state_path);

            let mut stale_set = HashSet::new();
            for entry in &harness_plan.cleanup_entry_names {
                if !current_set.contains(entry.as_str()) {
                    stale_set.insert(entry.clone());
                }
            }
            for entry in &recorded {
                if !current_set.contains(entry.as_str()) {
                    stale_set.insert(entry.clone());
                }
            }

            let mut stale_sorted: Vec<String> = stale_set.into_iter().collect();
            stale_sorted.sort();

            let cleanup_paths: Vec<PathBuf> = stale_sorted
                .into_iter()
                .filter_map(|entry| cleanup_path(&harness_plan.root, &entry))
                .collect();

            ManagedHarnessPlan {
                state_path: harness_plan.state_path.clone(),
                cleanup_paths,
                current_entry_names,
            }
        })
        .collect();

    ManagedSyncPlan { harnesses }
}

/// Cleans stale entries from previous sync runs across all harnesses.
#[must_use]
pub fn clean_managed_entries(plan: &ManagedSyncPlan) -> bool {
    let mut success = true;
    for harness in &plan.harnesses {
        for path in &harness.cleanup_paths {
            if let Err(e) = rm_entry(path) {
                eprintln!("sync: error: cleanup failed: {} ({e})", path.display());
                success = false;
            }
        }
    }
    success
}

/// Persists current managed entry lists atomically to state files.
#[must_use]
pub fn record_managed_entries(plan: &ManagedSyncPlan) -> bool {
    let mut success = true;
    for harness in &plan.harnesses {
        if let Err(e) =
            write_recorded_entry_names(&harness.state_path, &harness.current_entry_names)
        {
            eprintln!("sync: error: managed state write failed: {e}");
            success = false;
        }
    }
    success
}

/// Loads recorded entry names from a managed state JSON file, filtering unsafe names.
#[must_use]
pub fn load_recorded_entry_names(path: &Path) -> Vec<String> {
    let content = match fs::read_to_string(path) {
        Ok(c) => c,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Vec::new(),
        Err(e) => {
            eprintln!("sync: warning: read {} ({e})", path.display());
            return Vec::new();
        }
    };

    let parsed: serde_json::Value = match json5::from_str(&content) {
        Ok(p) => p,
        Err(e) => {
            eprintln!(
                "sync: warning: managed state parse failed, ignoring {} ({e})",
                path.display()
            );
            return Vec::new();
        }
    };

    let Some(array) = parsed.as_array() else {
        eprintln!(
            "sync: warning: managed state parse failed, ignoring {} (not an array)",
            path.display()
        );
        return Vec::new();
    };

    let mut safe_names = HashSet::new();
    for item in array {
        let Some(name) = item.as_str() else {
            continue;
        };
        if is_safe_managed_entry_name(name) {
            safe_names.insert(name.to_string());
        } else {
            eprintln!(
                "sync: warning: ignoring unsafe managed entry {:?} in {}",
                name,
                path.display()
            );
        }
    }

    let mut sorted: Vec<String> = safe_names.into_iter().collect();
    sorted.sort();
    sorted
}

/// Atomically writes recorded entry names to disk if content has changed.
pub fn write_recorded_entry_names(path: &Path, entry_names: &[String]) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }

    let mut sorted_entries = entry_names.to_vec();
    sorted_entries.sort();

    let content = format!(
        "{}\n",
        serde_json::to_string_pretty(&sorted_entries)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?
    );

    // Skip if identical regular file already exists
    if let Ok(metadata) = fs::symlink_metadata(path)
        && metadata.file_type().is_file()
        && let Ok(existing) = fs::read_to_string(path)
        && existing == content
    {
        return Ok(());
    }

    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let base = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("managed-state.json");
    let pid = std::process::id();
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis());

    for attempt in 0..16 {
        let temp_path = parent.join(format!(".{base}.{pid}.{nonce:x}-{attempt}.tmp"));
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);

        match options.open(&temp_path) {
            Ok(mut file) => {
                let _ = file.set_permissions(fs::Permissions::from_mode(0o644));
                file.write_all(content.as_bytes())?;
                file.sync_all()?;
                drop(file);

                if let Err(e) = fs::rename(&temp_path, path) {
                    let _ = fs::remove_file(&temp_path);
                    return Err(e);
                }
                return Ok(());
            }
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
            Err(e) => return Err(e),
        }
    }

    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        format!(
            "create temporary managed state near {} (name collision)",
            path.display()
        ),
    ))
}

fn cleanup_path(root: &Path, entry_name: &str) -> Option<PathBuf> {
    if is_safe_managed_entry_name(entry_name) {
        Some(root.join(entry_name))
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_load_recorded_entry_names_filters_unsafe() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        let state_path = temp.path().join("state.json");
        let content = r#"[
  "good.txt",
  "..",
  "/tmp/escape",
  "nested/path",
  "good.txt"
]"#;
        if let Err(e) = fs::write(&state_path, content) {
            panic!("write: {e}");
        }

        let names = load_recorded_entry_names(&state_path);
        assert_eq!(names, vec!["good.txt"]);
    }

    #[test]
    fn test_write_recorded_entry_names_atomic_and_idempotent() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        let state_path = temp.path().join("state.json");
        let entries = vec!["beta".to_string(), "alpha".to_string()];

        if let Err(e) = write_recorded_entry_names(&state_path, &entries) {
            panic!("write: {e}");
        }

        let content = match fs::read_to_string(&state_path) {
            Ok(c) => c,
            Err(e) => panic!("read: {e}"),
        };
        assert_eq!(content, "[\n  \"alpha\",\n  \"beta\"\n]\n");

        let meta1 = match fs::metadata(&state_path) {
            Ok(m) => m,
            Err(e) => panic!("meta: {e}"),
        };

        // Write identical content -> should skip rewrite
        if let Err(e) = write_recorded_entry_names(&state_path, &entries) {
            panic!("write2: {e}");
        }
        let meta2 = match fs::metadata(&state_path) {
            Ok(m) => m,
            Err(e) => panic!("meta2: {e}"),
        };

        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            assert_eq!(meta1.ino(), meta2.ino());
        }
    }
}
