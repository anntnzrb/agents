pub mod catalog;
pub mod cliproxy;
pub mod extensions;
pub mod harness;
pub mod harness_adapters;
pub mod hook_state;
pub mod jobs;
pub mod launcher;
pub mod managed_state;
pub mod managed_tools;
pub mod model_catalog_client;
pub mod orchestration;
pub mod packages;
pub mod plan;
pub mod runtime;
pub mod secret_template;
pub mod tool_launchers;
pub mod wrappers;

/// The executable name shared by the library and command-line layers.
pub const PRODUCT_NAME: &str = "agentium";

pub use orchestration::{
    DEFAULT_SYNC_TIMEOUT_SECONDS, SYNC_LOCK_FILE, SyncOptions, launch_main, launch_main_with_env,
    run_sync, sync_lock_path, sync_main, sync_main_with_env, try_acquire_sync_lock,
};
