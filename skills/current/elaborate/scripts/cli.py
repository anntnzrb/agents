# Copyright (c) 2026
# /// script
# requires-python = ">=3.14"
# dependencies = ["wordfreq>=3.1.1", "regex"]
# ///
"""Command-line entrypoint for deterministic elaborated editions."""

import argparse
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typing import TYPE_CHECKING

from lib.elaborate.build import MissingExecutableError, build, validate_epub
from lib.elaborate.config import load_config
from lib.elaborate.data import (
    GateResult,
    InputError,
    Report,
    Table,
    canonical,
    read_manifest,
    table,
)
from lib.elaborate.ingest import ingest
from lib.elaborate.work import CheckError, check, prompt, status

if TYPE_CHECKING:
    from collections.abc import Sequence


class Arguments(argparse.Namespace):
    """Typed command-specific argparse attributes."""

    command: str = ""
    work: Path = Path()
    config: Path | None = None
    json: bool = False
    book: Path = Path()
    ids: tuple[str, ...] = ()
    all: bool = False
    unit: str = ""
    kind: str = ""
    out: Path = Path()
    allow_pending: bool = False
    epubcheck: bool = False


def build_parser() -> argparse.ArgumentParser:
    """Create the public command grammar."""
    parser = argparse.ArgumentParser(prog="elaborate", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("ingest", "Extract EPUB units and protected facts"),
        ("check", "Check adapted units against measurable gates"),
        ("status", "Show adaptation progress and cache freshness"),
        ("prompt", "Render a rewrite or audit brief"),
        ("build", "Build a checked deterministic EPUB3"),
    ):
        command = commands.add_parser(name, help=help_text)
        _ = command.add_argument(
            "--work", type=Path, required=True, help="Work directory"
        )
        _ = command.add_argument(
            "--config", type=Path, help="TOML override (else ELABORATE_CONFIG)"
        )
        _ = command.add_argument(
            "--json", action="store_true", help="Print machine output"
        )
        if name == "ingest":
            _ = command.add_argument("book", type=Path, help="Source EPUB")
        elif name == "check":
            _ = command.add_argument("ids", nargs="*", help="Unit ids")
            _ = command.add_argument(
                "--all", action="store_true", help="Every body unit plus book gates"
            )
        elif name == "prompt":
            _ = command.add_argument("unit", help="Unit id")
            _ = command.add_argument(
                "--kind", choices=("rewrite", "audit"), required=True
            )
        elif name == "build":
            _ = command.add_argument(
                "--out", type=Path, required=True, help="Output EPUB"
            )
            _ = command.add_argument(
                "--allow-pending",
                action="store_true",
                help="Use visibly labeled source text for pending units",
            )
            _ = command.add_argument(
                "--epubcheck",
                action="store_true",
                help="Run external epubcheck after building",
            )
    return parser


def _gate_lines(gates: list[GateResult]) -> list[str]:
    lines: list[str] = []
    for gate in gates:
        if gate["status"] in ("fail", "warn"):
            lines.append(f"  {gate['id']} {gate['status']}: {gate['message']}")
            lines.extend(f"    {detail}" for detail in gate["details"][:10])
    return lines


def _report_lines(reports: list[Report], book: list[GateResult]) -> str:
    lines: list[str] = []
    for report in reports:
        failures = ", ".join(
            gate["id"] for gate in report["gates"] if gate["status"] == "fail"
        )
        lines.append(
            f"{report['unit']} {report['status']}"
            + (f" {failures}" if failures else "")
        )
        lines.extend(_gate_lines(report["gates"]))
    lines.extend(_gate_lines(book))
    return "\n".join(lines) + "\n"


def _status_lines(payload: Table) -> str:
    rows = payload["units"]
    if not isinstance(rows, list):
        raise InputError("Invalid status rows")
    lines = ["id   kind    words  adapted  check"]
    for value in rows:
        row = table(value)
        done = "yes" if row["adapted"] else "no"
        lines.append(
            f"{row['id']}\t{row['kind']}\t{row['words']}\t{done}\t{row['check']}"
        )
    totals = table(payload["totals"])
    lines.append(
        "Totals: " + ", ".join(f"{key}={value}" for key, value in totals.items())
    )
    return "\n".join(lines) + "\n"


def _execute(args: Arguments) -> int:
    config = load_config(args.config)
    if args.command == "ingest":
        manifest = ingest(args.book, args.work, config)
        output = (
            canonical(manifest)
            if args.json
            else "\n".join(
                f"{unit['id']} {unit['kind']} {unit['words']} {unit['title']}"
                for unit in manifest["units"]
            )
            + "\n"
        )
        _ = sys.stdout.write(output)
        return 0
    manifest = read_manifest(args.work)
    if args.command == "check":
        reports, book = check(
            args.work, manifest, config, list(args.ids), all_units=args.all
        )
        _ = sys.stdout.write(
            canonical({"units": reports, "book_gates": book})
            if args.json
            else _report_lines(reports, book)
        )
        return int(
            any(report["status"] == "fail" for report in reports)
            or any(gate["status"] == "fail" for gate in book)
        )
    if args.command == "status":
        payload = status(args.work, manifest, config)
        _ = sys.stdout.write(
            canonical(payload) if args.json else _status_lines(payload)
        )
    elif args.command == "prompt":
        rendered = prompt(
            args.work,
            manifest,
            config,
            args.unit,
            Path(__file__).resolve().parents[1]
            / "references"
            / "prompts"
            / f"{args.kind}.md",
        )
        _ = sys.stdout.write(canonical({"prompt": rendered}) if args.json else rendered)
    elif args.command == "build":
        build(
            args.work,
            manifest,
            config,
            args.out,
            allow_pending=args.allow_pending,
        )
        if args.epubcheck:
            validate_epub(args.out)
        _ = sys.stdout.write(
            canonical({"out": str(args.out), "status": "pass"})
            if args.json
            else f"Built {args.out}\n"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Execute a command and map expected failures to public exit codes."""
    args = build_parser().parse_args(argv, namespace=Arguments())
    try:
        return _execute(args)
    except MissingExecutableError as error:
        _ = sys.stderr.write(f"Error: {error}\n")
        return 127
    except (InputError, FileNotFoundError, tomllib.TOMLDecodeError, KeyError) as error:
        _ = sys.stderr.write(f"Error: {error}\n")
        return 2
    except (CheckError, OSError, RuntimeError) as error:
        _ = sys.stderr.write(f"Error: {error}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
