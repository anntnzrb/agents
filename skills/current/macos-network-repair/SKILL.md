---
name: macos-network-repair
description: "Diagnose and repair broken macOS Wi-Fi, DNS failures, and no-internet connections with staged, consent-gated fixes."
license: AGPL-3.0-or-later
---

# Repair macOS network connectivity

## Public entrypoint

```text
uv run --script <skill-dir>/scripts/cli.py [diagnose|repair] [--service NAME] [--telemetry]
```

Resolve `<skill-dir>` to this installed skill's directory. Use `fixnet` below as shorthand for that invocation.
Python 3.12+, `uv`, and macOS are required. Runtime Python dependencies are empty.

## Workflow

1. Read `references/repair.md` before running commands.
2. Run `fixnet diagnose`. Add `--telemetry` for signal, noise, channel, and PHY rate.
3. Report the observed failures. Distinguish direct HTTPS from browser, VPN, and private-name behavior.
4. If repair is authorized, run `fixnet repair` in the user's interactive terminal. Do not pass answers to its consent prompts.
5. Report the checks that passed, changes applied, unresolved failures, and any printed DNS undo command.

The default command is read-only. It sends small public connectivity probes but changes no network settings.
`repair` can flush caches and renew an existing DHCP lease. DNS changes and radio resets require separate interactive consent.
Do not run a disruptive repair through the connection carrying the user's SSH session without explicit approval.

## Repair boundaries

- Stop after successful HTTPS checks. Do not reset a working connection to optimize it.
- Preserve static IP, MTU, routes, ARP, AWDL, VPN configuration, and saved networks.
- Never infer an ISP outage from blocked ICMP or one failed destination.
- Do not substitute a remembered router address or `en0`. Discover the enabled service and device.
- DNS configuration uses the service name. Power and DHCP commands use the device name.
- Never pipe `yes`, add a force flag, or run `uv` under sudo. Let the CLI authenticate individual native commands.
- Public DNS requires resolver failures plus successful alternate DNS and pinned HTTPS. A failed trial restores the original setting.
- Keep public DNS only after a second consent prompt. Save the printed undo command before the trial.
- If a repair command fails, report it. Do not claim recovery from a planned or simulated repair.

## Common calls

```text
fixnet --help
fixnet diagnose
fixnet diagnose --telemetry
fixnet repair --service "Wi-Fi"
```

For latency, RF interference, MTU stalls, or recurring drops, use `macos-wifi-network-diagnostics` when available.
This skill owns conservative repair, not router tuning or throughput benchmarking.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Repair stages, consent, undo, and limits | `references/repair.md` | Before diagnostics or repair |
| Python versus Swift and validation commands | `references/implementation.md` | Maintaining or porting the CLI |
