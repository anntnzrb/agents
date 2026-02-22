use super::*;
use tempfile::TempDir;

fn write_file(path: &Path, content: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("create parent dirs");
    }
    fs::write(path, content).expect("write file");
}

#[cfg(unix)]
fn write_executable(path: &Path, script: &str) {
    use std::os::unix::fs::PermissionsExt;

    write_file(path, script);
    let mut perms = fs::metadata(path).expect("metadata").permissions();
    perms.set_mode(0o755);
    fs::set_permissions(path, perms).expect("set executable");
}

#[test]
fn copy_item_missing_source_returns_true() {
    let temp = TempDir::new().expect("tempdir");
    let src = temp.path().join("missing.txt");
    let dst = temp.path().join("out.txt");
    assert!(copy_item(&src, &dst));
    assert!(!dst.exists());
}

#[test]
fn copy_dir_into_merges_existing_destination() {
    let temp = TempDir::new().expect("tempdir");
    let src = temp.path().join("src");
    let dst = temp.path().join("dst");
    write_file(&src.join("x.txt"), "x");
    write_file(&dst.join("keep.txt"), "k");

    assert!(copy_dir_into(&src, &dst));
    assert!(dst.join("keep.txt").is_file());
    assert!(dst.join("x.txt").is_file());
}

#[test]
fn iter_extension_packages_skips_node_modules() {
    let temp = TempDir::new().expect("tempdir");
    let root = temp.path();
    write_file(&root.join("a").join("package.json"), "{}");
    write_file(&root.join("a").join("nested").join("package.json"), "{}");
    write_file(
        &root
            .join("a")
            .join("node_modules")
            .join("skip")
            .join("package.json"),
        "{}",
    );

    let mut packages = iter_extension_packages(root);
    packages.sort();
    assert_eq!(packages.len(), 2);
}

#[cfg(unix)]
#[test]
fn run_install_handles_success_failure_and_timeout() {
    let temp = TempDir::new().expect("tempdir");
    let bin = temp.path().join("bin");
    fs::create_dir_all(&bin).expect("create bin");

    let ok = bin.join("ok");
    write_executable(&ok, "#!/bin/sh\nexit 0\n");
    assert!(run_install(
        &[ok.to_string_lossy().to_string()],
        temp.path(),
        Duration::from_secs(1)
    ));

    let fail = bin.join("fail");
    write_executable(&fail, "#!/bin/sh\necho bad >&2\nexit 3\n");
    assert!(!run_install(
        &[fail.to_string_lossy().to_string()],
        temp.path(),
        Duration::from_secs(1)
    ));

    let sleepy = bin.join("sleepy");
    write_executable(&sleepy, "#!/bin/sh\nsleep 2\n");
    assert!(!run_install(
        &[sleepy.to_string_lossy().to_string()],
        temp.path(),
        Duration::from_millis(100)
    ));
}

#[test]
fn run_sync_happy_path() {
    let temp = TempDir::new().expect("tempdir");
    let home = temp.path().to_path_buf();
    let sync_env = SyncEnv::from_home(home.clone(), Duration::from_secs(1));

    write_file(
        &home
            .join(".config")
            .join("agents")
            .join("assets")
            .join("AGENTS.md"),
        "agent-instructions",
    );
    write_file(
        &home
            .join(".config")
            .join("agents")
            .join("assets")
            .join("mcporter.jsonc"),
        "{\"x\":1}",
    );
    write_file(
        &home
            .join(".config")
            .join("agents")
            .join("assets")
            .join("skills")
            .join("skill.txt"),
        "skill-content",
    );
    write_file(
        &home
            .join(".config")
            .join("agents")
            .join("tools")
            .join("codex")
            .join("config.toml"),
        "codex = true",
    );
    write_file(
        &home
            .join(".config")
            .join("agents")
            .join("tools")
            .join("pi")
            .join("agent")
            .join("extensions")
            .join("answer")
            .join("package.json"),
        "{}",
    );
    fs::create_dir_all(
        home.join(".config")
            .join("agents")
            .join("tools")
            .join("pi")
            .join("agent")
            .join("extensions")
            .join("answer")
            .join("node_modules"),
    )
    .expect("create node_modules");

    assert!(run_sync(&sync_env));
    assert!(home.join(".codex").join("AGENTS.md").is_file());
    assert!(home.join(".claude").join("CLAUDE.md").is_file());
    assert!(home.join(".config").join("opencode").join("AGENTS.md").is_file());
    assert!(home.join(".pi").join("agent").join("AGENTS.md").is_file());
    assert!(home.join(".mcporter").join("mcporter.json").is_file());
}

#[test]
fn run_sync_missing_sources_is_non_fatal() {
    let temp = TempDir::new().expect("tempdir");
    let sync_env = SyncEnv::from_home(temp.path().to_path_buf(), Duration::from_secs(1));
    assert!(run_sync(&sync_env));
}
