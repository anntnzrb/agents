#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Valorant meta CLI: live agent, patch, and map stats parsed from valking.gg.

Nothing is embedded in this skill; every answer is fetched fresh at runtime.
Sources are JS-rendered Next.js pages, so fetching goes through the sibling
firecrawl skill CLI (scrape -> markdown) and parsing works on the markdown.

Breakage detection is the point: parsers are strict, every parse is shape
fingerprinted, and a state file tracks per-source health. When a source breaks
or drifts, commands fail with explicit JSON errors or warnings instead of
emitting garbage.

Test injection: when VALORANT_META_FIXTURE_DIR is set, the fetch layer reads
<fixture_dir>/<source_key>.md instead of subprocessing firecrawl.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeIs

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

_json_loads: Callable[[str | bytes | bytearray], object] = json.loads

type JsonValue = (
    dict[str, JsonValue] | Sequence[JsonValue] | str | int | float | bool | None
)

FETCH_TIMEOUT = 240
SEARCH_TIMEOUT = 180
MIN_AGENT_ROWS = 10
ROW_CELLS = 7
ABUSE_WR = 51.0
ABUSE_PR = 8.0
AVOID_COUNT = 3
MOVERS_COUNT = 3
TAGS = ("NEUTRAL", "REWORK", "BUFF", "NERF", "NEW")
DISCOVER_QUERY = "valorant agent win rates pick rates stats site"

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
PATCH_VERSION_RE = re.compile(r"Patch (\d+\.\d+[a-z]?)")
CARD_RE = re.compile(rf"\[Patch (\d+\.\d+[a-z]?)((?:{MONTHS}) \d{{1,2}}, \d{{4}})")
CARD_URL_RE = re.compile(r"\]\((https://valking\.gg/en/patches/[^\s\")]+)")
CHANGE_RE = re.compile(r"^(NEUTRAL|REWORK|BUFF|NERF|NEW)(\S.*?)\s*\\-\s*(.+)$")
COUNTS_LINE_RE = re.compile(r"^(?:\d+\s*(?:NEUTRAL|REWORK|BUFF|NERF|NEW))+\s*$")
COUNT_RE = re.compile(r"(\d+)\s*(NEUTRAL|REWORK|BUFF|NERF|NEW)")
RELEASED_RE = re.compile(r"Released ([A-Z][a-z]+ \d{1,2}, \d{4})")
OFFICIAL_RE = re.compile(r"\((https://playvalorant\.com[^\s)]+)\)")
MOVER_PATTERN = (
    r"\[!\[[^\]]*\]\([^)]*\)([A-Za-z0-9/]+)([+-][\d.]+)%([\d.]+)%"
    r"\s*win\s*·\s*([\d.]+)%\s*pick\]"
)
MOVER_RE = re.compile(MOVER_PATTERN)
SPLASH_RE = re.compile(
    r"^!\[\]\(https://api\.valking\.gg/images/maps/([a-z0-9-]+)/splash\.webp\)",
    re.MULTILINE,
)
MAP_SIDES_RE = re.compile(r"^Attack\n\n([\d.]+)%\n\nDefense\n\n([\d.]+)%", re.MULTILINE)
MAP_NAME_RE = re.compile(r"^[A-Z][A-Za-z]+$")
STAT_RE = re.compile(r"^(\d+(?:\.\d+)?)%(.*)$")


class _FetchError(Exception):
    """A fetch-layer failure carrying its stable error code."""

    code: str
    message: str

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _ParseError(Exception):
    """A strict-parse failure; always means source shape breakage."""


@dataclass(frozen=True, slots=True)
class AgentRow:
    """One row of the agents tier-list table."""

    rank: int
    name: str
    role: str
    winrate: float
    wr_delta_7d: float
    pickrate: float
    pr_delta_7d: float
    kda: float
    tier: str


@dataclass(frozen=True, slots=True)
class AgentsResult:
    """Parsed agents page: patch version, rows, shape fingerprint."""

    patch: str | None
    agents: list[AgentRow]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class PatchChange:
    """One tagged change line of a patch card."""

    tag: str
    target: str
    text: str


@dataclass(frozen=True, slots=True)
class PatchCard:
    """One patch card of the patches index."""

    version: str
    date: str
    url: str
    changes: list[PatchChange]


@dataclass(frozen=True, slots=True)
class PatchesResult:
    """Parsed patches index: cards newest-first, shape fingerprint."""

    cards: list[PatchCard]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class Mover:
    """One biggest-mover entry of a patch detail page."""

    name: str
    delta: float
    winrate: float
    pickrate: float
    direction: str


@dataclass(frozen=True, slots=True)
class PatchDetail:
    """Best-effort parse of a patch detail page."""

    version: str | None
    release_date: str | None
    official_url: str | None
    counts: dict[str, int]
    movers: list[Mover]


@dataclass(frozen=True, slots=True)
class MapEntry:
    """One map section of the maps page."""

    name: str
    slug: str
    attack: float
    defense: float


@dataclass(frozen=True, slots=True)
class MapsResult:
    """Parsed maps page: patch version, map sections, shape fingerprint."""

    patch: str | None
    maps: list[MapEntry]
    fingerprint: str


type ParseResult = AgentsResult | PatchesResult | MapsResult


@dataclass(frozen=True, slots=True)
class Probe:
    """Outcome of one fetch+parse probe against a registry source."""

    key: str
    ok: bool
    latency_ms: int
    result: ParseResult | None
    error_code: str | None
    error_message: str | None


class _Args(argparse.Namespace):
    """Parsed command-line arguments."""

    command: str = ""
    query: str = DISCOVER_QUERY
    max_results: int = 10


def emit(payload: object) -> None:
    """Write exactly one JSON object to stdout."""
    _ = sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")


def fail(code: str, message: str, **details: object) -> SystemExit:
    """Emit a stable JSON error object and return SystemExit for raising."""
    emit(
        {
            "ok": False,
            "error": {"code": code, "message": message, "details": details},
        }
    )
    return SystemExit(1)


def utc_now() -> str:
    """Return the current UTC time in ISO 8601 Z form, second precision."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_dict(value: object) -> TypeIs[dict[str, JsonValue]]:
    return isinstance(value, dict)


def _as_dict(value: JsonValue) -> dict[str, JsonValue]:
    """Return the value when it is a JSON object, else an empty object."""
    return value if isinstance(value, dict) else {}


def _opt_str(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def shape_fingerprint(keys: Iterable[str], count: int) -> str:
    """Hash sorted structural keys plus the row-count bucket, hex-truncated."""
    low = (count // 10) * 10
    material = "|".join(sorted(keys)) + f"#rows{low}-{low + 9}"
    return hashlib.sha256(material.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- state file


def state_path() -> Path:
    """Return the XDG state file path for the maintenance tracker."""
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "valorant-meta" / "state.json"


def load_state() -> dict[str, JsonValue]:
    """Load the tracker state; corrupt or missing state is a fresh start."""
    path = state_path()
    if not path.is_file():
        return {"sources": {}}
    try:
        value = _json_loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return {"sources": {}}
    if not _is_dict(value) or not isinstance(value.get("sources"), dict):
        return {"sources": {}}
    return value


def save_state(state: dict[str, JsonValue]) -> None:
    """Write the tracker state atomically (tmp file plus rename)."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            _ = handle.write(json.dumps(state, indent=2) + "\n")
        _ = Path(tmp).replace(path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


def source_state(state: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
    """Return the mutable per-source state entry, creating it when absent."""
    sources = _as_dict(state.get("sources") or {})
    state["sources"] = sources
    entry = sources.get(key)
    if not isinstance(entry, dict):
        entry = {}
        sources[key] = entry
    return entry


def record_probe(state: dict[str, JsonValue], probe: Probe) -> None:
    """Apply one probe outcome to the tracker state."""
    entry = source_state(state, probe.key)
    entry["last_fetch_at"] = utc_now()
    if probe.ok and probe.result is not None:
        entry["last_success_at"] = utc_now()
        entry["fingerprint"] = probe.result.fingerprint
        entry["consecutive_failures"] = 0
    else:
        previous = entry.get("consecutive_failures")
        streak = previous if isinstance(previous, int) else 0
        entry["consecutive_failures"] = streak + 1


def baseline_fingerprints(state: dict[str, JsonValue]) -> dict[str, str]:
    """Snapshot the stored per-source fingerprints before any update."""
    baselines: dict[str, str] = {}
    sources = _as_dict(state.get("sources") or {})
    for key, raw in sources.items():
        if not isinstance(raw, dict):
            continue
        fingerprint = raw.get("fingerprint")
        if isinstance(fingerprint, str):
            baselines[key] = fingerprint
    return baselines


# ------------------------------------------------------------- fetch layer


def resolve_sibling(tool: str) -> Path:
    """Resolve a sibling skill CLI path or fail naming the env override."""
    env_name = f"VALORANT_META_{tool.upper()}_CLI"
    override = os.environ.get(env_name)
    if override:
        candidate = Path(override)
    else:
        candidate = (
            Path(__file__).resolve().parents[1].parent / tool / "scripts" / "cli.py"
        )
    if not candidate.is_file():
        raise _FetchError(
            "MISSING_DEPENDENCY",
            (
                f"sibling skill CLI not found: {candidate}; install the {tool}"
                f" skill beside this one or set {env_name} to its cli.py path"
            ),
        )
    return candidate


def run_sibling(cli: Path, argv: list[str], timeout: int) -> str:
    """Run a sibling skill CLI through uv and return its stdout."""
    uv = shutil.which("uv") or "uv"
    try:
        completed = subprocess.run(
            [uv, "run", "--script", str(cli), *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _FetchError(
            "FETCH_FAILED", f"sibling CLI timed out after {timeout}s: {cli}"
        ) from exc
    except OSError as exc:
        raise _FetchError("FETCH_FAILED", f"cannot run sibling CLI: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()[:300] or completed.stdout.strip()[:300]
        raise _FetchError(
            "FETCH_FAILED",
            f"sibling CLI exited {completed.returncode}: {detail}",
        )
    return completed.stdout


def fetch_markdown(key: str, url: str) -> str:
    """Fetch one source as markdown, or read its fixture in test injection."""
    fixture_dir = os.environ.get("VALORANT_META_FIXTURE_DIR")
    if fixture_dir:
        path = Path(fixture_dir) / f"{key}.md"
        if not path.is_file():
            raise _FetchError(
                "FIXTURE_MISSING",
                f"fixture injection active but {path} does not exist",
            )
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise _FetchError("FIXTURE_MISSING", f"cannot read {path}: {exc}") from exc
    cli = resolve_sibling("firecrawl")
    return run_sibling(cli, ["scrape", url], FETCH_TIMEOUT)


# ------------------------------------------------------------------ parsers


def split_cells(line: str) -> list[str]:
    """Split a markdown table row into stripped cells."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_stat(cell: str) -> tuple[float, float]:
    """Parse a `52.9%+1.2` style cell into value and signed 7-day delta."""
    match = STAT_RE.match(cell.strip())
    if match is None:
        raise _ParseError(f"malformed stat cell: {cell!r}")
    value = float(match.group(1))
    rest = match.group(2).strip()
    if not rest:
        raise _ParseError(f"stat cell misses its 7-day delta: {cell!r}")
    try:
        delta = float(rest[3:]) if rest.startswith("+/-") else float(rest)
    except ValueError as exc:
        raise _ParseError(f"malformed delta in stat cell: {cell!r}") from exc
    return value, delta


def agent_display_name(cell: str) -> str:
    """Extract the display name after the last <br> before `](` of a row cell.

    The image alt text and the display name can differ in case (`KillJoy` vs
    `Killjoy`); the display name after the final `<br>` is authoritative.
    """
    if "/en/agents/" not in cell:
        raise _ParseError(f"agent cell carries no agent link: {cell[:80]!r}")
    anchor = cell.rfind("<br>")
    if anchor == -1:
        raise _ParseError(f"agent cell carries no <br> name anchor: {cell[:80]!r}")
    after = cell[anchor + len("<br>") :]
    end = after.find("](")
    if end == -1:
        raise _ParseError(f"agent cell display name unterminated: {cell[:80]!r}")
    name = after[:end].strip()
    if not name:
        raise _ParseError(f"agent cell display name empty: {cell[:80]!r}")
    return name


def role_text(cell: str) -> str:
    """Extract the role text trailing the role image of a row cell."""
    close = cell.rfind(")")
    role = cell[close + 1 :].strip() if close != -1 else ""
    if not role:
        raise _ParseError(f"role cell carries no role text: {cell[:80]!r}")
    return role


def parse_agent_row(cells: list[str]) -> AgentRow:
    """Parse one data row of the agents table, strictly."""
    if len(cells) < ROW_CELLS or not cells[0].isdigit():
        raise _ParseError(f"malformed table row: {cells!r}")
    winrate, wr_delta = parse_stat(cells[3])
    pickrate, pr_delta = parse_stat(cells[4])
    try:
        kda = float(cells[5])
    except ValueError as exc:
        raise _ParseError(f"malformed KDA cell: {cells[5]!r}") from exc
    tier = cells[6]
    if len(tier) != 1 or not tier.isupper():
        raise _ParseError(f"malformed tier cell: {tier!r}")
    return AgentRow(
        rank=int(cells[0]),
        name=agent_display_name(cells[1]),
        role=role_text(cells[2]),
        winrate=winrate,
        wr_delta_7d=wr_delta,
        pickrate=pickrate,
        pr_delta_7d=pr_delta,
        kda=kda,
        tier=tier,
    )


def find_table_header(lines: list[str]) -> tuple[int, list[str]]:
    """Locate the tier-list table header row and return its index and cells."""
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = split_cells(line)
        if "Agent" in cells and "Win Rate" in cells:
            return index, cells
    raise _ParseError("agents table header row not found")


def scan_table_rows(lines: list[str]) -> list[AgentRow]:
    """Parse the data rows following the table header until the table ends."""
    rows: list[AgentRow] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = split_cells(line)
        if cells and all(set(cell) <= {"-", " "} for cell in cells if cell):
            continue
        if cells and cells[0].isdigit():
            rows.append(parse_agent_row(cells))
        elif rows:
            break
    return rows


def parse_agents_table(md: str) -> AgentsResult:
    """Parse the agents tier-list markdown table, strictly, or fail."""
    lines = md.splitlines()
    header_index, headers = find_table_header(lines)
    rows = scan_table_rows(lines[header_index + 1 :])
    if len(rows) < MIN_AGENT_ROWS:
        message = (
            f"agents table parsed {len(rows)} rows, expected at least"
            f" {MIN_AGENT_ROWS}; source shape likely changed"
        )
        raise _ParseError(message)
    patch_match = PATCH_VERSION_RE.search(md)
    keys = [cell for cell in headers if cell and cell != "#"]
    return AgentsResult(
        patch=patch_match.group(1) if patch_match else None,
        agents=rows,
        fingerprint=shape_fingerprint(keys, len(rows)),
    )


def parse_change_line(line: str) -> PatchChange | None:
    """Parse one tag-glued change line, or return None for non-change lines."""
    match = CHANGE_RE.match(line.strip())
    if match is None:
        return None
    return PatchChange(tag=match.group(1), target=match.group(2), text=match.group(3))


def parse_patches(md: str) -> PatchesResult:
    """Parse the patches index into cards newest-first, strictly, or fail."""
    matches = list(CARD_RE.finditer(md))
    if not matches:
        raise _ParseError("no patch cards found in patches index")
    cards: list[PatchCard] = []
    boundaries = [m.start() for m in matches] + [len(md)]
    for index, match in enumerate(matches):
        region = md[match.start() : boundaries[index + 1]]
        url_match = CARD_URL_RE.search(region)
        if url_match is None:
            raise _ParseError(f"patch card {match.group(1)} carries no detail URL")
        changes = [
            change
            for line in region.splitlines()
            if (change := parse_change_line(line)) is not None
        ]
        cards.append(
            PatchCard(
                version=match.group(1),
                date=match.group(2),
                url=url_match.group(1),
                changes=changes,
            )
        )
    if not cards[0].changes:
        message = (
            f"latest patch card {cards[0].version} parsed zero changes;"
            " source shape likely changed"
        )
        raise _ParseError(message)
    keys = [
        "patch-card",
        "detail-url",
        *sorted({change.tag for card in cards for change in card.changes}),
    ]
    return PatchesResult(cards=cards, fingerprint=shape_fingerprint(keys, len(cards)))


def parse_counts(md: str) -> dict[str, int]:
    """Extract the change-count blob of a patch detail page."""
    counts: dict[str, int] = dict.fromkeys(TAGS, 0)
    for line in md.splitlines():
        if COUNTS_LINE_RE.match(line.strip()):
            for match in COUNT_RE.finditer(line):
                counts[match.group(2)] = int(match.group(1))
            return counts
    return counts


def parse_movers(md: str) -> list[Mover]:
    """Extract the biggest-mover entries with their climbing/falling section."""
    movers: list[Mover] = []
    direction = ""
    for line in md.splitlines():
        if line.strip().startswith("▲"):
            direction = "climbing"
        elif line.strip().startswith("▼"):
            direction = "falling"
        for match in MOVER_RE.finditer(line):
            movers.append(
                Mover(
                    name=match.group(1),
                    delta=float(match.group(2)),
                    winrate=float(match.group(3)),
                    pickrate=float(match.group(4)),
                    direction=direction,
                )
            )
    return movers


def parse_patch_detail(md: str) -> PatchDetail:
    """Best-effort parse of a patch detail page; missing pieces stay null."""
    version = None
    title = re.search(r"^# Valorant Patch (\d+\.\d+[a-z]?)", md, re.MULTILINE)
    if title:
        version = title.group(1)
    released = RELEASED_RE.search(md)
    official = OFFICIAL_RE.search(md)
    return PatchDetail(
        version=version,
        release_date=released.group(1) if released else None,
        official_url=official.group(1) if official else None,
        counts=parse_counts(md),
        movers=parse_movers(md),
    )


def parse_map_region(slug: str, region: str) -> MapEntry:
    """Parse one map section region, strictly."""
    name = None
    for line in region.splitlines()[1:13]:
        if MAP_NAME_RE.match(line.strip()):
            name = line.strip()
            break
    if name is None:
        raise _ParseError(f"map section {slug} carries no standalone name line")
    sides = MAP_SIDES_RE.search(region)
    if sides is None:
        raise _ParseError(f"map section {slug} carries no Attack/Defense block")
    return MapEntry(
        name=name,
        slug=slug,
        attack=float(sides.group(1)),
        defense=float(sides.group(2)),
    )


def parse_maps(md: str) -> MapsResult:
    """Parse the maps page sections, strictly, or fail."""
    matches = list(SPLASH_RE.finditer(md))
    if not matches:
        raise _ParseError("no map splash sections found in maps page")
    boundaries = [m.start() for m in matches] + [len(md)]
    entries = [
        parse_map_region(match.group(1), md[match.start() : boundaries[index + 1]])
        for index, match in enumerate(matches)
    ]
    patch_match = PATCH_VERSION_RE.search(md)
    keys = ["attack", "defense", "name", "splash"]
    return MapsResult(
        patch=patch_match.group(1) if patch_match else None,
        maps=entries,
        fingerprint=shape_fingerprint(keys, len(entries)),
    )


PARSERS: dict[str, Callable[[str], ParseResult]] = {
    "parse_agents_table": parse_agents_table,
    "parse_patches": parse_patches,
    "parse_maps": parse_maps,
}


# ------------------------------------------------------------ probe+registry


def load_registry() -> dict[str, dict[str, str]]:
    """Load and validate the source registry beside the skill."""
    path = Path(__file__).resolve().parents[1] / "sources.json"
    try:
        value = _json_loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise fail("REGISTRY_ERROR", f"cannot read {path}: {exc}") from exc
    if not _is_dict(value) or not _is_dict(value.get("sources")):
        raise fail("REGISTRY_ERROR", f"{path} lacks a sources object")
    registry: dict[str, dict[str, str]] = {}
    sources = value["sources"]
    assert isinstance(sources, dict)
    for key, raw in sources.items():
        entry = _as_dict(raw)
        url = _opt_str(entry.get("url") or "")
        parser = _opt_str(entry.get("parser") or "")
        if not url or parser not in PARSERS:
            raise fail(
                "REGISTRY_ERROR",
                f"registry entry {key!r} lacks a url or names an unknown parser",
            )
        registry[key] = {
            "name": _opt_str(entry.get("name") or "") or key,
            "url": url,
            "parser": parser,
            "description": _opt_str(entry.get("description") or "") or "",
        }
    return registry


def probe_source(key: str, entry: dict[str, str]) -> Probe:
    """Fetch and parse one registry source; never raises for fetch/parse."""
    start = time.monotonic()
    try:
        markdown = fetch_markdown(key, entry["url"])
        result = PARSERS[entry["parser"]](markdown)
    except _FetchError as exc:
        latency = int((time.monotonic() - start) * 1000)
        return Probe(
            key,
            ok=False,
            latency_ms=latency,
            result=None,
            error_code=exc.code,
            error_message=exc.message,
        )
    except _ParseError as exc:
        latency = int((time.monotonic() - start) * 1000)
        return Probe(
            key,
            ok=False,
            latency_ms=latency,
            result=None,
            error_code="PARSE_FAILED",
            error_message=str(exc),
        )
    latency = int((time.monotonic() - start) * 1000)
    return Probe(
        key,
        ok=True,
        latency_ms=latency,
        result=result,
        error_code=None,
        error_message=None,
    )


def probe_or_fail(
    key: str, entry: dict[str, str], state: dict[str, JsonValue]
) -> tuple[Probe, str | None]:
    """Probe one source, record it, and fail hard when the probe fails.

    Returns the probe and a drift warning when the shape fingerprint moved
    away from the stored baseline.
    """
    baselines = baseline_fingerprints(state)
    probe = probe_source(key, entry)
    record_probe(state, probe)
    save_state(state)
    if not probe.ok:
        raise fail(
            probe.error_code or "FETCH_FAILED",
            probe.error_message or f"{key} probe failed",
            source=key,
        )
    warning = None
    baseline = baselines.get(key)
    if (
        probe.result is not None
        and baseline is not None
        and baseline != probe.result.fingerprint
    ):
        warning = (
            f"shape drift on {key}: fingerprint {baseline} became"
            f" {probe.result.fingerprint}; verify parser output before trusting"
        )
    return probe, warning


# ---------------------------------------------------------- json projections


def agent_json(row: AgentRow) -> dict[str, JsonValue]:
    """Project one agent row into its stable output fields."""
    return {
        "rank": row.rank,
        "name": row.name,
        "role": row.role,
        "winrate": row.winrate,
        "wr_delta_7d": row.wr_delta_7d,
        "pickrate": row.pickrate,
        "pr_delta_7d": row.pr_delta_7d,
        "kda": row.kda,
        "tier": row.tier,
    }


def change_json(change: PatchChange) -> dict[str, JsonValue]:
    """Project one patch change into its stable output fields."""
    return {"tag": change.tag, "target": change.target, "text": change.text}


def mover_json(mover: Mover) -> dict[str, JsonValue]:
    """Project one mover into its stable output fields."""
    return {
        "name": mover.name,
        "delta": mover.delta,
        "winrate": mover.winrate,
        "pickrate": mover.pickrate,
        "direction": mover.direction,
    }


def detail_json(detail: PatchDetail) -> dict[str, JsonValue]:
    """Project a patch detail parse into its stable output fields."""
    return {
        "version": detail.version,
        "release_date": detail.release_date,
        "official_url": detail.official_url,
        "counts": {tag: detail.counts[tag] for tag in TAGS},
        "movers": [mover_json(mover) for mover in detail.movers],
    }


def map_json(entry: MapEntry) -> dict[str, JsonValue]:
    """Project one map entry into its stable output fields."""
    return {
        "name": entry.name,
        "slug": entry.slug,
        "attack": entry.attack,
        "defense": entry.defense,
    }


# ----------------------------------------------------------------- commands


def cmd_agents(_args: _Args) -> None:
    """Parse the agents tier list: rank, stats, deltas, tier per agent."""
    registry = load_registry()
    state = load_state()
    probe, warning = probe_or_fail("agents", registry["agents"], state)
    assert isinstance(probe.result, AgentsResult)
    result = probe.result
    payload: dict[str, JsonValue] = {
        "ok": True,
        "fetched_at": utc_now(),
        "patch": result.patch,
        "fingerprint": result.fingerprint,
        "agents": [agent_json(row) for row in result.agents],
    }
    if warning:
        payload["warnings"] = [warning]
    emit(payload)


def fetch_patch_detail(url: str) -> PatchDetail | None:
    """Fetch and best-effort parse a patch detail page; None when broken."""
    try:
        markdown = fetch_markdown("patch-detail", url)
    except _FetchError:
        return None
    return parse_patch_detail(markdown)


def cmd_patch(_args: _Args) -> None:
    """Latest patch highlights: tagged changes plus detail-page context."""
    registry = load_registry()
    state = load_state()
    probe, warning = probe_or_fail("patches", registry["patches"], state)
    assert isinstance(probe.result, PatchesResult)
    latest = probe.result.cards[0]
    warnings = [warning] if warning else []
    detail = fetch_patch_detail(latest.url)
    if detail is None:
        warnings.append("patch detail page unavailable; index data only")
    payload: dict[str, JsonValue] = {
        "ok": True,
        "fetched_at": utc_now(),
        "patch": latest.version,
        "version": latest.version,
        "release_date": latest.date,
        "url": latest.url,
        "changes": [change_json(change) for change in latest.changes],
        "detail": detail_json(detail) if detail is not None else None,
    }
    if warnings:
        payload["warnings"] = warnings
    emit(payload)


def cmd_maps(_args: _Args) -> None:
    """Per-map attack/defense round win percentages."""
    registry = load_registry()
    state = load_state()
    probe, warning = probe_or_fail("maps", registry["maps"], state)
    assert isinstance(probe.result, MapsResult)
    result = probe.result
    payload: dict[str, JsonValue] = {
        "ok": True,
        "fetched_at": utc_now(),
        "patch": result.patch,
        "fingerprint": result.fingerprint,
        "maps": [map_json(entry) for entry in result.maps],
        "note": (
            "the maps page renders one map at a time and the competitive pool"
            " rotates; a capture can carry a subset of the pool or a map that"
            " is rotating out, so treat coverage as uncertain"
        ),
    }
    if warning:
        payload["warnings"] = [warning]
    emit(payload)


def derive_abuse(agents: list[AgentRow]) -> dict[str, JsonValue]:
    """Split high-winrate agents into meta-abuse and niche-pick buckets."""
    meta = [
        agent_json(row)
        for row in agents
        if row.winrate >= ABUSE_WR and row.pickrate >= ABUSE_PR
    ]
    niche = [
        agent_json(row)
        for row in agents
        if row.winrate >= ABUSE_WR and row.pickrate < ABUSE_PR
    ]
    return {"meta": meta, "niche": niche}


def derive_movers(agents: list[AgentRow]) -> dict[str, JsonValue]:
    """Pick the biggest 7-day win-rate risers and fallers."""
    ordered = sorted(agents, key=lambda row: row.wr_delta_7d, reverse=True)
    risers = [agent_json(row) for row in ordered[:MOVERS_COUNT]]
    fallers = [
        agent_json(row) for row in reversed(ordered[len(ordered) - MOVERS_COUNT :])
    ]
    return {"risers": risers, "fallers": fallers}


def snapshot_patch_context(patches_probe: Probe, warnings: list[str]) -> JsonValue:
    """Build the patch context section, or None with an explicit warning."""
    if not patches_probe.ok or not isinstance(patches_probe.result, PatchesResult):
        warning = (
            f"patch source unavailable: {patches_probe.error_message};"
            " patch context omitted"
        )
        warnings.append(warning)
        return None
    latest = patches_probe.result.cards[0]
    detail = fetch_patch_detail(latest.url)
    if detail is None:
        warnings.append("patch detail page unavailable; index data only")
    return {
        "version": latest.version,
        "release_date": latest.date,
        "url": latest.url,
        "changes": [change_json(change) for change in latest.changes],
        "detail": detail_json(detail) if detail is not None else None,
    }


def snapshot_maps_section(maps_probe: Probe, warnings: list[str]) -> JsonValue:
    """Build the maps section, or None with an explicit warning."""
    if not maps_probe.ok or not isinstance(maps_probe.result, MapsResult):
        warnings.append(
            f"maps source unavailable: {maps_probe.error_message}; maps section omitted"
        )
        return None
    return {
        "maps": [map_json(entry) for entry in maps_probe.result.maps],
        "note": (
            "the maps page renders one map at a time and the competitive pool"
            " rotates; coverage is uncertain"
        ),
    }


def cmd_snapshot(_args: _Args) -> None:
    """Build the composed answer: abuse, avoid, movers, and patch context."""
    registry = load_registry()
    state = load_state()
    keys = ("agents", "patches", "maps")
    baselines = baseline_fingerprints(state)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(keys)) as pool:
        futures = {key: pool.submit(probe_source, key, registry[key]) for key in keys}
        probes = {key: future.result() for key, future in futures.items()}
    for probe in probes.values():
        record_probe(state, probe)
    save_state(state)
    warnings: list[str] = []
    for key, probe in probes.items():
        baseline = baselines.get(key)
        if (
            probe.ok
            and probe.result is not None
            and baseline is not None
            and baseline != probe.result.fingerprint
        ):
            warning = (
                f"shape drift on {key}: fingerprint {baseline} became"
                f" {probe.result.fingerprint}; verify parser output"
            )
            warnings.append(warning)
    agents_probe = probes["agents"]
    if not agents_probe.ok or not isinstance(agents_probe.result, AgentsResult):
        raise fail(
            agents_probe.error_code or "FETCH_FAILED",
            f"agents source required for snapshot: {agents_probe.error_message}",
            source="agents",
        )
    agents = agents_probe.result.agents
    ordered = sorted(agents, key=lambda row: row.winrate)
    payload: dict[str, JsonValue] = {
        "ok": True,
        "fetched_at": utc_now(),
        "patch": agents_probe.result.patch,
        "abuse": derive_abuse(agents),
        "avoid": [agent_json(row) for row in ordered[:AVOID_COUNT]],
        "movers": derive_movers(agents),
        "patch_context": snapshot_patch_context(probes["patches"], warnings),
        "map_context": snapshot_maps_section(probes["maps"], warnings),
        "thresholds": {
            "abuse_wr_min": ABUSE_WR,
            "abuse_pr_min": ABUSE_PR,
            "niche_wr_min": ABUSE_WR,
            "niche_pr_max": ABUSE_PR,
            "avoid_bottom_n": AVOID_COUNT,
            "movers_n": MOVERS_COUNT,
        },
    }
    if warnings:
        payload["warnings"] = warnings
    emit(payload)


def cmd_doctor(_args: _Args) -> None:
    """Probe every registry source live and report health per source."""
    registry = load_registry()
    state = load_state()
    baselines = baseline_fingerprints(state)
    keys = sorted(registry)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(keys)) as pool:
        futures = {key: pool.submit(probe_source, key, registry[key]) for key in keys}
        probes = {key: future.result() for key, future in futures.items()}
    for probe in probes.values():
        record_probe(state, probe)
    save_state(state)
    report: list[JsonValue] = []
    for key in keys:
        probe = probes[key]
        entry = source_state(state, key)
        fingerprint_status: JsonValue = None
        if probe.ok and probe.result is not None:
            baseline = baselines.get(key)
            if baseline is None:
                fingerprint_status = "no-baseline"
            elif baseline == probe.result.fingerprint:
                fingerprint_status = "match"
            else:
                fingerprint_status = "mismatch"
        report.append(
            {
                "key": key,
                "name": registry[key]["name"],
                "url": registry[key]["url"],
                "ok": probe.ok,
                "latency_ms": probe.latency_ms,
                "fingerprint": (
                    probe.result.fingerprint if probe.result is not None else None
                ),
                "fingerprint_status": fingerprint_status,
                "consecutive_failures": entry.get("consecutive_failures") or 0,
                "error": probe.error_message if not probe.ok else None,
            }
        )
    emit(
        {
            "ok": True,
            "fetched_at": utc_now(),
            "healthy": all(probe.ok for probe in probes.values()),
            "state_file": str(state_path()),
            "sources": report,
        }
    )


def cmd_sources(_args: _Args) -> None:
    """Dump the registry entries plus their tracker health data."""
    registry = load_registry()
    state = load_state()
    entries: list[JsonValue] = []
    for key in sorted(registry):
        entry = source_state(state, key)
        entries.append(
            {
                "key": key,
                "name": registry[key]["name"],
                "url": registry[key]["url"],
                "parser": registry[key]["parser"],
                "description": registry[key]["description"],
                "health": {
                    "last_fetch_at": entry.get("last_fetch_at"),
                    "last_success_at": entry.get("last_success_at"),
                    "fingerprint": entry.get("fingerprint"),
                    "consecutive_failures": entry.get("consecutive_failures") or 0,
                },
            }
        )
    emit(
        {
            "ok": True,
            "fetched_at": utc_now(),
            "state_file": str(state_path()),
            "sources": entries,
        }
    )


def parse_search_domains(stdout: str) -> list[str]:
    """Extract result domains from parallel CLI --json output."""
    try:
        value = _json_loads(stdout)
    except json.JSONDecodeError as exc:
        raise fail("SEARCH_FAILED", "parallel CLI output is not valid JSON") from exc
    if not _is_dict(value):
        raise fail("SEARCH_FAILED", "parallel CLI output is not a JSON object")
    results = value.get("results")
    if not isinstance(results, list):
        raise fail("SEARCH_FAILED", "parallel CLI output lacks a results list")
    domains: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str):
            host = urllib.parse.urlparse(url).netloc.lower()
            if host and host not in domains:
                domains.append(host)
    return domains


def cmd_discover(args: _Args) -> None:
    """Search for candidate valorant stats sources not yet in the registry."""
    try:
        cli = resolve_sibling("parallel")
    except _FetchError as exc:
        raise fail(exc.code, exc.message) from exc
    try:
        stdout = run_sibling(
            cli,
            ["search", args.query, "--max-results", str(args.max_results), "--json"],
            SEARCH_TIMEOUT,
        )
    except _FetchError as exc:
        raise fail(exc.code, exc.message, dependency="parallel") from exc
    registry = load_registry()
    known = {
        urllib.parse.urlparse(entry["url"]).netloc.lower()
        for entry in registry.values()
    }
    candidates = [
        domain for domain in parse_search_domains(stdout) if domain not in known
    ]
    emit(
        {
            "ok": True,
            "fetched_at": utc_now(),
            "query": args.query,
            "registry_domains": sorted(known),
            "candidates": candidates,
            "vetting": (
                "vet candidates with the procedure in references/sources.md"
                " before adding them to the registry"
            ),
        }
    )


def arguments() -> _Args:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    _ = sub.add_parser(
        "agents", help="agent tier list: winrate, pickrate, deltas, KDA, tier"
    )
    _ = sub.add_parser("patch", help="latest patch highlights with tagged changes")
    _ = sub.add_parser("maps", help="per-map attack/defense round win percentages")
    _ = sub.add_parser(
        "snapshot",
        help="composed answer: abuse, avoid, movers, patch context",
    )
    _ = sub.add_parser(
        "doctor", help="probe every source live; report health and drift"
    )
    _ = sub.add_parser("sources", help="dump the source registry plus tracker health")
    discover = sub.add_parser(
        "discover",
        help="search for new valorant stats sources via the parallel skill",
    )
    _ = discover.add_argument("--query", default=DISCOVER_QUERY)
    _ = discover.add_argument("--max-results", type=int, default=10)
    return parser.parse_args(namespace=_Args())


COMMANDS: dict[str, Callable[[_Args], None]] = {
    "agents": cmd_agents,
    "patch": cmd_patch,
    "maps": cmd_maps,
    "snapshot": cmd_snapshot,
    "doctor": cmd_doctor,
    "sources": cmd_sources,
    "discover": cmd_discover,
}


def main() -> None:
    """Dispatch the parsed command."""
    args = arguments()
    handler = COMMANDS.get(args.command)
    if handler is None:
        raise fail("UNKNOWN_COMMAND", f"unhandled command {args.command!r}")
    handler(args)


if __name__ == "__main__":
    main()
