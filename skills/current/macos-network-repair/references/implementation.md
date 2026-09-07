# Python versus Swift

Read this explanation when maintaining or porting the CLI.

The repair workflow orchestrates macOS executables. Python's standard library covers subprocess deadlines, output collection, argument parsing, IP validation, JSON, and cleanup. A Swift compiler and PyObjC are unnecessary for this workflow.

The original Swift script used CoreWLAN for interface discovery and RF telemetry. This implementation reads service/device pairs from `networksetup` and optional telemetry from `system_profiler SPAirPortDataType -json`. The bundled parser does not assume that a channel above 14 is 5 GHz. That inference would mislabel 6 GHz channels.

Swift remains appropriate for direct CoreWLAN APIs, association control, native event callbacks, or a signed macOS application. A Python port of those APIs would need a bridge such as PyObjC. This CLI does not need them.

Python does not make these repairs cross-platform. The CLI rejects non-macOS hosts before running native commands. Offline use requires `uv` and a compatible Python interpreter already installed. There are no runtime packages to download after the interpreter is available.

The standalone Swift script is not a dependency and is not modified by this skill. The Python CLI defaults to diagnostics, uses separate consent for keeping DNS, and attempts cleanup on Ctrl-C and SIGTERM.

## Validation reference

Run from the agents repository root:

```text
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/macos-network-repair
uv run --script skills/current/skill-creator/scripts/cli.py gates skills/current/macos-network-repair --tests
uv run --script skills/current/macos-network-repair/scripts/cli.py --help
uv run --script skills/current/macos-network-repair/scripts/cli.py diagnose --telemetry
git diff --check
```

The live diagnostic command sends public HTTPS probes and gateway ICMP. Tests replace the native-command boundary for repair scenarios so they cannot change the host network.
No test under `sync/tests/` owns this skill's behavior.
