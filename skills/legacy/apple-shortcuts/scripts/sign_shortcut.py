# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Archive and sign an Apple Shortcuts plist on macOS."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

VALID_MODES = ("anyone", "people-who-know-me")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Unsigned shortcut plist/XML")
    parser.add_argument(
        "--name",
        help="Final shortcut name; defaults to the input stem",
    )
    parser.add_argument(
        "--mode",
        choices=VALID_MODES,
        default=os.environ.get("SHORTCUTS_PLAYGROUND_SIGNING_MODE", "anyone"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=os.environ.get("SHORTCUTS_PLAYGROUND_OUTPUT_DIR") or None,
        help="Required output directory; may also use SHORTCUTS_PLAYGROUND_OUTPUT_DIR",
    )
    return parser


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.mode not in VALID_MODES:
        choices = ", ".join(repr(mode) for mode in VALID_MODES)
        parser.error(
            f"argument --mode: invalid choice: {args.mode!r} (choose from {choices})",
        )
    return args


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        shell=False,
        capture_output=True,
        text=True,
    )


def _sign(shortcuts: str, mode: str, source: Path, output: Path) -> int:
    completed = _run(
        [
            shortcuts,
            "sign",
            "--mode",
            mode,
            "--input",
            str(source),
            "--output",
            str(output),
        ],
    )
    if completed.stdout:
        print(completed.stdout, end="", file=sys.stderr)
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


def _retry_binary(
    plutil: str,
    shortcuts: str,
    mode: str,
    source: Path,
    output: Path,
) -> int | None:
    if _run([plutil, "-lint", str(source)]).returncode != 0:
        return None
    output.unlink(missing_ok=True)
    print(
        "shortcuts-playground: Apple signing failed; retrying after binary plist conversion.",
        file=sys.stderr,
    )
    if _run([plutil, "-convert", "binary1", str(source)]).returncode != 0:
        return None
    return _sign(shortcuts, mode, source, output)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    source = args.input.expanduser().resolve()
    if not source.is_file():
        print(f"Input file not found: {source}", file=sys.stderr)
        return 2
    if args.output_dir is None:
        print(
            "Missing --output-dir (or SHORTCUTS_PLAYGROUND_OUTPUT_DIR); refusing an implicit write.",
            file=sys.stderr,
        )
        return 2
    if sys.platform != "darwin":
        print("Apple Shortcuts signing requires macOS.", file=sys.stderr)
        return 2

    shortcuts = shutil.which("shortcuts")
    if shortcuts is None:
        print("Apple shortcuts CLI not found on PATH.", file=sys.stderr)
        return 127

    name = args.name or source.stem
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        print(
            "Invalid --name: path separators and dot path segments are forbidden.",
            file=sys.stderr,
        )
        return 2

    output_dir = args.output_dir.expanduser().resolve()
    now = datetime.now().astimezone()
    archive_dir = output_dir / now.strftime("%Y-%m-%d")
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"{name}-{now:%H%M%S}.xml"
    signed = output_dir / f"{name}.shortcut"
    shutil.copyfile(source, archive)

    with tempfile.TemporaryDirectory(
        prefix=f"{name}-sign-",
        dir=output_dir,
    ) as temp_name:
        temp_dir = Path(temp_name)
        sign_input = temp_dir / f"{name}-sign-input.shortcut"
        sign_output = temp_dir / f"{name}-sign-output.shortcut"
        shutil.copyfile(source, sign_input)
        status = _sign(shortcuts, args.mode, sign_input, sign_output)
        if status != 0:
            shutil.copyfile(archive, sign_input)
            plutil = shutil.which("plutil")
            retried = (
                None
                if plutil is None
                else _retry_binary(
                    plutil,
                    shortcuts,
                    args.mode,
                    sign_input,
                    sign_output,
                )
            )
            if retried is not None:
                status = retried
        if status != 0:
            print(
                "shortcuts-playground: signing failed. If validation and plutil pass, retry outside "
                "workspace-write sandbox restrictions before treating the plist as malformed.",
                file=sys.stderr,
            )
            return status
        shutil.move(sign_output, signed)

    print(
        json.dumps({"archive": str(archive), "signed": str(signed), "mode": args.mode}),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
