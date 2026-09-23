# Reload and check runners

Read this when restarting or diagnosing Amp runner processes.

Check [Amp's runner docs](https://ampcode.com/docs/markdown/cli/runners) for current runner behavior and flags.

1. Identify the requested hosts, running Amp processes, and each runner's supervisor. Distinguish a long-lived `--no-tui` runner from an interactive Amp session. Read the owning service configuration or harness documentation for launch behavior.
2. Establish authorization for the interruption. `pkill -x amp` stops every matching Amp process on that host, including interactive sessions. Use it only when the requested scope includes those processes; otherwise target the runner or use its supervisor.
3. Record the old runner PID. Restart the selected process on each authorized host, then check the supervisor state and the new Amp PID. For a runner-only restart, confirm that the interactive process survived. On remote hosts, account for the login shell rather than assuming shell syntax is portable.
4. Check plugin discovery with `amp plugins list` and, when mode behavior matters, exercise a new thread on the reloaded runner. A running process and a listed mode do not prove its model route or tools work.

Report each host's restart result and any host that failed to return. Do not treat a service's `active` status as proof that the intended runner process started.
