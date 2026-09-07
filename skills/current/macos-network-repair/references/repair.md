# Diagnose before repairing

Read this procedure before running the CLI.

## Establish scope

Confirm whether the failure affects public websites, private names, one application, or all devices.
Treat reported failures as evidence. Run diagnostics to isolate the failing layer, not to challenge the report.
If the connection carries a remote session, warn that DHCP renewal or radio reset can disconnect it.

Run `fixnet diagnose`. The report includes the selected service, device, addressing, default IPv4 route, configured DNS, and gateway ICMP.
The CLI reads the gateway from configuration. It does not assume that the gateway is also a DNS server.
An absent IPv4 route does not prove failure on an IPv6 network.

The two HTTPS probes use Apple and Cloudflare. Each requires hostname resolution, TCP, certificate-verified TLS, and HTTP 2xx.
Redirects do not count as success. curl ignores its user configuration and proxy environment for these direct probes.
System routing can send them through a VPN or a different interface. Success does not certify the selected Wi-Fi link, browser proxies, private names, or every destination.
The timing output separates DNS, TCP, TLS, and total time. It is not a throughput or bufferbloat benchmark.

If only one target passes, investigate destination availability, VPN, proxies, or filters. The CLI skips link resets in that state.
If both pass but the reported problem remains, investigate the affected application instead of claiming that the user's problem disappeared.

## Apply staged repair

Run `fixnet repair` only when repair is authorized. Use the user's interactive terminal for sudo and consent prompts.
The CLI stops escalating whenever either HTTPS target starts working. Both must pass for exit status 0.

1. Flush the local DNS caches. Preserve configured resolvers and split DNS.
2. If both HTTPS probes fail with curl resolver error 6, query Cloudflare DNS directly.
   Require certificate-verified HTTPS pinned to the returned IPv4 address before offering a DNS trial.
3. Before accepting that trial, save the exact printed undo command. It preserves either the explicit DNS list or automatic DNS via `Empty`.
   Public DNS can break local names or alter VPN DNS precedence even though the CLI does not edit VPN settings.
4. Accept persistent DNS only after successful HTTPS checks and a separate keep prompt.
   Failed, declined, or interrupted trials restore the original setting. After restoration, the CLI checks HTTPS again.
5. If both probes still fail, renew DHCP only when `networksetup` reports `DHCP Configuration`.
   Static and unknown address configurations remain unchanged.
6. If both probes still fail, decide whether to accept the Wi-Fi power cycle.
   The CLI enables power in a `finally` block, waits up to 30 seconds for the link, and checks HTTPS again.
   macOS must rejoin a saved network. The CLI does not request passwords, force a band, or choose an access point.

Ctrl-C and SIGTERM unwind cleanup. SIGKILL, power loss, repeated interrupts, lost sudo authorization, or failing native commands can prevent restoration.
If restoration fails, use the printed DNS undo command or turn Wi-Fi on in Control Center. Do not promise crash-proof rollback.
Do not run concurrent repairs or edit DNS settings during a trial.

## Investigate unresolved failures

- If Wi-Fi cannot associate, join the network in Wi-Fi settings.
- If a captive portal is present, complete its login. Do not disable certificate verification.
- If private names or VPN applications fail, inspect split DNS and VPN policy before changing resolvers.
- If other devices also fail, inspect the router, upstream connection, and ISP status.
- If small requests pass but TLS or large transfers stall, investigate MTU and packet loss before changing MTU.
- If gateway latency spikes, inspect RF conditions and router channel width. Do not disable AWDL blindly.

Report exit status 0 as both direct HTTPS probes passing, not universal recovery.
Status 1 means unhealthy, partial, interrupted, or a runtime failure. Status 2 means usage, platform, or configuration failure.
Status 124 identifies an outer command timeout when propagated. Status 127 identifies a missing required executable.
Other native repair command errors retain their exit status.
