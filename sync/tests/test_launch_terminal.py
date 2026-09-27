# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Interactive launches keep the terminal: the harness replaces the wrapper.

Each test runs ``launch_main`` inside a fresh PTY against a pre-seeded npm
cache whose binary is a probe. ``npm`` is absent from ``PATH``, so the launcher
takes its offline cached-package fallback without touching the network.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import pty
import signal
import struct
import sys
import termios
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from sync.core.launcher import NpmPackageSpec, npm_cache_layout

if TYPE_CHECKING:
    from collections.abc import Callable

# xdist workers are multi-threaded; the forked child only calls execve.
pytestmark = pytest.mark.filterwarnings(
    "ignore:This process .* is multi-threaded, use of forkpty:DeprecationWarning"
)

TOOL: Final[str] = "mcporter"
EXIT_SIGINT: Final[int] = 130
EXIT_SIGTERM: Final[int] = 143
PROBE_WAIT_SECONDS: Final[float] = 15.0
MODE_EXECUTABLE: Final[int] = 0o755

PROBE: Final[str] = r"""
import os, signal, sys, time
case, out = sys.argv[1], sys.argv[2]
def say(msg):
    with open(out, "a") as f:
        f.write(msg + "\n")
if case == "tty":
    try:
        fg = os.tcgetpgrp(0)
    except OSError as e:
        fg = f"ERR{e.errno}"
    try:
        os.close(os.open("/dev/tty", os.O_RDWR))
        devtty = "ok"
    except OSError as e:
        devtty = f"ERR{e.errno}"
    sigpipe = os.environ["PROBE_SIGPIPE"]
    say(f"fg_is_self={fg == os.getpgid(0)} devtty={devtty} sigpipe={sigpipe}")
    sys.exit(0)
if case == "winch":
    signal.signal(signal.SIGWINCH, lambda *_: (say("winch"), os._exit(0)))
if case == "int":
    signal.signal(signal.SIGINT, lambda *_: (say("int"), os._exit(130)))
if case == "term":
    signal.signal(signal.SIGTERM, lambda *_: (say("term"), os._exit(143)))
print("READY", flush=True)
time.sleep(10)
say("no signal")
"""

WRAPPER: Final[str] = (
    "import sys\n"
    "from sync.core.index import launch_main\n"
    f"sys.exit(launch_main({TOOL!r}, sys.argv[1:]))\n"
)


def _seed_cache(home: Path) -> None:
    """Install a probe as the current cached package for the tool launcher."""
    spec = NpmPackageSpec(tool=TOOL, package=TOOL, bin=TOOL)
    layout = npm_cache_layout(str(home), spec, str(home / ".cache"))
    version_dir = Path(layout.versions_dir) / "1.0.0"
    probe = version_dir / "probe.py"
    probe.parent.mkdir(parents=True)
    _ = probe.write_text(PROBE, encoding="utf-8")
    bin_path = version_dir / "node_modules" / ".bin" / TOOL
    bin_path.parent.mkdir(parents=True)
    # Python re-ignores SIGPIPE at startup, so the shell shim observes it.
    shim = [
        "#!/bin/sh",
        "if /bin/sh -c 'kill -PIPE $$'; then PROBE_SIGPIPE=ignored;",
        "else PROBE_SIGPIPE=default; fi",
        "export PROBE_SIGPIPE",
        f'exec "{sys.executable}" "{probe}" "$@"',
    ]
    _ = bin_path.write_text("\n".join(shim) + "\n", encoding="utf-8")
    bin_path.chmod(MODE_EXECUTABLE)
    manifest = version_dir / "node_modules" / TOOL / "package.json"
    manifest.parent.mkdir(parents=True)
    _ = manifest.write_text(
        json.dumps({"name": TOOL, "version": "1.0.0"}), encoding="utf-8"
    )
    Path(layout.current_link).symlink_to(Path("versions") / "1.0.0")


def _launch_in_pty(
    tmp_path: Path,
    case: str,
    act: Callable[[int, int], None] | None = None,
) -> tuple[str, int]:
    """Launch the probe via ``launch_main`` in a PTY; return its report and status."""
    home = tmp_path / "home"
    _seed_cache(home)
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    out = tmp_path / "probe.out"
    env = {
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "PATH": str(empty_path),
        "TERM": "dumb",
    }
    argv = [sys.executable, "-c", WRAPPER, case, str(out)]
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - replaced by exec in the child
        os.execve(argv[0], argv, env)  # noqa: S606
    try:
        os.set_blocking(fd, False)
        buffer = b""
        acted = False
        status: int | None = None
        deadline = time.monotonic() + PROBE_WAIT_SECONDS
        while time.monotonic() < deadline:
            waited, raw_status = os.waitpid(pid, os.WNOHANG)
            if waited:
                status = raw_status
                break
            with contextlib.suppress(OSError):
                buffer += os.read(fd, 4096)
            if act is not None and not acted and b"READY" in buffer:
                acted = True
                time.sleep(0.2)
                act(pid, fd)
            time.sleep(0.02)
        if status is None:
            os.kill(pid, signal.SIGKILL)
            _, status = os.waitpid(pid, 0)
            pytest.fail(f"launch did not exit; output: {buffer!r}")
    finally:
        os.close(fd)
    report = out.read_text(encoding="utf-8").strip() if out.exists() else ""
    return report, os.waitstatus_to_exitcode(status)


def test_launched_harness_owns_the_controlling_terminal(tmp_path: Path) -> None:
    """The harness owns the terminal and starts with default signal handling.

    Python ignores SIGPIPE, and ignored dispositions survive exec; the harness
    and the shells it spawns must not inherit that.
    """
    report, code = _launch_in_pty(tmp_path, "tty")

    assert report == "fg_is_self=True devtty=ok sigpipe=default"
    assert code == 0


def test_terminal_resize_reaches_launched_harness(tmp_path: Path) -> None:
    """A PTY resize delivers SIGWINCH to the harness."""

    def resize(_pid: int, fd: int) -> None:
        _ = fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 120, 0, 0))

    report, code = _launch_in_pty(tmp_path, "winch", resize)

    assert report == "winch"
    assert code == 0


def test_terminal_interrupt_reaches_launched_harness(tmp_path: Path) -> None:
    """^C delivers SIGINT to the harness, whose own exit status is returned."""

    def interrupt(_pid: int, fd: int) -> None:
        _ = os.write(fd, b"\x03")

    report, code = _launch_in_pty(tmp_path, "int", interrupt)

    assert report == "int"
    assert code == EXIT_SIGINT


def test_sigterm_to_launched_pid_stops_harness(tmp_path: Path) -> None:
    """A supervisor's SIGTERM to the wrapper PID reaches the harness itself."""

    def terminate(pid: int, _fd: int) -> None:
        os.kill(pid, signal.SIGTERM)

    report, code = _launch_in_pty(tmp_path, "term", terminate)

    assert report == "term"
    assert code == EXIT_SIGTERM
