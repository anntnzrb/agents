# Cargo Script Workflow

Set `<CARGO_SCRIPT_CMD>` by environment:
- rustup toolchain selector style: `cargo +nightly -Zscript`
- nightly cargo already on PATH (common in Nix): `cargo -Zscript`

## Canonical Command Shapes

Run script directly:

```sh
<CARGO_SCRIPT_CMD> ./script.rs -- arg1 arg2
```

Run through subcommand:

```sh
<CARGO_SCRIPT_CMD> run --manifest-path ./script.rs -- arg1 arg2
```

Non-run commands:

```sh
<CARGO_SCRIPT_CMD> check --manifest-path ./script.rs
<CARGO_SCRIPT_CMD> build --manifest-path ./script.rs
<CARGO_SCRIPT_CMD> test --manifest-path ./script.rs
```

## Script File Skeleton

```rust
#!/usr/bin/env -S cargo -Zscript
---cargo
[package]
name = "tool"
edition = "2024"

[dependencies]
anyhow = "1"
clap = { version = "4", features = ["derive"] }
---

use clap::Parser;

#[derive(Parser)]
struct Args {
    #[arg(long)]
    name: Option<String>,
}

fn main() {
    let args = Args::parse();
    println!("{:?}", args.name);
}
```

## Operational Notes

- `cargo <path.rs>` works as manifest-command form; still requires `-Zscript`.
- Manifest-command precedence beats external subcommands when path is recognized.
- For extensionless files, use `./name`; bare `name` is treated as command lookup.
- Arguments after script path are script args; pass global Cargo flags before script path.

## Build/Lock Location Behavior

For embedded manifests:
- default build dir is under Cargo cache (`{cargo-cache-home}/build/{workspace-path-hash}`)
- target dir defaults to `<build-dir>/target`
- lockfile root is tied to build-dir hash; no local `./Cargo.lock` next to script by default

Implications:
- script repositories stay clean
- build products are shared by Cargo cache policy
- if users expect local lockfile in script dir, explain this is current design

## Config Scope Behavior

`cargo <script.rs>` reloads config rooted at script parent path (install-like behavior), not caller cwd behavior from regular project commands.

If config surprises appear:
- inspect nearest `.cargo/config.toml` from script location
- do not assume workspace-root config from current shell cwd

## `arg0` vs executable path

For embedded manifests:
- `arg0` is script path
- executable path should be obtained via `std::env::current_exe()`

## Recommended Debug Flow

1. Validate parser/frontmatter:

```sh
<CARGO_SCRIPT_CMD> check --manifest-path ./script.rs -v
```

2. Validate command dispatch:

```sh
<CARGO_SCRIPT_CMD> -v ./script.rs -- --help
```

3. Validate dependency graph:

```sh
<CARGO_SCRIPT_CMD> tree --manifest-path ./script.rs
```

4. If editing deps, test mutators:

```sh
<CARGO_SCRIPT_CMD> add --manifest-path ./script.rs serde --features derive
<CARGO_SCRIPT_CMD> remove --manifest-path ./script.rs serde
```
