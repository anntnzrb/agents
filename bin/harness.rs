use std::path::{Path, PathBuf};
use std::time::Duration;

pub(super) const SOURCE_AGENT_FILE: &str = "AGENTS.md";
const CLAUDE_AGENT_FILE: &str = "CLAUDE.md";
const INSTALL_TIMEOUT_SECONDS: u64 = 120;
pub(super) const MANAGED_STATE_SUBDIR: &str = ".local/share/agents/sync-managed";

pub(super) type AssetRename = (&'static str, &'static str);

const PI_COMPAT_MANAGED_ENTRIES: &[&str] = &["legacy"];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum HarnessId {
    Claude,
    Codex,
    Opencode,
    Pi,
    Omp,
}

#[derive(Clone, Debug)]
pub(super) struct Harness {
    pub(super) id: HarnessId,
    pub(super) source_name: &'static str,
    home: PathBuf,
    instruction_file: &'static str,
    asset_renames: &'static [AssetRename],
    runtime_subdir: Option<&'static str>,
    pub(super) compat_managed_entries: &'static [&'static str],
}

impl Harness {
    fn new(id: HarnessId, source_name: &'static str, home: PathBuf) -> Self {
        Self {
            id,
            source_name,
            home,
            instruction_file: SOURCE_AGENT_FILE,
            asset_renames: &[],
            runtime_subdir: None,
            compat_managed_entries: &[],
        }
    }

    fn with_instruction_file(mut self, instruction_file: &'static str) -> Self {
        self.instruction_file = instruction_file;
        self
    }

    fn with_runtime_subdir(mut self, runtime_subdir: &'static str) -> Self {
        self.runtime_subdir = Some(runtime_subdir);
        self
    }

    fn with_compat_managed_entries(
        mut self,
        compat_managed_entries: &'static [&'static str],
    ) -> Self {
        self.compat_managed_entries = compat_managed_entries;
        self
    }

    pub(super) fn root(&self) -> PathBuf {
        self.runtime_subdir
            .map_or_else(|| self.home.clone(), |subdir| self.home.join(subdir))
    }

    pub(super) fn source_root(&self, tools_home: &Path) -> PathBuf {
        self.runtime_subdir.map_or_else(
            || tools_home.join(self.source_name),
            |subdir| tools_home.join(self.source_name).join(subdir),
        )
    }

    pub(super) fn instruction_file_name(&self) -> &'static str {
        self.instruction_file
    }

    pub(super) fn instruction_target(&self) -> PathBuf {
        self.root().join(self.instruction_file)
    }

    pub(super) fn rename_asset(&self, asset_name: &str) -> String {
        self.asset_renames
            .iter()
            .find_map(|(src, dst)| (*src == asset_name).then_some((*dst).to_string()))
            .unwrap_or_else(|| asset_name.to_string())
    }

    pub(super) fn managed_state_path(&self, managed_state_home: &Path) -> PathBuf {
        managed_state_home.join(format!("{}.json", self.source_name))
    }
}

#[derive(Clone, Debug)]
pub(super) struct SyncEnv {
    pub(super) home: PathBuf,
    pub(super) assets_home: PathBuf,
    pub(super) tools_home: PathBuf,
    pub(super) mcporter_home: PathBuf,
    pub(super) managed_state_home: PathBuf,
    pub(super) install_timeout: Duration,
    pub(super) harnesses: Vec<Harness>,
}

impl SyncEnv {
    pub(super) fn from_system() -> Result<Self, String> {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .ok_or_else(|| "missing HOME".to_string())?;
        Ok(Self::from_home(
            home,
            Duration::from_secs(INSTALL_TIMEOUT_SECONDS),
        ))
    }

    pub(super) fn from_home(home: PathBuf, install_timeout: Duration) -> Self {
        let agents_home = home.join(".config").join("agents");
        Self {
            home: home.clone(),
            assets_home: agents_home.join("assets"),
            tools_home: agents_home.join("tools"),
            mcporter_home: home.join(".mcporter"),
            managed_state_home: home.join(MANAGED_STATE_SUBDIR),
            install_timeout,
            harnesses: vec![
                Harness::new(HarnessId::Claude, "claude", home.join(".claude"))
                    .with_instruction_file(CLAUDE_AGENT_FILE),
                Harness::new(HarnessId::Codex, "codex", home.join(".codex")),
                Harness::new(
                    HarnessId::Opencode,
                    "opencode",
                    home.join(".config").join("opencode"),
                ),
                Harness::new(HarnessId::Pi, "pi", home.join(".pi"))
                    .with_runtime_subdir("agent")
                    .with_compat_managed_entries(PI_COMPAT_MANAGED_ENTRIES),
                Harness::new(HarnessId::Omp, "omp", home.join(".omp")).with_runtime_subdir("agent"),
            ],
        }
    }

    pub(super) fn harness(&self, id: HarnessId) -> Option<&Harness> {
        self.harnesses.iter().find(|harness| harness.id == id)
    }
}
