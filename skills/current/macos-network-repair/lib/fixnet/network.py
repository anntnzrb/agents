"""Run bounded macOS commands and repair only while HTTPS remains broken."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import FrameType

NETWORKSETUP = "/usr/sbin/networksetup"
CURL = "/usr/bin/curl"
TARGETS = (
    ("www.apple.com", "https://www.apple.com/library/test/success.html"),
    ("www.cloudflare.com", "https://www.cloudflare.com/cdn-cgi/trace"),
)
DNS_FAILURE = 6
HTTP_FAILURE = 22
TIMEOUT = 124
MISSING_COMMAND = 127
HTTP_OK_MIN = 200
HTTP_OK_MAX = 300


@dataclass(frozen=True)
class Result:
    """Command output and its unmodified exit status."""

    code: int
    output: str

    @property
    def ok(self) -> bool:
        """Return whether the command succeeded."""
        return self.code == 0


@dataclass(frozen=True)
class Service:
    """An enabled macOS Wi-Fi service and its hardware device."""

    name: str
    device: str


class RepairError(Exception):
    """An operational failure with a CLI exit status."""

    def __init__(self, message: str, code: int = 1) -> None:
        """Preserve the user-facing error and exit status."""
        super().__init__(message)
        self.code = code


def run(command: Sequence[str], *, timeout: float = 12) -> Result:
    """Drain both output streams and kill timed-out children without a shell."""
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "LC_ALL": "C"},
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RepairError(
            f"Required executable missing: {command[0]}", MISSING_COMMAND
        ) from exc
    except subprocess.TimeoutExpired:
        return Result(TIMEOUT, f"Timed out: {shlex.join(command)}")
    return Result(completed.returncode, completed.stdout.strip())


def required(command: Sequence[str]) -> str:
    """Read configuration, stopping rather than guessing after command failure."""
    result = run(command)
    if not result.ok:
        raise RepairError(result.output, result.code)
    return result.output


def services_from(text: str) -> list[Service]:
    """Parse service/device pairs without treating device IDs as service names."""
    services: list[Service] = []
    name: str | None = None
    for line in text.splitlines():
        header = re.fullmatch(r"\((\d+|\*)\) (.+)", line)
        if header:
            name = header[2] if header[1] != "*" else None
        hardware = re.fullmatch(
            r"\(Hardware Port: (?:Wi-Fi|AirPort), Device: ([^)]+)\)", line
        )
        if hardware and name:
            services.append(Service(name, hardware[1]))
    return services


def discover(name: str | None) -> Service:
    """Select the requested service or require exactly one enabled Wi-Fi service."""
    services = services_from(required([NETWORKSETUP, "-listnetworkserviceorder"]))
    selected = [service for service in services if name is None or service.name == name]
    if len(selected) != 1:
        choices = ", ".join(service.name for service in services) or "none"
        raise RepairError(
            f"Select one enabled Wi-Fi service with --service. Available: {choices}", 2
        )
    return selected[0]


def field(text: str, key: str) -> str | None:
    """Read one named field from macOS command output."""
    for line in text.splitlines():
        label, separator, value = line.strip().partition(":")
        if separator and label == key:
            return value.strip()
    return None


def probe(target: tuple[str, str], address: str | None = None) -> Result:
    """Require hostname-based verified TLS and a 2xx HTTP response."""
    command = [
        CURL,
        "-q",
        "--noproxy",
        "*",
        "--silent",
        "--show-error",
        "--fail",
        "--connect-timeout",
        "4",
        "--max-time",
        "8",
        "--output",
        os.devnull,
        "--write-out",
        (
            "%{http_code} DNS=%{time_namelookup}s TCP=%{time_connect}s "
            "TLS=%{time_appconnect}s total=%{time_total}s"
        ),
    ]
    if address:
        command.extend(["--resolve", f"{target[0]}:443:{address}"])
    result = run([*command, target[1]], timeout=10)
    if not result.ok:
        return result
    status = result.output.partition(" ")[0]
    if status.isdigit() and HTTP_OK_MIN <= int(status) < HTTP_OK_MAX:
        return result
    return Result(HTTP_FAILURE, result.output)


def check() -> list[Result]:
    """Report both independent HTTPS probes; ICMP never determines recovery."""
    results = []
    for target in TARGETS:
        result = probe(target)
        print(f"{target[0]}: {'OK' if result.ok else 'FAIL'} {result.output}")
        results.append(result)
    return results


def healthy(results: Sequence[Result]) -> bool:
    """Require all attempted endpoints to pass."""
    return bool(results) and all(result.ok for result in results)


def report(service: Service) -> None:
    """Show address, route and resolver context without publishing private logs."""
    info = required([NETWORKSETUP, "-getinfo", service.name])
    print(info)
    route = run(["/sbin/route", "-n", "get", "default"])
    print(f"Default route device: {field(route.output, 'interface') or 'none'}")
    print(f"Default gateway: {field(route.output, 'gateway') or 'none'}")
    gateway = field(info, "Router")
    if gateway:
        try:
            ipaddress.ip_address(gateway)
        except ValueError:
            pass
        else:
            ping = run(
                ["/sbin/ping", "-n", "-c", "3", "-W", "1000", gateway], timeout=5
            )
            print(
                f"Gateway ICMP (blocked ICMP does not prove an outage):\n{ping.output}"
            )
    print("Configured DNS:", required([NETWORKSETUP, "-getdnsservers", service.name]))
    print("Direct HTTPS follows system routing and may use a VPN or another interface.")
    print("Browser proxies, private DNS names and every destination are not tested.")


def telemetry() -> None:
    """Print selected RF fields from system_profiler, not its full private payload."""
    result = run(
        ["/usr/sbin/system_profiler", "SPAirPortDataType", "-json"], timeout=25
    )
    if not result.ok:
        print(f"Wi-Fi telemetry unavailable: {result.output}", file=sys.stderr)
        return
    try:
        payload = json.loads(result.output)
    except json.JSONDecodeError:
        print(
            "Wi-Fi telemetry unavailable: invalid system_profiler JSON", file=sys.stderr
        )
        return
    if not isinstance(payload, dict):
        return
    for section in payload.get("SPAirPortDataType", []):
        if not isinstance(section, dict):
            continue
        for interface in section.get("spairport_airport_interfaces", []):
            if not isinstance(interface, dict):
                continue
            current = interface.get("spairport_current_network_information")
            if isinstance(current, dict):
                print(
                    "RF:",
                    {
                        key: current.get(key, "unavailable")
                        for key in (
                            "spairport_network_channel",
                            "spairport_signal_noise",
                            "spairport_network_rate",
                        )
                    },
                )


def confirm(question: str) -> bool:
    """Require an interactive affirmative answer; never auto-approve through stdin."""
    if not sys.stdin.isatty():
        print(f"Skipped (interactive consent required): {question}")
        return False
    return input(f"{question} [y/N] ").strip().lower() == "y"


def authorize() -> None:
    """Authenticate sudo in the terminal without elevating Python or uv."""
    if os.geteuid() == 0:
        return
    if not sys.stdin.isatty():
        raise RepairError(
            "Run repair from an interactive terminal for sudo authentication.", 2
        )
    result = subprocess.run(["/usr/bin/sudo", "-v"], timeout=120, check=False)
    if result.returncode:
        raise RepairError("sudo authentication failed", result.returncode)


def change(command: Sequence[str]) -> None:
    """Run one privileged mutation and fail visibly if it does not succeed."""
    print("Running:", shlex.join(command))
    prefix = [] if os.geteuid() == 0 else ["/usr/bin/sudo", "-n"]
    result = run([*prefix, *command])
    if not result.ok:
        raise RepairError(f"Command failed: {result.output}", result.code)


def flush_dns() -> None:
    """Flush caches without replacing configured or split DNS."""
    change(["/usr/bin/dscacheutil", "-flushcache"])
    change(["/usr/bin/killall", "-HUP", "mDNSResponder"])


def parse_dns(text: str) -> list[str]:
    """Preserve explicit DNS or the automatic setting; reject unknown output."""
    if text.startswith("There aren't any DNS Servers set on "):
        return ["Empty"]
    servers = text.splitlines()
    try:
        if not servers:
            raise ValueError("Empty DNS response")
        for server in servers:
            ipaddress.ip_address(server)
    except ValueError as exc:
        raise RepairError(
            "Cannot safely capture current DNS settings; no DNS changes made.", 2
        ) from exc
    return servers


def dns_trial(service: Service, results: list[Result]) -> list[Result]:
    """Try alternate DNS only after DNS failure is isolated; roll back failed trials."""
    if not all(result.code == DNS_FAILURE for result in results):
        return results
    answer = run(
        [
            "/usr/bin/dig",
            "@1.1.1.1",
            TARGETS[0][0],
            "A",
            "+short",
            "+time=2",
            "+tries=1",
        ]
    )
    addresses = []
    for line in answer.output.splitlines():
        try:
            addresses.append(str(ipaddress.IPv4Address(line)))
        except ipaddress.AddressValueError:
            continue
    if not answer.ok or not addresses or not probe(TARGETS[0], addresses[0]).ok:
        return results
    old = parse_dns(required([NETWORKSETUP, "-getdnsservers", service.name]))
    restore = [NETWORKSETUP, "-setdnsservers", service.name, *old]
    print("Public DNS plus pinned HTTPS work; hostname-based HTTPS failed to resolve.")
    print("Save this undo command:", shlex.join(["sudo", *restore]))
    if not confirm(
        "Try Cloudflare DNS? Local names and VPN DNS precedence may change."
    ):
        return results
    keep = False
    try:
        change([NETWORKSETUP, "-setdnsservers", service.name, "1.1.1.1", "1.0.0.1"])
        flush_dns()
        results = check()
        if healthy(results):
            keep = confirm(
                "Keep DNS persistently? Otherwise restore the original settings."
            )
    finally:
        if not keep:
            print("Restoring original DNS settings.")
            change(restore)
            flush_dns()
    return results if keep else check()


def cycle_radio(service: Service) -> list[Result]:
    """Restore power even after an interrupted reset, then wait for link readiness."""
    print("Wi-Fi reset interrupts sessions. macOS must rejoin a saved network.")
    print("If this process is killed, turn Wi-Fi on from Control Center.")
    try:
        change([NETWORKSETUP, "-setairportpower", service.device, "off"])
        time.sleep(1)
    finally:
        change([NETWORKSETUP, "-setairportpower", service.device, "on"])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        time.sleep(1)
        link = run(["/sbin/ifconfig", service.device])
        if field(link.output, "status") == "active":
            break
    return check()


def repair(service: Service, results: list[Result]) -> list[Result]:
    """Escalate caches, isolated DNS, existing DHCP, and a consent-gated radio reset."""
    if any(result.ok for result in results):
        return results
    authorize()
    print("Stage 1: flush DNS caches.")
    flush_dns()
    results = check()
    if any(result.ok for result in results):
        return results
    results = dns_trial(service, results)
    if any(result.ok for result in results):
        return results
    info = required([NETWORKSETUP, "-getinfo", service.name])
    if info.startswith("DHCP Configuration"):
        print("Stage 2: renew the existing DHCP configuration.")
        change(["/usr/sbin/ipconfig", "set", service.device, "DHCP"])
        time.sleep(3)
        results = check()
    else:
        print("Skipping DHCP renewal: static or unknown addressing is preserved.")
    if not any(result.ok for result in results) and confirm(
        "Cycle Wi-Fi power and disconnect Wi-Fi sessions?"
    ):
        results = cycle_radio(service)
    return results


def interrupted(_signum: int, _frame: FrameType | None) -> None:
    """Unwind repair cleanup on SIGTERM just as on Ctrl-C."""
    raise KeyboardInterrupt


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the CLI and keep all repairs opt-in and macOS-only."""
    parser = argparse.ArgumentParser(
        prog="fixnet",
        description="Diagnose macOS Wi-Fi; explicitly request staged repair.",
        epilog="Examples: fixnet diagnose --telemetry; fixnet repair --service 'Wi-Fi'",
    )
    parser.add_argument(
        "mode", choices=("diagnose", "repair"), nargs="?", default="diagnose"
    )
    parser.add_argument("--service", help="Exact enabled Wi-Fi network service name")
    parser.add_argument(
        "--telemetry",
        action="store_true",
        help="Include system_profiler RF measurements",
    )
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        print("fixnet requires macOS and its native network commands.", file=sys.stderr)
        return 2
    previous_handler = signal.signal(signal.SIGTERM, interrupted)
    try:
        service = discover(args.service)
        print(f"Wi-Fi service: {service.name}; device: {service.device}")
        report(service)
        if args.telemetry:
            telemetry()
        results = check()
        if args.mode == "repair" and not healthy(results):
            results = repair(service, results)
        if healthy(results):
            print("HEALTHY: both direct HTTPS checks passed.")
            return 0
        print(
            "UNRESOLVED/PARTIAL: check captive portal, VPN, filters, router or ISP. "
            "No root cause is proven.",
            file=sys.stderr,
        )
    except RepairError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    except subprocess.TimeoutExpired:
        print("Authentication timed out.", file=sys.stderr)
        return TIMEOUT
    except (OSError, EOFError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "Interrupted. Cleanup was attempted. "
            "Use printed recovery commands if it failed.",
            file=sys.stderr,
        )
        return 1
    else:
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
