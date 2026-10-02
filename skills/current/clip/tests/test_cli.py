"""Clipboard routing regressions, without changing the developer's clipboard."""

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cli


def input_bytes(data: bytes) -> Callable[[str | None], bytes]:
    """Return a typed stdin replacement."""

    def read(_path: str | None) -> bytes:
        return data

    return read


def available_tool(tool: str) -> str:
    """Resolve a fake executable without invoking the real clipboard."""
    return f"/bin/{tool}"


def test_captured_output_is_not_a_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    """A detached command must not report success into a pipe."""
    monkeypatch.delenv("SSH_TTY", raising=False)

    def unavailable(*_args: object, **_kwargs: object) -> int:
        raise OSError("no terminal")

    monkeypatch.setattr(os, "open", unavailable)
    with pytest.raises(OSError, match="terminal"):
        _ = cli.get_output_channel()


def test_local_macos_uses_native_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    """The local clipboard works even without a controlling terminal."""
    monkeypatch.setattr(sys, "platform", "darwin")
    for name in ("SSH_TTY", "SSH_CONNECTION", "SSH_CLIENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "argv", ["clip"])
    monkeypatch.setattr(cli, "read_input", input_bytes(b"hola\n"))
    monkeypatch.setattr(shutil, "which", available_tool)
    clipboard = io.BytesIO()

    def copy(
        command: list[str], *, input: bytes, **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        assert Path(command[0]).name == "pbcopy"
        _ = clipboard.write(input)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", copy)
    assert cli.main() == 0
    assert clipboard.getvalue() == b"hola\n"


@pytest.mark.parametrize("marker", ["SSH_TTY", "SSH_CONNECTION", "SSH_CLIENT"])
def test_remote_never_uses_native(monkeypatch: pytest.MonkeyPatch, marker: str) -> None:
    """Remote copying must target the client, not the server desktop."""
    monkeypatch.setenv(marker, "remote")
    monkeypatch.setattr(shutil, "which", available_tool)
    assert cli.native_command() is None
    monkeypatch.delenv(marker)
    monkeypatch.setattr(sys, "platform", "darwin")
    for name in ("SSH_TTY", "SSH_CONNECTION", "SSH_CLIENT"):
        monkeypatch.delenv(name, raising=False)
    assert cli.native_command() == ["/bin/pbcopy"]


@pytest.mark.parametrize(
    ("platform", "environment", "available", "expected"),
    [
        ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, "wl-copy", ["wl-copy"]),
        ("linux", {"DISPLAY": ":0"}, "xclip", ["xclip", "-selection", "clipboard"]),
        ("linux", {"DISPLAY": ":0"}, "xsel", ["xsel", "--clipboard", "--input"]),
        ("linux", {}, "xclip", None),
        ("darwin", {}, "missing", None),
    ],
)
def test_native_selection(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    environment: dict[str, str],
    available: str,
    expected: list[str] | None,
) -> None:
    """Only select tools with an available local desktop transport."""
    for name in (
        "SSH_TTY",
        "SSH_CONNECTION",
        "SSH_CLIENT",
        "WAYLAND_DISPLAY",
        "DISPLAY",
        "WSL_DISTRO_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    def resolve(tool: str) -> str | None:
        return tool if tool == available else None

    monkeypatch.setattr(shutil, "which", resolve)
    assert cli.native_command() == expected


def test_windows_native_reads_utf8_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows and WSL use PowerShell without modifying text with echo."""
    for name in ("SSH_TTY", "SSH_CONNECTION", "SSH_CLIENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("WSL_DISTRO_NAME", "test")

    def resolve(tool: str) -> str | None:
        return tool if tool == "powershell.exe" else None

    monkeypatch.setattr(shutil, "which", resolve)
    command = cli.native_command()
    assert command is not None
    assert command[:4] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
    ]
    assert "UTF8Encoding" in command[4]
    assert "Set-Clipboard -Value ([Console]::In.ReadToEnd())" in command[4]


@pytest.mark.parametrize(
    ("tmux", "screen", "outer", "expected"),
    [
        (False, False, False, b"\x1b]52;c;aG9sYQ==\x07"),
        (True, False, False, b"\x1bPtmux;\x1b\x1b]52;c;aG9sYQ==\x07\x1b\\"),
        (True, False, True, b"\x1b]52;c;aG9sYQ==\x07"),
        (False, True, False, b"\x1bP\x1b]52;c;aG9sYQ==\x07\x1b\\"),
    ],
)
def test_remote_terminal_framing(  # noqa: PLR0913 - transport scenario parameters
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    tmux: bool,
    screen: bool,
    outer: bool,
    expected: bytes,
) -> None:
    """Copy the payload through the appropriate multiplexer wire protocol."""
    monkeypatch.setattr(sys, "argv", ["clip"])
    monkeypatch.setattr(cli, "read_input", input_bytes(b"hola"))
    monkeypatch.setenv("SSH_CONNECTION", "remote")
    for key, enabled in (("TMUX", tmux), ("STY", screen)):
        if enabled:
            monkeypatch.setenv(key, "session")
        else:
            monkeypatch.delenv(key, raising=False)
    output = tmp_path / "terminal"
    monkeypatch.setattr(cli, "get_output_channel", lambda: (output.open("wb"), outer))
    assert cli.main() == 0
    assert output.read_bytes() == expected


def test_detached_command_discovers_ancestor_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A detached child can reach the agent's nearest ancestor terminal."""
    if os.name == "nt":
        pytest.skip("Unix ancestor TTY discovery")
    master, slave = os.openpty()
    tty = os.ttyname(slave)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr(os, "getppid", lambda: 100)

    def process(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        row = "200 ??" if command[2] == "100" else f"1 {tty}"
        return subprocess.CompletedProcess(command, 0, row, "")

    monkeypatch.setattr(subprocess, "run", process)
    real_open = os.open

    def open_terminal(path: str, flags: int) -> int:
        if path != tty:
            raise OSError("no controlling terminal")
        return real_open(path, flags)

    monkeypatch.setattr(os, "open", open_terminal)
    try:
        target, outer = cli.get_output_channel()
        with target:
            _ = target.write(b"\x1b]52;c;aGk=\x07")
        assert outer is False
        assert os.read(master, 1024) == b"\x1b]52;c;aGk=\x07"
    finally:
        os.close(master)
        os.close(slave)


def test_empty_input_does_not_clear_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty input is a no-op before choosing any transport."""
    monkeypatch.setattr(sys, "argv", ["clip"])
    monkeypatch.setattr(cli, "read_input", input_bytes(b""))

    def unexpected() -> None:
        pytest.fail("empty input attempted clipboard access")

    monkeypatch.setattr(cli, "native_command", unexpected)
    assert cli.main() == 0


def test_native_failure_without_terminal_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A backend failure cannot turn into silent success on captured stdout."""
    monkeypatch.setattr(sys, "argv", ["clip"])
    monkeypatch.setattr(cli, "read_input", input_bytes(b"hola"))
    monkeypatch.setattr(cli, "native_command", lambda: ["pbcopy"])

    def failed(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(7, command)

    def unavailable() -> tuple[io.BytesIO, bool]:
        raise OSError("no terminal")

    monkeypatch.setattr(subprocess, "run", failed)
    monkeypatch.setattr(cli, "get_output_channel", unavailable)
    expected_exit = 7
    assert cli.main() == expected_exit
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "copy failed" in captured.err
