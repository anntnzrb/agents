use std::process::ExitCode;

use app_core::{DEFAULT_SYNC_TIMEOUT_SECONDS, PRODUCT_NAME, SyncOptions, launch_main, sync_main};
use clap::{Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(
    name = PRODUCT_NAME,
    version,
    about = "Agentium synchronization engine",
    propagate_version = true
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Option<Commands>,

    /// Force refresh of model catalog caches
    #[arg(long, global = true)]
    pub refresh_models: bool,
}

#[derive(Debug, Subcommand, PartialEq, Eq)]
pub enum Commands {
    /// Synchronize agent harnesses, tools, and configurations
    Sync {
        /// Force refresh of model catalog caches
        #[arg(long)]
        refresh_models: bool,
    },
    /// Launch a configured harness or tool
    Launch {
        /// Target harness or tool name
        target: String,

        /// Forwarded arguments passed to the launched executable
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<String>,
    },
}

#[tokio::main]
async fn main() -> ExitCode {
    let raw_args: Vec<String> = std::env::args().collect();

    // Fast-path trampoline: if first arg after binary is "launch"
    if raw_args.get(1).map(String::as_str) == Some("launch") {
        let target = match raw_args.get(2) {
            Some(t) if !t.starts_with('-') => t,
            _ => {
                eprintln!("sync: usage: launch NAME -- [ARGS...]");
                return ExitCode::from(2);
            }
        };

        let sub_args = match raw_args.get(3..) {
            Some(slice) => slice,
            None => &[],
        };

        let forwarded_args: Vec<String> = if sub_args.first().map(String::as_str) == Some("--") {
            sub_args.get(1..).unwrap_or(&[]).to_vec()
        } else {
            sub_args.to_vec()
        };

        let code = launch_main(target, &forwarded_args).await;
        return ExitCode::from(u8::try_from(code & 0xFF).unwrap_or(255));
    }

    let cli = Cli::parse();

    match cli.command {
        Some(Commands::Launch { target, args }) => {
            let code = launch_main(&target, &args).await;
            ExitCode::from(u8::try_from(code & 0xFF).unwrap_or(255))
        }
        Some(Commands::Sync { refresh_models }) => {
            start_watchdog(DEFAULT_SYNC_TIMEOUT_SECONDS);
            let options = SyncOptions {
                warn_managed_services: true,
                force_model_refresh: refresh_models || cli.refresh_models,
            };
            let code = sync_main(&options).await;
            ExitCode::from(u8::try_from(code & 0xFF).unwrap_or(255))
        }
        None => {
            start_watchdog(DEFAULT_SYNC_TIMEOUT_SECONDS);
            let options = SyncOptions {
                warn_managed_services: true,
                force_model_refresh: cli.refresh_models,
            };
            let code = sync_main(&options).await;
            ExitCode::from(u8::try_from(code & 0xFF).unwrap_or(255))
        }
    }
}

fn start_watchdog(timeout_seconds: u64) {
    tokio::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_secs(timeout_seconds)).await;
        eprintln!("sync: timed out after {timeout_seconds}s");
        #[allow(clippy::exit)]
        std::process::exit(124);
    });
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
    use clap::CommandFactory;

    #[test]
    fn test_cli_metadata() {
        let cmd = Cli::command();
        assert_eq!(cmd.get_name(), PRODUCT_NAME);
    }

    #[test]
    fn test_cli_parse_sync_subcommand() {
        let cli = Cli::try_parse_from(["agentium", "sync", "--refresh-models"]).unwrap();
        assert_eq!(
            cli.command,
            Some(Commands::Sync {
                refresh_models: true
            })
        );
    }

    #[test]
    fn test_cli_parse_launch_subcommand() {
        let cli =
            Cli::try_parse_from(["agentium", "launch", "codex", "--", "--verbose", "file.ts"])
                .unwrap();
        assert_eq!(
            cli.command,
            Some(Commands::Launch {
                target: "codex".to_string(),
                args: vec!["--verbose".to_string(), "file.ts".to_string()],
            })
        );
    }

    #[test]
    fn test_cli_default_is_none_subcommand() {
        let cli = Cli::try_parse_from(["agentium"]).unwrap();
        assert!(cli.command.is_none());
        assert!(!cli.refresh_models);
    }

    #[test]
    fn test_cli_default_with_refresh_models() {
        let cli = Cli::try_parse_from(["agentium", "--refresh-models"]).unwrap();
        assert!(cli.command.is_none());
        assert!(cli.refresh_models);
    }
}
