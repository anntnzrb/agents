# Copyright (c) 2026
"""Check orchestration, cache freshness, status, and prompt rendering."""

import math
import re
import sys
from typing import TYPE_CHECKING

from .adapted import Parsed, ParseError, parse
from .config import fingerprint, labels, section
from .data import (
    GateResult,
    InputError,
    Manifest,
    Report,
    Table,
    Unit,
    canonical,
    digest,
    integer,
    read_facts,
    read_json,
    string,
    strings,
    table,
    write_json,
)
from .gates import DESCRIPTIONS, Context, book_gates, evaluate, metrics, result
from .text import plain

if TYPE_CHECKING:
    from pathlib import Path


class CheckError(RuntimeError):
    """A required check failed or source text is still pending."""


def warn_config(manifest: Manifest, config: Table) -> None:
    """Warn when checks use a different configuration than ingest."""
    if manifest["config_sha256"] != fingerprint(config):
        _ = sys.stderr.write("Warning: merged config differs from ingest config\n")


def unit_by_id(manifest: Manifest, uid: str) -> Unit:
    """Resolve a user-specified unit without allowing arbitrary paths."""
    for unit in manifest["units"]:
        if unit["id"] == uid:
            return unit
    raise InputError(f"Unknown unit: {uid}")


def cache_key(source: str, adapted: str | None, config: Table) -> str:
    """Hash delimited source, adapted content, and merged configuration."""
    return digest(canonical([source, adapted, config]))


def _cached(path: Path, key: str) -> Report | None:
    if not path.exists():
        return None
    raw = read_json(path)
    if raw.get("key") != key:
        return None
    entries = raw["gates"]
    if not isinstance(entries, list):
        raise InputError("Invalid check cache gates")
    gates: list[GateResult] = []
    for entry in entries:
        gate = table(entry)
        gates.append(
            GateResult(
                id=string(gate["id"]),
                category=string(gate["category"]),
                status=string(gate["status"]),
                message=string(gate["message"]),
                details=strings(gate["details"]),
            )
        )
    return Report(
        unit=string(raw["unit"]),
        key=key,
        status=string(raw["status"]),
        gates=gates,
        metrics=table(raw["metrics"]),
    )


def check_unit(work: Path, unit: Unit, lang: str, config: Table) -> Report:
    """Check one adapted unit or report it pending, using valid cached results."""
    uid = unit["id"]
    source = (work / unit["source"]).read_text(encoding="utf-8")
    adapted_path = work / "adapted" / f"{uid}.md"
    adapted = (
        adapted_path.read_text(encoding="utf-8") if adapted_path.exists() else None
    )
    key = cache_key(source, adapted, config)
    path = work / "checks" / f"{uid}.json"
    cached = _cached(path, key)
    if cached is not None:
        return cached
    report = Report(unit=uid, key=key, status="pending", gates=[], metrics={})
    if adapted is not None:
        try:
            parsed = parse(adapted)
        except ParseError as error:
            gate = result(
                "K-format",
                (False, str(error), []),
                section(section(config, "gates"), "K-format"),
            )
            # Format is an unconditional hard failure, even if configured as warn.
            gate["status"] = "fail"
            report.update(status="fail", gates=[gate])
        else:
            source_body = plain(source.partition("\n")[2])
            ctx = Context(
                parsed=parsed,
                source=source_body,
                facts=read_facts(work / "protected" / f"{uid}.json"),
                lang=lang,
                config=config,
            )
            gates = evaluate(ctx)
            report.update(
                status="fail"
                if any(gate["status"] == "fail" for gate in gates)
                else "pass",
                gates=gates,
                metrics=metrics(ctx),
            )
    write_json(path, report)
    return report


def check(
    work: Path,
    manifest: Manifest,
    config: Table,
    ids: list[str],
    *,
    all_units: bool = False,
) -> tuple[list[Report], list[GateResult]]:
    """Check requested units and optionally the book-level invariants."""
    warn_config(manifest, config)
    units = (
        [unit for unit in manifest["units"] if unit["kind"] == "body"]
        if all_units
        else [unit_by_id(manifest, uid) for uid in ids]
    )
    if not units and not all_units:
        raise InputError("Specify unit ids or --all")
    reports = [
        check_unit(work, unit, manifest["book"]["language"], config) for unit in units
    ]
    parsed: list[tuple[str, Parsed]] = []
    if all_units:
        for unit, report in zip(units, reports, strict=True):
            if report["status"] == "pending" or any(
                gate["id"] == "K-format" and gate["status"] == "fail"
                for gate in report["gates"]
            ):
                continue
            parsed.append(
                (
                    unit["id"],
                    parse(
                        (work / "adapted" / f"{unit['id']}.md").read_text(
                            encoding="utf-8"
                        )
                    ),
                )
            )
    return reports, book_gates(parsed, config) if all_units else []


def status(work: Path, manifest: Manifest, config: Table) -> Table:
    """Summarize unit progress using cache freshness rather than rerunning gates."""
    rows: list[Table] = []
    for unit in manifest["units"]:
        adapted_path = work / "adapted" / f"{unit['id']}.md"
        adapted = (
            adapted_path.read_text(encoding="utf-8") if adapted_path.exists() else None
        )
        source = (work / unit["source"]).read_text(encoding="utf-8")
        path = work / "checks" / f"{unit['id']}.json"
        cached = _cached(path, cache_key(source, adapted, config))
        last = (
            cached["status"]
            if cached
            else "stale"
            if path.exists() and adapted is not None
            else "pending"
        )
        rows.append(
            {
                "id": unit["id"],
                "kind": unit["kind"],
                "words": unit["words"],
                "adapted": adapted is not None,
                "check": last,
            }
        )
    body = [row for row in rows if row["kind"] == "body"]
    total_words = sum(integer(row["words"]) for row in body)
    return {
        "units": list(rows),
        "totals": {
            "body_units": len(body),
            "adapted": sum(bool(row["adapted"]) for row in body),
            "passing": sum(row["check"] == "pass" for row in body),
            "words": total_words,
            "minutes": math.ceil(
                total_words / integer(section(config, "build")["words_per_minute"])
            ),
        },
    }


def prompt(
    work: Path, manifest: Manifest, config: Table, uid: str, template_path: Path
) -> str:
    """Render a bundled template with an exact, closed placeholder vocabulary."""
    kind = template_path.stem
    unit = unit_by_id(manifest, uid)
    facts = read_facts(work / "protected" / f"{uid}.json")
    checklist = [
        f"{name}:\n" + "\n".join(f"- {item}" for item in items)
        if name == "Quotes"
        else f"{name}: " + ", ".join(items)
        for name, items in (
            ("Quotes", facts["quotes"]),
            ("Numbers", facts["numbers"]),
            ("Proper nouns", facts["proper_nouns"]),
            ("Hedges", [f"{term} x{count}" for term, count in facts["hedges"].items()]),
            ("Rare words", facts["rare_words"]),
        )
    ]
    if images := facts.get("images", []):
        checklist.append("Images: " + ", ".join(images))
    adapted_path = work / "adapted" / f"{uid}.md"
    if kind == "audit" and not adapted_path.exists():
        raise InputError(f"Audit requires adapted/{uid}.md")
    values = {
        "book_title": manifest["book"]["title"],
        "authors": ", ".join(manifest["book"]["authors"]),
        "language": manifest["book"]["language"],
        "unit_id": uid,
        "unit_title": unit["title"],
        "source": (work / unit["source"]).read_text(encoding="utf-8"),
        "protected": "\n\n".join(checklist),
        "voice": _voice(config),
        "thresholds": _thresholds(config),
        "labels": canonical(labels(config, manifest["book"]["language"])).strip(),
        "adapted": adapted_path.read_text(encoding="utf-8")
        if adapted_path.exists()
        else "",
    }
    template = template_path.read_text(encoding="utf-8")

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name not in values:
            raise InputError(f"Unknown template placeholder: {name}")
        return values[name]

    return re.sub(r"\{\{([^{}]+)\}\}", substitute, template)


def _voice(config: Table) -> str:
    preferences = section(config, "voice")
    bullets = [
        f"- {label}: "
        + (", ".join(strings(value)) if isinstance(value, list) else string(value))
        for key, label in (
            ("style", "Style"),
            ("code_switch", "Code-switching"),
            ("slang", "Slang"),
            ("analogy_domains", "Analogy domains"),
            ("banned", "Banned terms"),
            ("aside_examples", "Sample asides"),
        )
        if (value := preferences[key])
    ]
    return "\n".join(bullets) if bullets else "- (no extra voice preferences)"


def _thresholds(config: Table) -> str:
    lines: list[str] = []
    for gid, value in section(config, "gates").items():
        settings = table(value)
        if not settings["enabled"]:
            continue
        parameters = ", ".join(
            f"{key}={parameter}"
            for key, parameter in settings.items()
            if key not in ("enabled", "severity")
        )
        lines.append(
            f"- {gid} ({settings['severity']}): {DESCRIPTIONS[gid]}"
            + (f"; {parameters}" if parameters else "")
        )
    return "\n".join(lines)
