use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use super::harness::{Harness, SyncEnv};
use super::{err, rm_entry};

#[derive(Clone, Debug)]
pub(super) struct ManagedSyncPlan {
    harnesses: Vec<ManagedHarnessPlan>,
}

#[derive(Clone, Debug)]
struct ManagedHarnessPlan {
    state_path: PathBuf,
    cleanup_paths: Vec<PathBuf>,
    current_entry_names: Vec<String>,
}

pub(super) fn plan_managed_entries(sync_env: &SyncEnv) -> Result<ManagedSyncPlan, String> {
    let harnesses = sync_env
        .harnesses
        .iter()
        .map(|harness| plan_harness(sync_env, harness))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(ManagedSyncPlan { harnesses })
}

pub(super) fn clean_managed_entries(plan: &ManagedSyncPlan) -> bool {
    let mut success = true;
    for harness in &plan.harnesses {
        for path in &harness.cleanup_paths {
            if let Err(error) = rm_entry(path) {
                err(&format!("cleanup failed: {} ({error})", path.display()));
                success = false;
            }
        }
    }
    success
}

pub(super) fn record_managed_entries(plan: &ManagedSyncPlan) -> bool {
    let mut success = true;
    for harness in &plan.harnesses {
        if let Err(message) =
            write_recorded_entry_names(&harness.state_path, &harness.current_entry_names)
        {
            err(&format!("managed state write failed: {message}"));
            success = false;
        }
    }
    success
}

pub(super) fn asset_dir_names(path: &Path) -> Result<Vec<String>, String> {
    dir_entry_names(path, true)
}

pub(super) fn top_level_entry_names(path: &Path) -> Result<Vec<String>, String> {
    dir_entry_names(path, false)
}

fn dir_entry_names(path: &Path, dirs_only: bool) -> Result<Vec<String>, String> {
    if !path.is_dir() {
        return Ok(Vec::new());
    }

    let entries =
        fs::read_dir(path).map_err(|error| format!("read {} ({error})", path.display()))?;
    let mut names = Vec::new();
    for entry_result in entries {
        let entry = entry_result.map_err(|error| format!("read {} ({error})", path.display()))?;
        let file_type = entry
            .file_type()
            .map_err(|error| format!("stat {} ({error})", entry.path().display()))?;
        if dirs_only && !file_type.is_dir() {
            continue;
        }

        let name = entry.file_name();
        let name = name
            .to_str()
            .ok_or_else(|| format!("invalid UTF-8 path: {}", entry.path().display()))?;
        names.push(name.to_string());
    }
    names.sort();
    Ok(names)
}

fn plan_harness(sync_env: &SyncEnv, harness: &Harness) -> Result<ManagedHarnessPlan, String> {
    let current_entry_names = current_managed_entry_names(sync_env, harness)?;
    let state_path = harness.managed_state_path(&sync_env.managed_state_home);
    let mut cleanup_entry_names = BTreeSet::new();
    cleanup_entry_names.extend(current_entry_names.iter().cloned());
    cleanup_entry_names.extend(
        harness
            .compat_managed_entries
            .iter()
            .map(|entry| (*entry).to_string()),
    );
    cleanup_entry_names.extend(load_recorded_entry_names(&state_path)?);

    Ok(ManagedHarnessPlan {
        state_path,
        cleanup_paths: cleanup_entry_names
            .into_iter()
            .map(|entry| harness.root().join(entry))
            .collect(),
        current_entry_names,
    })
}

fn current_managed_entry_names(
    sync_env: &SyncEnv,
    harness: &Harness,
) -> Result<Vec<String>, String> {
    let mut names = BTreeSet::new();
    names.insert(harness.instruction_file_name().to_string());

    for entry_name in top_level_entry_names(&harness.source_root(&sync_env.tools_home))? {
        names.insert(entry_name);
    }

    for asset_name in asset_dir_names(&sync_env.assets_home)? {
        names.insert(harness.rename_asset(&asset_name));
    }

    Ok(names.into_iter().collect())
}

fn load_recorded_entry_names(path: &Path) -> Result<Vec<String>, String> {
    let content = match fs::read_to_string(path) {
        Ok(content) => content,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(format!("read {} ({error})", path.display())),
    };

    let recorded: Vec<String> = serde_json::from_str(&content)
        .map_err(|error| format!("parse {} ({error})", path.display()))?;
    Ok(recorded
        .into_iter()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect())
}

fn write_recorded_entry_names(path: &Path, entry_names: &[String]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("create {} ({error})", parent.display()))?;
    }
    let content = serde_json::to_string_pretty(entry_names)
        .map_err(|error| format!("serialize {} ({error})", path.display()))?;
    fs::write(path, format!("{content}\n"))
        .map_err(|error| format!("write {} ({error})", path.display()))
}
