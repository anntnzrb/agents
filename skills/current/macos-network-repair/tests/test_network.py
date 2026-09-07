"""Exercise repair transitions without host network changes or runtime packages."""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import patch

from fixnet import network

if TYPE_CHECKING:
    from collections.abc import Sequence

SERVICE = network.Service("Office Wi-Fi's network", "en7")
FAILED = [network.Result(6, "resolver failed"), network.Result(6, "resolver failed")]
PASSED = [network.Result(0, "200 OK"), network.Result(0, "200 OK")]


@dataclass
class Mac:
    """Model the native-command boundary with address and radio state."""

    dns: list[str] = field(default_factory=lambda: ["9.9.9.9", "149.112.112.112"])
    power: bool = True
    dhcp: bool = True
    renewed: bool = False
    reachable_with_dns: bool = True
    broken_write: bool = False
    interrupt_probe: bool = False
    changes: list[list[str]] = field(default_factory=list)

    def run(self, command: Sequence[str], *, timeout: float = 12) -> network.Result:
        """Emulate native network effects instead of internal call order."""
        assert timeout > 0
        args = list(command)
        if "-setdnsservers" in args:
            self.dns = args[3:]
            self.changes.append(args)
            if self.broken_write and self.dns == ["1.1.1.1", "1.0.0.1"]:
                return network.Result(1, "write failed after changing state")
        elif "-getdnsservers" in args:
            return network.Result(0, "\n".join(self.dns))
        elif "-getinfo" in args:
            return network.Result(
                0, "DHCP Configuration" if self.dhcp else "Manual Configuration"
            )
        elif args[0] == "/usr/bin/dig":
            return network.Result(0, "alias.example.\n203.0.113.10")
        elif args[0] == network.CURL:
            return self.https(args)
        elif "-setairportpower" in args:
            self.power = args[-1] == "on"
            self.changes.append(args)
        elif args[0] == "/sbin/ifconfig":
            return network.Result(
                0, "status: active" if self.power else "status: inactive"
            )
        elif args[0] == "/usr/sbin/ipconfig":
            self.renewed = True
            self.changes.append(args)
        else:
            self.changes.append(args)
        return network.Result(0, "")

    def https(self, args: list[str]) -> network.Result:
        """Resolve through the current simulated DNS setting."""
        if "--resolve" in args:
            return network.Result(0, "200 pinned TLS passed")
        if self.interrupt_probe:
            raise KeyboardInterrupt
        if self.reachable_with_dns and self.dns == ["1.1.1.1", "1.0.0.1"]:
            return network.Result(0, "200 OK")
        return network.Result(6, "resolver failed")


class RepairTests(unittest.TestCase):
    """Protect mutable network state at the native-command boundary."""

    def setUp(self) -> None:
        """Replace native commands, authentication and delays for each test."""
        self.mac = Mac()
        self.enterContext(patch.object(network, "run", self.mac.run))
        self.enterContext(patch.object(network, "authorize", lambda: None))
        self.enterContext(patch.object(network.os, "geteuid", lambda: 0, create=True))
        self.enterContext(patch.object(network.time, "sleep", lambda _: None))

    def test_partial_connectivity_never_mutates(self) -> None:
        """One working endpoint must prevent a link reset."""
        partial = [PASSED[0], FAILED[1]]
        assert network.repair(SERVICE, partial) == partial
        assert self.mac.changes == []

    def test_static_addressing_survives_failed_repairs(self) -> None:
        """A broken static-IP network must not be converted to DHCP."""
        self.mac.dhcp = False
        with patch.object(network, "confirm", return_value=False):
            assert not network.healthy(network.repair(SERVICE, FAILED))
        assert not self.mac.renewed
        assert self.mac.power

    def test_failed_dns_trial_restores_original(self) -> None:
        """Public resolver reachability alone is insufficient to keep a DNS change."""
        original = self.mac.dns.copy()
        self.mac.reachable_with_dns = False
        with patch.object(network, "confirm", return_value=True):
            assert not network.healthy(network.dns_trial(SERVICE, FAILED))
        assert self.mac.dns == original

    def test_dns_keep_requires_separate_consent(self) -> None:
        """Declining persistence restores DNS and reports post-restore failure."""
        original = self.mac.dns.copy()
        with patch.object(network, "confirm", side_effect=[True, False]):
            assert not network.healthy(network.dns_trial(SERVICE, FAILED))
        assert self.mac.dns == original

    def test_successful_dns_trial_can_be_kept(self) -> None:
        """Only a healthy trial plus keep consent may leave public DNS configured."""
        with patch.object(network, "confirm", return_value=True):
            assert network.healthy(network.dns_trial(SERVICE, FAILED))
        assert self.mac.dns == ["1.1.1.1", "1.0.0.1"]

    def test_partial_dns_write_failure_restores_original(self) -> None:
        """A failed command may already have mutated DNS; restoration must still run."""
        original = self.mac.dns.copy()
        self.mac.broken_write = True
        with (
            patch.object(network, "confirm", return_value=True),
            self.assertRaises(network.RepairError),
        ):
            network.dns_trial(SERVICE, FAILED)
        assert self.mac.dns == original

    def test_interrupted_dns_trial_restores_original(self) -> None:
        """Ctrl-C during verification must not strand a temporary DNS override."""
        original = self.mac.dns.copy()
        self.mac.interrupt_probe = True
        with (
            patch.object(network, "confirm", return_value=True),
            self.assertRaises(KeyboardInterrupt),
        ):
            network.dns_trial(SERVICE, FAILED)
        assert self.mac.dns == original

    def test_interrupted_radio_cycle_enables_wifi(self) -> None:
        """Ctrl-C during the power-off interval must still restore radio power."""
        with (
            patch.object(network.time, "sleep", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            network.cycle_radio(SERVICE)
        assert self.mac.power


class BoundaryTests(unittest.TestCase):
    """Exercise native output parsing and subprocess failures."""

    def test_renamed_and_disabled_services(self) -> None:
        """Preserve service names and exclude disabled and non-Wi-Fi services."""
        text = """(1) Office Wi-Fi's network
(Hardware Port: Wi-Fi, Device: en7)
(*) Disabled Wi-Fi
(Hardware Port: Wi-Fi, Device: en8)
(3) Thunderbolt Bridge
(Hardware Port: Thunderbolt Bridge, Device: bridge0)
"""
        assert network.services_from(text) == [SERVICE]

    def test_unknown_dns_cannot_be_restore_arguments(self) -> None:
        """Unreadable settings must stop a DNS trial rather than poison rollback."""
        with self.assertRaises(network.RepairError):
            network.parse_dns("An Error occurred while reading preferences")
        assert network.parse_dns("There aren't any DNS Servers set on Wi-Fi.") == [
            "Empty"
        ]

    def test_redirect_does_not_count_as_recovery(self) -> None:
        """An HTTP redirect can indicate a portal and cannot satisfy HTTPS health."""
        with patch.object(
            network, "run", return_value=network.Result(0, "302 redirect")
        ):
            assert not network.probe(network.TARGETS[0]).ok

    def test_unsupported_platform_never_discovers_network(self) -> None:
        """Non-macOS hosts must fail before executing native networking commands."""
        with patch.object(network.sys, "platform", "linux"):
            assert network.main(["repair"]) == 2

    def test_subprocess_drains_output_and_bounds_time(self) -> None:
        """Pipe-sized output and a hung child must not freeze an emergency repair."""
        large = network.run([sys.executable, "-c", "print('x' * 200000)"])
        assert large.ok
        assert large.output == "x" * 200000
        hung = network.run(
            [sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1
        )
        assert hung.code == network.TIMEOUT
