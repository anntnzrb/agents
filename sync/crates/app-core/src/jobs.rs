use std::collections::HashMap;
use std::fs;
use std::hash::BuildHasher;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

use crate::cliproxy::config::{
    CliProxyConfigSyncOptions, sync_cli_proxy_config, sync_client_model_catalog,
};
use crate::cliproxy::deployment::{
    CliProxyEndpointPublication, CliProxyEndpointSyncOptions, is_cli_proxy_target_ready,
    publish_cli_proxy_endpoint_templates,
};
pub use crate::plan::Job as SyncJob;
use crate::plan::{DirScope, Job};
use crate::runtime::fs::{copy_tree, is_symlink, rm_entry};
use crate::secret_template::sync_secret_template;

#[derive(Debug, Clone, Default)]
pub struct JobRunOptions {
    pub force_model_refresh: Option<bool>,
    pub quiet_model_refresh: Option<bool>,
}

#[derive(Debug, Default)]
struct JobRunState {
    cli_proxy_target_ready: Option<bool>,
}

/// Copies a single item (file or directory) to destination.
#[must_use]
pub fn copy_item(src: &Path, dst: &Path) -> bool {
    if !src.exists() && !is_symlink(src) {
        eprintln!("sync: error: missing source: {}", src.display());
        return true;
    }

    if let Some(parent) = dst.parent()
        && let Err(e) = fs::create_dir_all(parent)
    {
        eprintln!(
            "sync: error: copy failed: {} -> {} ({e})",
            src.display(),
            dst.display()
        );
        return false;
    }

    let _ = rm_entry(dst);
    if src.is_dir() {
        copy_tree(src, dst).is_ok()
    } else {
        match fs::copy(src, dst) {
            Ok(_) => true,
            Err(e) => {
                eprintln!(
                    "sync: error: copy failed: {} -> {} ({e})",
                    src.display(),
                    dst.display()
                );
                false
            }
        }
    }
}

/// Copies direct children of `src_dir` into `dst_dir`.
#[must_use]
pub fn copy_dir_into(src_dir: &Path, dst_dir: &Path) -> bool {
    if !src_dir.is_dir() {
        eprintln!("sync: error: missing directory: {}", src_dir.display());
        return true;
    }

    if let Err(e) = fs::create_dir_all(dst_dir) {
        eprintln!(
            "sync: error: copy failed: {} -> {} ({e})",
            src_dir.display(),
            dst_dir.display()
        );
        return false;
    }

    let preserve: &[&str] = &[];
    crate::runtime::fs::sync_managed_children(src_dir, dst_dir, preserve, None).is_ok()
}

/// Runs a sequence of synchronization jobs, respecting preserve paths.
#[must_use]
pub fn run_jobs_with_preserve<S: BuildHasher>(
    jobs: &[Job],
    preserve_paths_by_dst: &HashMap<PathBuf, Vec<String>, S>,
    options: &JobRunOptions,
) -> bool {
    let mut state = JobRunState::default();
    for job in jobs {
        if !run_job(job, preserve_paths_by_dst, options, &mut state) {
            return false;
        }
    }
    true
}

#[allow(clippy::too_many_lines)]
fn run_job<S: BuildHasher>(
    job: &Job,
    preserve_paths_by_dst: &HashMap<PathBuf, Vec<String>, S>,
    options: &JobRunOptions,
    state: &mut JobRunState,
) -> bool {
    match job {
        Job::Dir {
            src,
            dst,
            scope,
            preserve_paths,
        } => {
            let mut all_preserve = preserve_paths.clone();
            if let Some(extra) = preserve_paths_by_dst.get(dst) {
                all_preserve.extend(extra.iter().cloned());
            }

            match scope {
                DirScope::Children => sync_dir_into(src, dst, &all_preserve),
                DirScope::Tree => sync_managed_dir(src, dst, &all_preserve),
            }
        }
        Job::File { src, dst } => sync_item(src, dst),
        Job::SecretTemplate {
            src,
            dst,
            secrets_path,
        } => {
            if !src.exists() {
                eprintln!("sync: error: missing source: {}", src.display());
                return true;
            }
            if !secrets_path.exists() {
                eprintln!(
                    "sync: warning: missing local secrets {}; skipping {}",
                    secrets_path.display(),
                    dst.display()
                );
                return true;
            }
            match sync_secret_template(src, dst, secrets_path) {
                Ok(()) => true,
                Err(e) => {
                    eprintln!("sync: error: secret template sync failed: {e}");
                    false
                }
            }
        }
        Job::CliProxyReadiness {
            deployment,
            gateway_host,
        } => {
            if *gateway_host {
                return true;
            }
            let ready = is_cli_proxy_target_ready(deployment, None, None);
            state.cli_proxy_target_ready = Some(ready);
            if !ready {
                eprintln!(
                    "sync: warning: CLIProxyAPI endpoint is not ready; preserving existing client artifacts"
                );
            }
            true
        }
        Job::CliProxyEndpointTemplates {
            targets,
            deployment,
        } => {
            if state.cli_proxy_target_ready == Some(false) {
                return true;
            }
            let skip_readiness = state.cli_proxy_target_ready == Some(true);
            let options = CliProxyEndpointSyncOptions {
                skip_readiness,
                timeout: None,
            };
            match publish_cli_proxy_endpoint_templates(targets, deployment, None, &options) {
                Ok(CliProxyEndpointPublication::Published) => true,
                Ok(CliProxyEndpointPublication::Skipped) => {
                    if !targets.is_empty() {
                        eprintln!(
                            "sync: warning: CLIProxyAPI endpoint is not ready; preserving existing harness endpoints"
                        );
                    }
                    true
                }
                Err(e) => {
                    eprintln!("sync: error: endpoint template publication failed: {e}");
                    false
                }
            }
        }
        Job::CliProxyConfig {
            src,
            dst,
            secrets_path,
            deployment,
            gateway_host,
            cache_root,
            runtime_root,
        } => {
            if state.cli_proxy_target_ready == Some(false) {
                return true;
            }
            if !src.exists() {
                eprintln!("sync: error: missing source: {}", src.display());
                return true;
            }

            let config_options = CliProxyConfigSyncOptions {
                write_server_config: *gateway_host,
                cache_root: cache_root.clone(),
                runtime_root: runtime_root.clone(),
                force_model_refresh: options.force_model_refresh.unwrap_or(false),
                quiet_model_refresh: options.quiet_model_refresh.unwrap_or(false),
            };

            if !secrets_path.exists() {
                if !*gateway_host {
                    return match sync_client_model_catalog(
                        src,
                        deployment,
                        &config_options,
                        None,
                        None,
                    ) {
                        Ok(()) => true,
                        Err(e) => {
                            eprintln!("sync: error: client model catalog sync failed: {e}");
                            false
                        }
                    };
                }
                eprintln!(
                    "sync: warning: missing local secrets {}; skipping {}",
                    secrets_path.display(),
                    dst.display()
                );
                return true;
            }

            match sync_cli_proxy_config(
                src,
                dst,
                secrets_path,
                deployment,
                &config_options,
                None,
                None,
            ) {
                Ok(()) => true,
                Err(e) => {
                    eprintln!("sync: error: CLIProxyAPI config sync failed: {e}");
                    false
                }
            }
        }
    }
}

/// Synchronizes a single file item, skipping if contents and mode match.
#[must_use]
pub fn sync_item(src: &Path, dst: &Path) -> bool {
    if !src.exists() && !is_symlink(src) {
        eprintln!("sync: error: missing source: {}", src.display());
        return true;
    }

    if files_match(src, dst) {
        return true;
    }

    if let Some(parent) = dst.parent()
        && let Err(e) = fs::create_dir_all(parent)
    {
        eprintln!(
            "sync: error: copy failed: {} -> {} ({e})",
            src.display(),
            dst.display()
        );
        return false;
    }

    let _ = rm_entry(dst);
    match fs::copy(src, dst) {
        Ok(_) => true,
        Err(e) => {
            eprintln!(
                "sync: error: copy failed: {} -> {} ({e})",
                src.display(),
                dst.display()
            );
            false
        }
    }
}

/// Synchronizes contents of `src_dir` into `dst_dir`, pruning removed unpreserved entries.
#[must_use]
pub fn sync_dir_into(src_dir: &Path, dst_dir: &Path, preserve_paths: &[String]) -> bool {
    if !src_dir.is_dir() {
        eprintln!("sync: error: missing directory: {}", src_dir.display());
        return true;
    }

    if let Err(e) = fs::create_dir_all(dst_dir) {
        eprintln!(
            "sync: error: copy failed: {} -> {} ({e})",
            src_dir.display(),
            dst_dir.display()
        );
        return false;
    }

    sync_managed_children(src_dir, dst_dir, preserve_paths)
}

/// Synchronizes tree of `src_dir` to `dst_dir`, creating parent and pruning stale entries.
#[must_use]
pub fn sync_managed_dir(src_dir: &Path, dst_dir: &Path, preserve_paths: &[String]) -> bool {
    if !src_dir.is_dir() {
        eprintln!("sync: error: missing directory: {}", src_dir.display());
        return true;
    }

    if let Some(parent) = dst_dir.parent()
        && let Err(e) = fs::create_dir_all(parent)
    {
        eprintln!(
            "sync: error: copy failed: {} -> {} ({e})",
            src_dir.display(),
            dst_dir.display()
        );
        return false;
    }

    sync_managed_children(src_dir, dst_dir, preserve_paths)
}

fn sync_managed_children(src: &Path, dst: &Path, preserve_paths: &[String]) -> bool {
    let Ok(src_entries) = fs::read_dir(src) else {
        return false;
    };

    let mut src_names = std::collections::HashSet::new();
    let mut entries = Vec::new();
    for entry in src_entries.flatten() {
        src_names.insert(entry.file_name().to_string_lossy().to_string());
        entries.push(entry);
    }

    // Prune entries in dst that no longer exist in src
    if let Ok(dst_entries) = fs::read_dir(dst) {
        for dst_entry in dst_entries.flatten() {
            let name = dst_entry.file_name().to_string_lossy().to_string();
            if !src_names.contains(&name) && !preserve_paths.contains(&name) {
                let _ = rm_entry(dst_entry.path());
            }
        }
    }

    // Sync children
    for entry in entries {
        let child_src = entry.path();
        let name = entry.file_name();
        let child_dst = dst.join(&name);

        if child_src.is_dir() {
            let child_preserve: Vec<String> = preserve_paths
                .iter()
                .filter_map(|p| {
                    let name_str = name.to_string_lossy();
                    let prefix = format!("{name_str}/");
                    p.strip_prefix(&prefix).map(ToString::to_string)
                })
                .collect();
            if !sync_dir_into(&child_src, &child_dst, &child_preserve) {
                return false;
            }
        } else if !sync_item(&child_src, &child_dst) {
            return false;
        }
    }

    true
}

fn files_match(src: &Path, dst: &Path) -> bool {
    let Ok(src_meta) = fs::symlink_metadata(src) else {
        return false;
    };
    let Ok(dst_meta) = fs::symlink_metadata(dst) else {
        return false;
    };

    if src_meta.file_type().is_symlink() || dst_meta.file_type().is_symlink() {
        return false;
    }

    if !src_meta.file_type().is_file() || !dst_meta.file_type().is_file() {
        return false;
    }

    if src_meta.len() != dst_meta.len() {
        return false;
    }

    if (src_meta.permissions().mode() & 0o777) != (dst_meta.permissions().mode() & 0o777) {
        return false;
    }

    if src_meta.len() == 0 {
        return true;
    }

    let Ok(src_bytes) = fs::read(src) else {
        return false;
    };
    let Ok(dst_bytes) = fs::read(dst) else {
        return false;
    };

    src_bytes == dst_bytes
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_copy_item_missing_source_returns_true() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        let src = temp.path().join("missing.txt");
        let dst = temp.path().join("out.txt");
        assert!(copy_item(&src, &dst));
    }

    #[test]
    fn test_copy_dir_into_merges_existing() {
        let temp = match tempdir() {
            Ok(t) => t,
            Err(e) => panic!("tempdir: {e}"),
        };
        let src = temp.path().join("src");
        let dst = temp.path().join("dst");
        if let Err(e) = fs::create_dir_all(&src) {
            panic!("mkdir: {e}");
        }
        if let Err(e) = fs::create_dir_all(&dst) {
            panic!("mkdir: {e}");
        }

        if let Err(e) = fs::write(src.join("a.txt"), "hello") {
            panic!("write: {e}");
        }
        if let Err(e) = fs::write(dst.join("existing.txt"), "keep") {
            panic!("write: {e}");
        }

        assert!(copy_dir_into(&src, &dst));
        assert!(dst.join("a.txt").exists());
        assert!(dst.join("existing.txt").exists());
    }

    #[test]
    fn test_render_secret_template() {
        let template = "api_key: ${MY_API_KEY}\nother: normal\n";
        let mut secrets = HashMap::new();
        secrets.insert("MY_API_KEY".to_string(), "secret123".to_string());

        let rendered = match crate::secret_template::render_secret_template(template, &secrets) {
            Ok(r) => r,
            Err(e) => panic!("render: {e}"),
        };
        assert_eq!(rendered, "api_key: \"secret123\"\nother: normal\n");
    }
}
