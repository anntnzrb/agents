#!/usr/bin/env -S cargo -q -Zscript run --release --manifest-path
---cargo
[package]
edition = "2024"

[dependencies]
wait-timeout = "0.2"
walkdir = "2"

[dev-dependencies]
tempfile = "3"

[lints.rust]
warnings = { level = "deny", priority = -2 }
future_incompatible = { level = "deny", priority = -1 }
rust_2018_idioms = { level = "deny", priority = -1 }
rust_2024_compatibility = { level = "deny", priority = -1 }
unused = { level = "deny", priority = -1 }
nonstandard_style = { level = "deny", priority = -1 }
unsafe_code = "forbid"
missing_docs = "deny"
missing_debug_implementations = "deny"
missing_copy_implementations = "deny"
unreachable_pub = "deny"
single_use_lifetimes = "deny"
private_interfaces = "deny"
private_bounds = "deny"
unused_crate_dependencies = "deny"

[lints.rustdoc]
all = "deny"
broken_intra_doc_links = "deny"
private_intra_doc_links = "deny"
missing_crate_level_docs = "deny"
private_doc_tests = "deny"
invalid_codeblock_attributes = "deny"
invalid_rust_codeblocks = "deny"
invalid_html_tags = "deny"
bare_urls = "deny"
unescaped_backticks = "deny"
redundant_explicit_links = "deny"
---

//! Sync runner entrypoint for syncing agent configs into tool homes.
#[path = "lib.rs"]
mod sync;

fn main() -> std::process::ExitCode {
    sync::main()
}
