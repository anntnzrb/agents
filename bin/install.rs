use std::ffi::OsStr;
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

use wait_timeout::ChildExt;
use walkdir::WalkDir;

use super::{err, packages};

pub(super) fn iter_extension_packages(root: &Path) -> Vec<PathBuf> {
    if !root.is_dir() {
        return Vec::new();
    }

    let walker = WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_entry(|entry| {
            !(entry.file_type().is_dir() && entry.file_name() == OsStr::new("node_modules"))
        });

    let mut packages = Vec::new();
    for entry_result in walker {
        let entry = entry_result.unwrap_or_else(|error| panic!("{error}"));
        if entry.file_type().is_symlink() {
            continue;
        }
        if entry.file_type().is_file() && entry.file_name() == OsStr::new("package.json") {
            if let Some(parent) = entry.path().parent() {
                packages.push(parent.to_path_buf());
            }
        }
    }
    packages
}

pub(super) fn command_exists(command: &str) -> bool {
    let Some(path_var) = std::env::var_os("PATH") else {
        return false;
    };
    std::env::split_paths(&path_var).any(|dir| {
        let candidate = dir.join(command);
        if !candidate.is_file() {
            return false;
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::metadata(&candidate)
                .map(|metadata| metadata.permissions().mode() & 0o111 != 0)
                .unwrap_or(false)
        }
        #[cfg(not(unix))]
        {
            true
        }
    })
}

pub(super) fn read_pipe<R: Read + Send + 'static>(mut reader: R) -> Vec<u8> {
    let mut bytes = Vec::new();
    let _ = reader.read_to_end(&mut bytes);
    bytes
}

pub(super) fn run_install(command: &[String], package_dir: &Path, timeout: Duration) -> bool {
    let mut child = match Command::new(&command[0])
        .args(&command[1..])
        .current_dir(package_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            err(&format!("missing installer: {}", command[0]));
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
                "deps install failed in {}: {} ({detail})",
                package_dir.display(),
                command[0]
            ));
            false
        }
        Ok(None) => {
            let _ = child.kill();
            let _ = child.wait();
            let _ = stdout_handle.join();
            let _ = stderr_handle.join();
            err(&format!(
                "deps install timed out in {}: {}",
                package_dir.display(),
                command[0]
            ));
            false
        }
        Err(error) => panic!("{error}"),
    }
}

pub(super) fn install_extension_deps(root: &Path, timeout: Duration) -> bool {
    let mut results = Vec::new();
    for package_dir in iter_extension_packages(root) {
        if !needs_node_install(&package_dir) {
            results.push(true);
            continue;
        }

        let Some(command) = choose_installer(&package_dir) else {
            err(&format!(
                "no package manager available for {}",
                package_dir.display()
            ));
            results.push(false);
            continue;
        };

        results.push(run_install(&command, &package_dir, timeout));
    }
    results.push(packages::install_inferred_import_packages(root, timeout));
    results.into_iter().all(std::convert::identity)
}

fn needs_node_install(package_dir: &Path) -> bool {
    package_dir.join("package.json").is_file() && !package_dir.join("node_modules").exists()
}

fn choose_installer(package_dir: &Path) -> Option<Vec<String>> {
    if package_dir.join("bun.lockb").exists() && command_exists("bun") {
        return Some(vec!["bun".to_string(), "install".to_string()]);
    }
    if command_exists("npm") {
        return Some(vec!["npm".to_string(), "install".to_string()]);
    }
    if command_exists("bun") {
        return Some(vec!["bun".to_string(), "install".to_string()]);
    }
    None
}
