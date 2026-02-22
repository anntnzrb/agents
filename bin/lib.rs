use std::ffi::OsStr;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};
const DEFAULT_AGENT_FILE: &str = "AGENTS.md";
const INSTALL_TIMEOUT_SECONDS: u64 = 120;

#[derive(Clone, Debug)]
struct ToolConfig {
    name: &'static str,
    home: PathBuf,
    agent_file: &'static str,
    asset_renames: Vec<(&'static str, &'static str)>,
    tool_subdir: Option<&'static str>,
}
impl ToolConfig {
    fn root(&self) -> PathBuf {
        self.tool_subdir
            .map_or_else(|| self.home.clone(), |subdir| self.home.join(subdir))
    }

    fn rename_asset(&self, asset_name: &str) -> String {
        self.asset_renames
            .iter()
            .find_map(|(src, dst)| (*src == asset_name).then_some((*dst).to_string()))
            .unwrap_or_else(|| asset_name.to_string())
    }
}
#[derive(Clone, Copy, Debug)]
enum JobKind {
    File,
    Dir,
}

#[derive(Clone, Debug)]
struct Job {
    src: PathBuf,
    dst: PathBuf,
    kind: JobKind,
}
#[derive(Clone, Debug)]
struct SyncEnv {
    assets_home: PathBuf,
    tools_home: PathBuf,
    mcporter_home: PathBuf,
    install_timeout: Duration,
    tools: Vec<ToolConfig>,
}
impl SyncEnv {
    fn from_system() -> Result<Self, String> {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .ok_or_else(|| "missing HOME".to_string())?;
        Ok(Self::from_home(home, Duration::from_secs(INSTALL_TIMEOUT_SECONDS)))
    }

    fn from_home(home: PathBuf, install_timeout: Duration) -> Self {
        let agents_home = home.join(".config").join("agents");
        Self {
            assets_home: agents_home.join("assets"),
            tools_home: agents_home.join("tools"),
            mcporter_home: home.join(".mcporter"),
            install_timeout,
            tools: vec![
                ToolConfig {
                    name: "claude",
                    home: home.join(".claude"),
                    agent_file: "CLAUDE.md",
                    asset_renames: Vec::new(),
                    tool_subdir: None,
                },
                ToolConfig {
                    name: "codex",
                    home: home.join(".codex"),
                    agent_file: DEFAULT_AGENT_FILE,
                    asset_renames: Vec::new(),
                    tool_subdir: None,
                },
                ToolConfig {
                    name: "opencode",
                    home: home.join(".config").join("opencode"),
                    agent_file: DEFAULT_AGENT_FILE,
                    asset_renames: Vec::new(),
                    tool_subdir: None,
                },
                ToolConfig {
                    name: "pi",
                    home: home.join(".pi"),
                    agent_file: DEFAULT_AGENT_FILE,
                    asset_renames: Vec::new(),
                    tool_subdir: Some("agent"),
                },
            ],
        }
    }
}
fn err(message: &str) {
    eprintln!("sync: {message}");
}
fn panic_message(payload: Box<dyn std::any::Any + Send>) -> String {
    if let Some(text) = payload.downcast_ref::<&str>() {
        return (*text).to_string();
    }
    if let Some(text) = payload.downcast_ref::<String>() {
        return text.clone();
    }
    "panic".to_string()
}
fn is_symlink(path: &Path) -> bool {
    fs::symlink_metadata(path)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false)
}
fn rm_entry(path: &Path) -> std::io::Result<()> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error),
    };

    if metadata.file_type().is_symlink() {
        return fs::remove_file(path).or_else(ignore_not_found);
    }
    if metadata.is_dir() {
        return fs::remove_dir_all(path);
    }
    fs::remove_file(path).or_else(ignore_not_found)
}
fn ignore_not_found(error: std::io::Error) -> std::io::Result<()> {
    if error.kind() == std::io::ErrorKind::NotFound {
        Ok(())
    } else {
        Err(error)
    }
}
fn copy_tree(src: &Path, dst: &Path) -> std::io::Result<()> {
    let metadata = fs::metadata(src)?;
    if metadata.is_dir() {
        fs::create_dir_all(dst)?;
        for entry_result in fs::read_dir(src)? {
            let entry = entry_result?;
            copy_tree(&entry.path(), &dst.join(entry.file_name()))?;
        }
        return Ok(());
    }

    if let Some(parent) = dst.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::copy(src, dst)?;
    Ok(())
}
fn copy_item(src: &Path, dst: &Path) -> bool {
    if !src.exists() && !is_symlink(src) {
        err(&format!("missing source: {}", src.display()));
        return true;
    }

    if let Some(parent) = dst.parent() {
        fs::create_dir_all(parent).unwrap_or_else(|error| panic!("{error}"));
    }
    rm_entry(dst).unwrap_or_else(|error| panic!("{error}"));

    let result = if src.is_dir() {
        copy_tree(src, dst)
    } else {
        fs::copy(src, dst).map(|_| ())
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

fn copy_dir_into(src_dir: &Path, dst_dir: &Path) -> bool {
    if !src_dir.is_dir() {
        err(&format!("missing directory: {}", src_dir.display()));
        return true;
    }

    fs::create_dir_all(dst_dir).unwrap_or_else(|error| panic!("{error}"));
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

fn run_job(job: &Job) -> bool {
    let (name, handler): (&str, fn(&Path, &Path) -> bool) = match job.kind {
        JobKind::Dir => ("copy_dir_into", copy_dir_into),
        JobKind::File => ("copy_item", copy_item),
    };

    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| handler(&job.src, &job.dst))) {
        Ok(result) => result,
        Err(payload) => {
            err(&format!("unexpected error in {name}: {}", panic_message(payload)));
            false
        }
    }
}

fn tool_dirs(sync_env: &SyncEnv) -> Vec<Job> {
    sync_env
        .tools
        .iter()
        .map(|tool| Job {
            src: tool.tool_subdir.map_or_else(
                || sync_env.tools_home.join(tool.name),
                |subdir| sync_env.tools_home.join(tool.name).join(subdir),
            ),
            dst: tool.root(),
            kind: JobKind::Dir,
        })
        .collect()
}

fn asset_copies(sync_env: &SyncEnv) -> Vec<Job> {
    if !sync_env.assets_home.is_dir() {
        return Vec::new();
    }

    let mut jobs = Vec::new();
    for entry_result in fs::read_dir(&sync_env.assets_home).unwrap_or_else(|error| panic!("{error}")) {
        let asset_path = entry_result.unwrap_or_else(|error| panic!("{error}")).path();
        if !asset_path.is_dir() {
            continue;
        }
        let asset_name = asset_path
            .file_name()
            .and_then(OsStr::to_str)
            .unwrap_or_else(|| panic!("invalid UTF-8 path: {}", asset_path.display()));
        for tool in &sync_env.tools {
            jobs.push(Job {
                src: asset_path.clone(),
                dst: tool.root().join(tool.rename_asset(asset_name)),
                kind: JobKind::Dir,
            });
        }
    }
    jobs
}

fn agent_files(sync_env: &SyncEnv) -> Vec<Job> {
    sync_env
        .tools
        .iter()
        .map(|tool| Job {
            src: sync_env.assets_home.join(DEFAULT_AGENT_FILE),
            dst: tool.root().join(tool.agent_file),
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

fn iter_jobs(sync_env: &SyncEnv) -> Vec<Job> {
    let builders: [fn(&SyncEnv) -> Vec<Job>; 4] = [tool_dirs, asset_copies, agent_files, config_files];
    let mut jobs = Vec::new();
    for builder in builders {
        jobs.extend(builder(sync_env));
    }
    jobs
}

fn run_jobs(jobs: &[Job]) -> bool {
    jobs.iter().all(run_job)
}

fn iter_extension_packages(root: &Path) -> Vec<PathBuf> {
    fn walk(current: &Path, packages: &mut Vec<PathBuf>) {
        if !current.is_dir() {
            return;
        }

        if current.join("package.json").is_file() {
            packages.push(current.to_path_buf());
        }

        for child_result in fs::read_dir(current).unwrap_or_else(|error| panic!("{error}")) {
            let child = child_result.unwrap_or_else(|error| panic!("{error}")).path();
            if child.is_dir() && !is_symlink(&child) && child.file_name() != Some(OsStr::new("node_modules")) {
                walk(&child, packages);
            }
        }
    }

    let mut packages = Vec::new();
    walk(root, &mut packages);
    packages
}

fn needs_node_install(package_dir: &Path) -> bool {
    package_dir.join("package.json").is_file() && !package_dir.join("node_modules").exists()
}

fn command_exists(command: &str) -> bool {
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

fn run_install(command: &[String], package_dir: &Path, timeout: Duration) -> bool {
    let mut child = match Command::new(&command[0])
        .args(&command[1..])
        .current_dir(package_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            err(&format!("missing installer: {}", command[0]));
            return false;
        }
        Err(error) => panic!("{error}"),
    };

    let mut stdout = child
        .stdout
        .take()
        .unwrap_or_else(|| panic!("missing stdout pipe for {}", command[0]));
    let mut stderr = child
        .stderr
        .take()
        .unwrap_or_else(|| panic!("missing stderr pipe for {}", command[0]));

    let stdout_handle = thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = stdout.read_to_end(&mut bytes);
        bytes
    });
    let stderr_handle = thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = stderr.read_to_end(&mut bytes);
        bytes
    });

    let start = Instant::now();
    loop {
        if start.elapsed() > timeout {
            let _ = child.kill();
            let _ = child.wait();
            let _ = stdout_handle.join();
            let _ = stderr_handle.join();
            err(&format!(
                "deps install timed out in {}: {}",
                package_dir.display(),
                command[0]
            ));
            return false;
        }

        match child.try_wait() {
            Ok(Some(status)) => {
                let stdout_text = String::from_utf8_lossy(&stdout_handle.join().unwrap_or_default()).into_owned();
                let stderr_text = String::from_utf8_lossy(&stderr_handle.join().unwrap_or_default()).into_owned();

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
                return false;
            }
            Ok(None) => thread::sleep(Duration::from_millis(50)),
            Err(error) => panic!("{error}"),
        }
    }
}

fn install_extension_deps(root: &Path, timeout: Duration) -> bool {
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
    results.into_iter().all(std::convert::identity)
}

fn run_sync(sync_env: &SyncEnv) -> bool {
    let base_success = run_jobs(&iter_jobs(sync_env));
    let install_success = if base_success {
        sync_env
            .tools
            .iter()
            .find(|tool| tool.name == "pi")
            .map(|tool| install_extension_deps(&tool.root().join("extensions"), sync_env.install_timeout))
            .unwrap_or(true)
    } else {
        true
    };

    base_success && install_success
}

pub(crate) fn main() -> std::process::ExitCode {
    let sync_env = match SyncEnv::from_system() {
        Ok(sync_env) => sync_env,
        Err(message) => {
            err(&message);
            return std::process::ExitCode::from(1);
        }
    };

    std::process::ExitCode::from(if run_sync(&sync_env) { 0 } else { 1 })
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
