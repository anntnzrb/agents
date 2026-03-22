use std::process::Command;
use std::time::Duration;

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

fn init_git_repo(path: &Path) {
    let run = |args: &[&str]| {
        let status = Command::new("git")
            .args(args)
            .current_dir(path)
            .status()
            .expect("run git");
        assert!(status.success(), "git command failed: {args:?}");
    };

    run(&["init"]);
    run(&["config", "user.name", "Test User"]);
    run(&["config", "user.email", "test@example.com"]);
    run(&["add", "."]);
    run(&["commit", "-m", "init"]);
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
fn parse_timeout_seconds_uses_default_for_invalid_values() {
    assert_eq!(parse_timeout_seconds(None, 7), Duration::from_secs(7));
    assert_eq!(parse_timeout_seconds(Some("0"), 7), Duration::from_secs(7));
    assert_eq!(
        parse_timeout_seconds(Some("nope"), 7),
        Duration::from_secs(7)
    );
    assert_eq!(parse_timeout_seconds(Some("9"), 7), Duration::from_secs(9));
}

#[test]
fn sync_env_harness_lookup_is_typed() {
    let temp = TempDir::new().expect("tempdir");
    let sync_env = SyncEnv::from_home(temp.path().to_path_buf(), Duration::from_secs(1));

    let pi = sync_env.harness(HarnessId::Pi).expect("pi harness");
    assert_eq!(
        pi.source_root(&sync_env.tools_home),
        temp.path()
            .join(".config")
            .join("agents")
            .join("tools")
            .join("pi")
            .join("agent")
    );
    assert_eq!(
        pi.instruction_target(),
        temp.path().join(".pi").join("agent").join("AGENTS.md")
    );

    let claude = sync_env.harness(HarnessId::Claude).expect("claude harness");
    assert_eq!(
        claude.instruction_target(),
        temp.path().join(".claude").join("CLAUDE.md")
    );
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
            .join("omp")
            .join("agent")
            .join("config.yml"),
        "theme:\n  dark: graphite\n",
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
    write_file(
        &home.join(".pi").join("agent").join("auth.json"),
        "{\"token\":1}",
    );
    write_file(
        &home
            .join(".pi")
            .join("agent")
            .join("extensions")
            .join("stale.ts"),
        "stale",
    );
    write_file(
        &home
            .join(".omp")
            .join("agent")
            .join("skills")
            .join("stale.txt"),
        "stale-skill",
    );
    write_file(
        &home
            .join(".omp")
            .join("agent")
            .join("logs")
            .join("keep.txt"),
        "keep-me",
    );

    assert!(run_sync(&sync_env));
    assert!(home.join(".codex").join("AGENTS.md").is_file());
    assert!(home.join(".claude").join("CLAUDE.md").is_file());
    assert!(!home.join(".claude").join("AGENTS.md").exists());
    assert!(
        home.join(".config")
            .join("opencode")
            .join("AGENTS.md")
            .is_file()
    );
    assert!(home.join(".pi").join("agent").join("AGENTS.md").is_file());
    assert!(home.join(".omp").join("agent").join("AGENTS.md").is_file());
    assert!(home.join(".omp").join("agent").join("config.yml").is_file());
    assert!(
        home.join(".omp")
            .join("agent")
            .join("skills")
            .join("skill.txt")
            .is_file()
    );
    assert!(home.join(".mcporter").join("mcporter.json").is_file());
    assert!(home.join(".pi").join("agent").join("auth.json").is_file());
    assert!(
        !home
            .join(".pi")
            .join("agent")
            .join("extensions")
            .join("stale.ts")
            .exists()
    );
    assert!(
        !home
            .join(".omp")
            .join("agent")
            .join("skills")
            .join("stale.txt")
            .exists()
    );
    assert!(
        home.join(".omp")
            .join("agent")
            .join("logs")
            .join("keep.txt")
            .is_file()
    );
}

#[test]
fn run_sync_missing_sources_is_non_fatal() {
    let temp = TempDir::new().expect("tempdir");
    let sync_env = SyncEnv::from_home(temp.path().to_path_buf(), Duration::from_secs(1));
    assert!(run_sync(&sync_env));
}

#[test]
fn run_sync_claude_uses_claude_md() {
    let temp = TempDir::new().expect("tempdir");
    let home = temp.path().to_path_buf();
    let sync_env = SyncEnv::from_home(home.clone(), Duration::from_secs(1));

    let source_agent_file = home
        .join(".config")
        .join("agents")
        .join("assets")
        .join("AGENTS.md");
    write_file(&source_agent_file, "agent-instructions");

    assert!(run_sync(&sync_env));
    assert_eq!(
        fs::read_to_string(home.join(".claude").join("CLAUDE.md")).expect("read claude file"),
        "agent-instructions"
    );
    assert!(!home.join(".claude").join("AGENTS.md").exists());
    assert_eq!(
        fs::read_to_string(source_agent_file).expect("read source agent file"),
        "agent-instructions"
    );
}

#[test]
fn run_sync_cleans_managed_entries_for_multiple_harnesses() {
    let temp = TempDir::new().expect("tempdir");
    let home = temp.path().to_path_buf();
    let sync_env = SyncEnv::from_home(home.clone(), Duration::from_secs(1));
    let agents_root = home.join(".config").join("agents");

    write_file(
        &agents_root.join("assets").join("AGENTS.md"),
        "agent-instructions",
    );
    write_file(
        &agents_root.join("assets").join("skills").join("skill.txt"),
        "fresh-skill",
    );
    write_file(
        &agents_root.join("tools").join("codex").join("config.toml"),
        "fresh = true\n",
    );
    write_file(
        &agents_root
            .join("tools")
            .join("omp")
            .join("agent")
            .join("config.yml"),
        "theme:\n  light: graphite\n",
    );

    write_file(&home.join(".codex").join("config.toml"), "stale = true\n");
    write_file(
        &home.join(".codex").join("skills").join("stale.txt"),
        "stale-skill",
    );
    write_file(
        &home.join(".codex").join("logs").join("keep.txt"),
        "keep-me",
    );

    write_file(
        &home.join(".omp").join("agent").join("config.yml"),
        "stale-config\n",
    );
    write_file(
        &home
            .join(".omp")
            .join("agent")
            .join("skills")
            .join("stale.txt"),
        "stale-skill",
    );
    write_file(
        &home
            .join(".omp")
            .join("agent")
            .join("logs")
            .join("keep.txt"),
        "keep-me",
    );

    assert!(run_sync(&sync_env));
    assert_eq!(
        fs::read_to_string(home.join(".codex").join("config.toml")).expect("read codex config"),
        "fresh = true\n"
    );
    assert_eq!(
        fs::read_to_string(home.join(".omp").join("agent").join("config.yml"))
            .expect("read omp config"),
        "theme:\n  light: graphite\n"
    );
    assert!(
        home.join(".codex")
            .join("skills")
            .join("skill.txt")
            .is_file()
    );
    assert!(
        home.join(".omp")
            .join("agent")
            .join("skills")
            .join("skill.txt")
            .is_file()
    );
    assert!(
        !home
            .join(".codex")
            .join("skills")
            .join("stale.txt")
            .exists()
    );
    assert!(
        !home
            .join(".omp")
            .join("agent")
            .join("skills")
            .join("stale.txt")
            .exists()
    );
    assert!(home.join(".codex").join("logs").join("keep.txt").is_file());
    assert!(
        home.join(".omp")
            .join("agent")
            .join("logs")
            .join("keep.txt")
            .is_file()
    );
}

#[test]
fn run_sync_omp_cleans_managed_entries_but_preserves_local_files() {
    let temp = TempDir::new().expect("tempdir");
    let home = temp.path().to_path_buf();
    let sync_env = SyncEnv::from_home(home.clone(), Duration::from_secs(1));
    let agents_root = home.join(".config").join("agents");

    write_file(
        &agents_root.join("assets").join("AGENTS.md"),
        "agent-instructions",
    );
    write_file(
        &agents_root.join("assets").join("skills").join("skill.txt"),
        "fresh-skill",
    );
    write_file(
        &agents_root
            .join("tools")
            .join("omp")
            .join("agent")
            .join("config.yml"),
        "theme:\n  light: graphite\n",
    );

    write_file(
        &home.join(".omp").join("agent").join("config.yml"),
        "stale-config\n",
    );
    write_file(
        &home
            .join(".omp")
            .join("agent")
            .join("skills")
            .join("stale.txt"),
        "stale-skill",
    );
    write_file(
        &home
            .join(".omp")
            .join("agent")
            .join("logs")
            .join("keep.txt"),
        "keep-me",
    );

    assert!(run_sync(&sync_env));
    assert_eq!(
        fs::read_to_string(home.join(".omp").join("agent").join("config.yml"))
            .expect("read omp config"),
        "theme:\n  light: graphite\n"
    );
    assert!(
        home.join(".omp")
            .join("agent")
            .join("skills")
            .join("skill.txt")
            .is_file()
    );
    assert!(
        !home
            .join(".omp")
            .join("agent")
            .join("skills")
            .join("stale.txt")
            .exists()
    );
    assert!(
        home.join(".omp")
            .join("agent")
            .join("logs")
            .join("keep.txt")
            .is_file()
    );
}

#[test]
fn run_sync_cleans_legacy_pi_entries_without_prior_state() {
    let temp = TempDir::new().expect("tempdir");
    let home = temp.path().to_path_buf();
    let sync_env = SyncEnv::from_home(home.clone(), Duration::from_secs(1));
    let agents_root = home.join(".config").join("agents");

    write_file(
        &agents_root.join("assets").join("AGENTS.md"),
        "agent-instructions",
    );
    write_file(
        &home
            .join(".pi")
            .join("agent")
            .join("legacy")
            .join("old.txt"),
        "stale",
    );
    write_file(
        &home.join(".pi").join("agent").join("auth.json"),
        "{\"token\":1}",
    );

    assert!(run_sync(&sync_env));
    assert!(!home.join(".pi").join("agent").join("legacy").exists());
    assert!(home.join(".pi").join("agent").join("auth.json").is_file());
}

#[test]
fn run_sync_removes_entries_removed_from_ssot_after_prior_sync() {
    let temp = TempDir::new().expect("tempdir");
    let home = temp.path().to_path_buf();
    let sync_env = SyncEnv::from_home(home.clone(), Duration::from_secs(1));
    let agents_root = home.join(".config").join("agents");
    let codex_config = agents_root.join("tools").join("codex").join("config.toml");
    let skills_root = agents_root.join("assets").join("skills");

    write_file(
        &agents_root.join("assets").join("AGENTS.md"),
        "agent-instructions",
    );
    write_file(&skills_root.join("skill.txt"), "fresh-skill");
    write_file(&codex_config, "fresh = true\n");

    assert!(run_sync(&sync_env));
    assert!(home.join(".codex").join("config.toml").is_file());
    assert!(
        home.join(".codex")
            .join("skills")
            .join("skill.txt")
            .is_file()
    );
    assert!(sync_env.managed_state_home.join("codex.json").is_file());

    rm_entry(&codex_config).expect("remove codex config source");
    rm_entry(&skills_root).expect("remove skills source");
    write_file(
        &home.join(".codex").join("logs").join("keep.txt"),
        "keep-me",
    );

    assert!(run_sync(&sync_env));
    assert!(!home.join(".codex").join("config.toml").exists());
    assert!(!home.join(".codex").join("skills").exists());
    assert!(home.join(".codex").join("logs").join("keep.txt").is_file());
}

#[test]
fn run_sync_omp_does_not_bootstrap_packages() {
    let temp = TempDir::new().expect("tempdir");
    let home = temp.path().to_path_buf();
    let sync_env = SyncEnv::from_home(home.clone(), Duration::from_secs(1));
    let agents_root = home.join(".config").join("agents");

    write_file(
        &agents_root.join("assets").join("AGENTS.md"),
        "agent-instructions",
    );
    write_file(
        &agents_root
            .join("tools")
            .join("omp")
            .join("agent")
            .join("config.yml"),
        "interruptMode: immediate\n",
    );
    write_file(
        &agents_root
            .join("tools")
            .join("omp")
            .join("agent")
            .join("packages.json"),
        "this is not valid json\n",
    );

    assert!(run_sync(&sync_env));
    assert_eq!(
        fs::read_to_string(home.join(".omp").join("agent").join("packages.json"))
            .expect("read copied omp package file"),
        "this is not valid json\n"
    );
    assert!(home.join(".omp").join("agent").join("config.yml").is_file());
}

#[test]
fn read_package_manifest_dedupes_sources() {
    let temp = TempDir::new().expect("tempdir");
    let path = temp.path().join("packages.json");
    write_file(
        &path,
        r#"{
  "packages": [
    "https://github.com/tintinweb/pi-supervisor",
    "https://github.com/tintinweb/pi-supervisor",
    "https://github.com/joelhooks/pi-tools"
  ]
}"#,
    );

    let manifest = packages::read_package_manifest(&path).expect("manifest");
    assert_eq!(manifest.packages.len(), 2);
}

#[test]
fn patch_runtime_settings_preserves_other_keys() {
    let temp = TempDir::new().expect("tempdir");
    let path = temp.path().join("settings.json");
    write_file(
        &path,
        r#"{
  "theme": "dark",
  "defaultModel": "gpt-5.4"
}
"#,
    );

    packages::patch_runtime_settings(&path, &[temp.path().join("pkg")]).expect("patch settings");

    let settings = fs::read_to_string(&path).expect("read settings");
    assert!(settings.contains("\"theme\": \"dark\""));
    assert!(settings.contains("\"packages\""));
    assert!(settings.contains(&*temp.path().join("pkg").to_string_lossy()));
}

#[test]
fn package_cache_dir_is_stable() {
    let root = Path::new("/tmp/cache-root");
    let left = packages::package_cache_dir(root, "https://github.com/tintinweb/pi-supervisor");
    let right = packages::package_cache_dir(root, "https://github.com/tintinweb/pi-supervisor");
    assert_eq!(left, right);
}

#[test]
fn github_clone_command_prefers_gh_when_available() {
    let temp = TempDir::new().expect("tempdir");
    let target = temp.path().join("out");
    let command =
        packages::command_for_tests("https://github.com/tintinweb/pi-supervisor", &target);
    assert_eq!(command[0], "gh");
    assert_eq!(
        packages::github_slug_for_tests("https://github.com/tintinweb/pi-supervisor"),
        Some("tintinweb/pi-supervisor".to_string())
    );
}

#[test]
fn github_clone_falls_back_to_git_after_gh_failure() {
    let temp = TempDir::new().expect("tempdir");
    let target = temp.path().join("out");
    let (success, attempts) = packages::clone_attempts_for_tests(
        "https://github.com/tintinweb/pi-supervisor",
        &target,
        true,
        &[false, true],
    );

    assert!(success);
    assert_eq!(attempts.len(), 2);
    assert_eq!(attempts[0][0], "gh");
    assert_eq!(attempts[1][0], "git");
    assert_eq!(attempts[1][3], "https://github.com/tintinweb/pi-supervisor");
}

#[test]
fn validate_package_dir_accepts_manifest_and_conventional_dirs() {
    let temp = TempDir::new().expect("tempdir");
    let manifest_pkg = temp.path().join("manifest-pkg");
    write_file(
        &manifest_pkg.join("package.json"),
        r#"{
  "pi": {
    "extensions": ["./src/index.ts"]
  }
}"#,
    );
    write_file(
        &manifest_pkg.join("src").join("index.ts"),
        "export default {}\n",
    );
    assert!(packages::validate_package_for_tests(&manifest_pkg).expect("validate manifest"));

    let conventional_pkg = temp.path().join("conventional-pkg");
    write_file(
        &conventional_pkg.join("extensions").join("index.ts"),
        "export default {}\n",
    );
    assert!(
        packages::validate_package_for_tests(&conventional_pkg).expect("validate conventional")
    );
}

#[test]
fn validate_package_dir_detects_missing_import_packages() {
    let temp = TempDir::new().expect("tempdir");
    let pkg = temp.path().join("import-pkg");
    write_file(
        &pkg.join("package.json"),
        r#"{
  "pi": {
    "extensions": ["./index.ts"]
  }
}"#,
    );
    write_file(
        &pkg.join("index.ts"),
        "import { Text } from \"@mariozechner/pi-tui\";\nexport default Text;\n",
    );
    assert!(!packages::validate_package_for_tests(&pkg).expect("missing import invalid"));

    write_file(
        &pkg.join("node_modules")
            .join("@mariozechner")
            .join("pi-tui")
            .join("package.json"),
        "{}\n",
    );
    assert!(packages::validate_package_for_tests(&pkg).expect("resolved import valid"));
}

#[cfg(unix)]
#[test]
fn run_sync_bootstraps_packages_and_patches_runtime_settings() {
    let temp = TempDir::new().expect("tempdir");
    let home = temp.path().to_path_buf();
    let sync_env = SyncEnv::from_home(home.clone(), Duration::from_secs(2));

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
            .join("tools")
            .join("pi")
            .join("agent")
            .join("settings.json"),
        "{}\n",
    );
    let repos = temp.path().join("repos");
    fs::create_dir_all(&repos).expect("create repos");

    let source_repo = repos.join("source-pkg");
    write_file(
        &source_repo.join("package.json"),
        r#"{
  "pi": {
    "extensions": ["./src/index.ts"]
  }
}
"#,
    );
    write_file(
        &source_repo.join("src").join("index.ts"),
        "export default {}\n",
    );
    init_git_repo(&source_repo);

    let build_repo = repos.join("build-pkg");
    write_file(
        &build_repo.join("package.json"),
        r#"{
  "scripts": {
    "build": "mkdir -p dist && printf 'export default {}\\n' > dist/index.js"
  },
  "pi": {
    "extensions": ["./dist/index.js"]
  }
}
"#,
    );
    init_git_repo(&build_repo);

    write_file(
        &home
            .join(".config")
            .join("agents")
            .join("tools")
            .join("pi")
            .join("agent")
            .join("packages.json"),
        &format!(
            "{{\n  \"packages\": [\n    \"{}\",\n    \"{}\"\n  ]\n}}\n",
            source_repo.display(),
            build_repo.display()
        ),
    );

    let success = run_sync(&sync_env);

    assert!(success);
    let settings = fs::read_to_string(home.join(".pi").join("agent").join("settings.json"))
        .expect("read runtime settings");
    assert!(settings.contains("source-pkg"));
    assert!(settings.contains("build-pkg"));
    assert!(
        home.join(".local")
            .join("share")
            .join("agents")
            .join("pi-packages")
            .read_dir()
            .expect("cache dir")
            .next()
            .is_some()
    );
}
