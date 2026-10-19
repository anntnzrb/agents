# Security

Read when handling untrusted inputs, subprocesses, filesystem boundaries, secrets, or security-sensitive builds. [self-check]

## Boundaries

- MUST reject unknown fields in external input, using `#[serde(deny_unknown_fields)]` when deserializing with Serde or an explicit error in handwritten parsers. [cargo test; self-check]
- MUST enforce byte and collection-size limits on external input, converting into private validated domain types. [cargo test; self-check]
- MUST parse data read back from storage into validated types; stored data is an external boundary. [self-check]
- MUST bound reads of untrusted network, standard-input, and archive data with `Read::take`, body limits, and explicit limits on decoded structures. Reading a whole local file that the user names explicitly is acceptable unless the task sets a limit. [cargo test; self-check]
- MUST generate cross-language types from one OpenAPI or protobuf schema and run contract tests on both sides. NEVER hand-maintain duplicate contract types. [contract tests; self-check]
- MUST invoke subprocesses with `std::process::Command` and separate arguments. NEVER interpolate input into `sh -c`. Validate tool-specific options where untrusted arguments could become flags. [cargo test; self-check]
- SHOULD set an explicit working directory for subprocesses. [self-check]
- MUST canonicalize filesystem paths and verify containment under the canonical allowed base before access. When an attacker can race symlinks, use directory-relative APIs or another design that prevents path changes between validation and access. [cargo test; self-check]
- MUST validate foreign integers, pointers, and handle identity before admitting them into safe domain code. [self-check]

## Secrets and process state

- MUST store secrets in `secrecy::SecretString` or types with deliberate `zeroize` cleanup and use `subtle` for constant-time secret comparison. [self-check]
- MUST hash passwords with a memory-hard function such as Argon2id in PHC string format, and compare secrets in constant time. [self-check]
- MUST redact secrets from `Debug`, errors, tracing fields, and test failure output. [cargo test; self-check]
- MUST redact credentials in URLs. [self-check]
- MUST explicitly wipe secrets at the end of their security-critical lifetime when completion matters. Do not rely solely on `Drop`, which leaks and aborts can bypass. [self-check]
- MUST NOT mutate the process environment with `std::env::set_var` or `remove_var` after startup or in multithreaded code. Pass environment values to children through `Command::env` instead. [unsafe_code; governance-check; self-check]

## Build integrity

- MUST retain release `overflow-checks = true` alongside explicit checked arithmetic. NEVER disable dev or test overflow checks or debug assertions to pass a gate. [arithmetic_side_effects; governance-check; self-check]
- MUST NOT override `RUSTC`, `RUSTC_WRAPPER`, or compiler flags to circumvent checks. Use the installed toolchain and gate configuration. [governance-check; self-check]
- MUST use official Tier 1 targets for safety-critical deployments unless the project has explicitly established another validated target policy. [self-check]
- MUST inspect direct and transitive dependency risk, including unsafe code, build scripts, maintenance, advisories, and licenses. [cargo-deny; self-check]
- MUST reject OpenSSL dependencies in favor of the project's approved Rust TLS stack, normally rustls. [cargo-deny; self-check]
- MUST run the repository's human-installed fuzz target for changed untrusted-input parsers with a time bound and keep minimized failures as regression tests, or report fuzzing as missing human-owned setup. [cargo-fuzz; self-check]
- MUST change quality-gate files only on the user's request and verify required server-side checks rather than trusting skippable hooks. [governance-check; repository rulesets; self-check]
