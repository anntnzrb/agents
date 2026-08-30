use std::path::{Path, PathBuf};

/// Specification for a static managed tool launched via npm wrapper.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ToolLauncherSpec {
    pub id: &'static str,
    pub package: &'static str,
    pub bin: &'static str,
    pub dist_tag: Option<&'static str>,
    pub smoke_check: Option<&'static str>,
    pub default_args: &'static [&'static str],
    pub config_home_segments: &'static [&'static str],
}

/// npm tools that sync launches like harnesses: a generated wrapper under
/// `~/.local/bin`, a versioned package cache, and a best-effort sync before
/// launch.
///
/// Tools have no harness home, instruction file, or skills.
pub const TOOL_LAUNCHERS: &[ToolLauncherSpec] = &[
    ToolLauncherSpec {
        id: "mcporter",
        package: "mcporter",
        bin: "mcporter",
        dist_tag: None,
        smoke_check: None,
        default_args: &[],
        config_home_segments: &[".mcporter", "mcporter.json"],
    },
    ToolLauncherSpec {
        id: "summarize",
        package: "@steipete/summarize",
        bin: "summarize",
        dist_tag: None,
        smoke_check: None,
        default_args: &[
            "--force-summary",
            "--timestamps",
            "--format",
            "md",
            "--retries",
            "2",
            "--metrics",
            "detailed",
        ],
        config_home_segments: &[],
    },
];

/// Returns all statically registered tool launcher specifications.
#[must_use]
pub const fn tool_launchers() -> &'static [ToolLauncherSpec] {
    TOOL_LAUNCHERS
}

/// Finds a tool launcher specification by its identifier.
#[must_use]
pub fn tool_launcher(id: &str) -> Option<&'static ToolLauncherSpec> {
    TOOL_LAUNCHERS.iter().find(|tool| tool.id == id)
}

/// Resolves default CLI arguments for a tool launcher given the user's home directory.
#[must_use]
pub fn tool_launcher_default_args(home: &Path, tool: &ToolLauncherSpec) -> Vec<String> {
    let mut args = Vec::new();
    if !tool.config_home_segments.is_empty() {
        let mut config_path = PathBuf::from(home);
        for segment in tool.config_home_segments {
            config_path.push(segment);
        }
        args.push(String::from("--config"));
        args.push(config_path.to_string_lossy().into_owned());
    }
    for arg in tool.default_args {
        args.push((*arg).to_string());
    }
    args
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic
)]
mod tests {
    use super::*;

    #[test]
    fn test_lookup_static_tool_launchers() {
        let mcporter = tool_launcher("mcporter");
        assert!(mcporter.is_some());
        let mcporter = mcporter.unwrap();
        assert_eq!(mcporter.package, "mcporter");
        assert_eq!(mcporter.bin, "mcporter");

        let summarize = tool_launcher("summarize");
        assert!(summarize.is_some());
        let summarize = summarize.unwrap();
        assert_eq!(summarize.package, "@steipete/summarize");
        assert_eq!(summarize.bin, "summarize");

        assert!(tool_launcher("nonexistent").is_none());
    }

    #[test]
    fn test_tool_launcher_default_args_mcporter() {
        let home = Path::new("/custom/home");
        let tool = tool_launcher("mcporter").unwrap();
        let args = tool_launcher_default_args(home, tool);
        assert_eq!(
            args,
            vec![
                String::from("--config"),
                String::from("/custom/home/.mcporter/mcporter.json")
            ]
        );
    }

    #[test]
    fn test_tool_launcher_default_args_summarize() {
        let home = Path::new("/custom/home");
        let tool = tool_launcher("summarize").unwrap();
        let args = tool_launcher_default_args(home, tool);
        assert_eq!(
            args,
            vec![
                String::from("--force-summary"),
                String::from("--timestamps"),
                String::from("--format"),
                String::from("md"),
                String::from("--retries"),
                String::from("2"),
                String::from("--metrics"),
                String::from("detailed"),
            ]
        );
    }
}
