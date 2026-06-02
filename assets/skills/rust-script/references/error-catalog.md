# Error Catalog (Exact Message -> Fix)

Use these as deterministic mappings.

## Nightly / Flag Gating

Error:

- `running the file \`foo.rs\` requires \`-Zscript\``

Fix:

- Use nightly and place flag before file:
  `<CARGO_SCRIPT_CMD> foo.rs`

Error:

- `embedded manifest \`.../script.rs\` requires \`-Zscript\``

Fix:

- Add `-Zscript` to command using `--manifest-path script.rs`.

## Dispatch / Path Ambiguity

Error:

- `no such command: \`echo\``+ help suggesting`./echo`

Fix:

- Use relative or absolute path for extensionless script:
  `<CARGO_SCRIPT_CMD> ./echo`

Error:

- `no such file or subcommand \`foo.rs\``

Fix:

- verify file path exists
- if typo, use suggested nearby script path

Error:

- on stable without `-Zscript`: `no such subcommand \`foo.rs\``

Fix:

- switch to nightly + `-Zscript`

## Manifest Path Validation

Error:

- `manifest path \`script.rs\` does not exist`

Fix:

- correct path or cwd

Error:

- `the manifest-path must be a path to a Cargo.toml or script file`

Fix:

- pass `Cargo.toml` or script file path only

## Embedded Manifest Restrictions

Error:

- ``...` is/are not allowed in embedded manifests``

Fix:

- remove disallowed field/table and convert script to normal Cargo package if needed

Error:

- `the binary target name \`deps\` is forbidden, it conflicts with cargo's build directory names`

Fix:

- rename script file / package name to avoid `deps`

## Unsupported Command Surfaces

Error:

- `.../script.rs is unsupported by \`cargo package\``
- `.../script.rs is unsupported by \`cargo publish\``

Fix:

- convert to standard package and package/publish from directory project

Error:

- ``.../script.rs` is not a directory. --path must point to a directory containing a Cargo.toml file.`

Fix:

- for install, provide package directory path, not script file path

Error:

- `single file packages cannot be used as dependencies`

Fix:

- depend on normal package path/git/registry source, not script file source

## Frontmatter Parse Shape

Likely causes:

- mismatched opening/closing dash count
- unsupported infostring attributes
- multiple frontmatter blocks
- trailing characters after closing fence

Fix pattern:

1. reduce to one block
2. ensure matching fence lengths
3. use `---cargo` or plain `---`
4. keep close line clean (`---` + whitespace only)
