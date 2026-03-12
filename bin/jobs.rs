use std::path::{Path, PathBuf};

use super::harness::{SOURCE_AGENT_FILE, SyncEnv};
use super::managed::asset_dir_names;
use super::{copy_tree, err, is_symlink, panic_message, rm_entry};

#[derive(Clone, Copy, Debug)]
pub(super) enum JobKind {
    File,
    Dir,
}

#[derive(Clone, Debug)]
pub(super) struct Job {
    src: PathBuf,
    dst: PathBuf,
    kind: JobKind,
}

pub(super) fn copy_item(src: &Path, dst: &Path) -> bool {
    if !src.exists() && !is_symlink(src) {
        err(&format!("missing source: {}", src.display()));
        return true;
    }

    if let Some(parent) = dst.parent() {
        std::fs::create_dir_all(parent).unwrap_or_else(|error| panic!("{error}"));
    }
    rm_entry(dst).unwrap_or_else(|error| panic!("{error}"));

    let result = if src.is_dir() {
        copy_tree(src, dst)
    } else {
        std::fs::copy(src, dst).map(|_| ())
    };

    if let Err(error) = result {
        err(&format!(
            "copy failed: {} -> {} ({error})",
            src.display(),
            dst.display()
        ));
        return false;
    }

    true
}

pub(super) fn copy_dir_into(src_dir: &Path, dst_dir: &Path) -> bool {
    if !src_dir.is_dir() {
        err(&format!("missing directory: {}", src_dir.display()));
        return true;
    }

    std::fs::create_dir_all(dst_dir).unwrap_or_else(|error| panic!("{error}"));
    if let Err(error) = copy_tree(src_dir, dst_dir) {
        err(&format!(
            "copy failed: {} -> {} ({error})",
            src_dir.display(),
            dst_dir.display()
        ));
        return false;
    }

    true
}

pub(super) fn iter_jobs(sync_env: &SyncEnv) -> Result<Vec<Job>, String> {
    let mut jobs = harness_dirs(sync_env);
    jobs.extend(asset_copies(sync_env)?);
    jobs.extend(agent_files(sync_env));
    jobs.extend(config_files(sync_env));
    Ok(jobs)
}

pub(super) fn run_jobs(jobs: &[Job]) -> bool {
    jobs.iter().all(run_job)
}

fn run_job(job: &Job) -> bool {
    let (name, handler): (&str, fn(&Path, &Path) -> bool) = match job.kind {
        JobKind::Dir => ("copy_dir_into", copy_dir_into),
        JobKind::File => ("copy_item", copy_item),
    };

    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| handler(&job.src, &job.dst))) {
        Ok(result) => result,
        Err(payload) => {
            err(&format!(
                "unexpected error in {name}: {}",
                panic_message(payload)
            ));
            false
        }
    }
}

fn harness_dirs(sync_env: &SyncEnv) -> Vec<Job> {
    sync_env
        .harnesses
        .iter()
        .map(|harness| Job {
            src: harness.source_root(&sync_env.tools_home),
            dst: harness.root(),
            kind: JobKind::Dir,
        })
        .collect()
}

fn asset_copies(sync_env: &SyncEnv) -> Result<Vec<Job>, String> {
    let asset_names = asset_dir_names(&sync_env.assets_home)?;
    let mut jobs = Vec::new();
    for asset_name in asset_names {
        let asset_path = sync_env.assets_home.join(&asset_name);
        for harness in &sync_env.harnesses {
            jobs.push(Job {
                src: asset_path.clone(),
                dst: harness.root().join(harness.rename_asset(&asset_name)),
                kind: JobKind::Dir,
            });
        }
    }
    Ok(jobs)
}

fn agent_files(sync_env: &SyncEnv) -> Vec<Job> {
    sync_env
        .harnesses
        .iter()
        .map(|harness| Job {
            src: sync_env.assets_home.join(SOURCE_AGENT_FILE),
            dst: harness.instruction_target(),
            kind: JobKind::File,
        })
        .collect()
}

fn config_files(sync_env: &SyncEnv) -> Vec<Job> {
    vec![Job {
        src: sync_env.assets_home.join("mcporter.jsonc"),
        dst: sync_env.mcporter_home.join("mcporter.json"),
        kind: JobKind::File,
    }]
}
