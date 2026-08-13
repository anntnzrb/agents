# Copyright (c) 2026
"""LiveBench application/bundle discovery with explicit authority limitation."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urljoin

if TYPE_CHECKING:
    from pathlib import Path

from .cache import CacheStore, sha256_bytes
from .contracts import Diagnostic, RawArtifact, SourceTarget, raise_expected, utc_now
from .diagnostics import make_diagnostic
from .parsing import parse_release_list
from .transport import fetch_target

APP_URL = "https://livebench.ai/"
_DATE_RE = re.compile(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)")
_SCRIPT_RE = re.compile(
    r"<script[^>]+src=[\"']([^\"']+\.js(?:\?[^\"']*)?)[\"']", re.IGNORECASE
)


@dataclass
class ReleaseDiscovery:
    """Represent ReleaseDiscovery in the LiveBench adapter."""

    releases: list[dict[str, object]]
    latest_id: str
    authority_url: str
    authority_sha256: str
    discovered_at: str
    authority_artifact: RawArtifact | None = None
    bundle_artifact: RawArtifact | None = None
    asset_templates: dict[str, str] = field(default_factory=dict)
    warnings: list[Diagnostic] = field(default_factory=list)
    raw_metadata: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """As dict for the LiveBench adapter."""
        return {
            "releases": self.releases,
            "latest": self.latest_id,
            "authority": {
                "url": self.authority_url,
                "sha256": self.authority_sha256,
                "discovered_at": self.discovered_at,
                "rule": "last advertised release entry",
                "limitation": (
                    "current application/bundle selector is not an origin-wide "
                    "release index"
                ),
            },
            "asset_templates": self.asset_templates,
            "raw_metadata": self.raw_metadata,
        }


def discover_releases(
    *,
    snapshot: Path | None = None,
    cache: CacheStore | None = None,
    timeout: float = 30.0,
    opener: Callable[..., object] | None = None,
) -> ReleaseDiscovery:
    """Discover releases for the LiveBench adapter."""
    if snapshot is not None:
        return _discover_snapshot(snapshot)
    store = cache or CacheStore()
    shell_target = SourceTarget(
        "discovery", "application", APP_URL, APP_URL, ("text/html",)
    )
    shell = fetch_target(shell_target, store, timeout=timeout, opener=opener)
    html = shell.body.decode("utf-8", errors="replace")
    match = _SCRIPT_RE.search(html)
    if match is None:
        raise_expected(
            "REQUIRES_RENDERED_SOURCE",
            (
                "The LiveBench shell did not expose an official JavaScript "
                "bundle or data asset."
            ),
            {"attempted_url": APP_URL, "delivery": "empty_root_js_shell"},
        )
    bundle_url = urljoin(APP_URL, match.group(1))
    bundle_target = SourceTarget(
        "discovery",
        "bundle",
        bundle_url,
        APP_URL,
        ("text/javascript", "application/javascript", "*/*"),
    )
    bundle = fetch_target(bundle_target, store, timeout=timeout, opener=opener)
    source = bundle.body.decode("utf-8", errors="replace")
    release_ids = _release_ids(source)
    if not release_ids:
        raise_expected(
            "MALFORMED_PAYLOAD",
            "The official bundle did not advertise a release selector.",
            {"attempted_url": bundle_url},
        )
    templates = _asset_templates(source, APP_URL)
    if "table" not in templates or "category" not in templates:
        raise_expected(
            "REQUIRES_RENDERED_SOURCE",
            "The official bundle did not expose score and category asset templates.",
            {"attempted_url": bundle_url, "templates": templates},
        )
    releases = [_release_entry(identifier, templates) for identifier in release_ids]
    warning = make_diagnostic(
        "RELEASE_DISCOVERY_LIMITED",
        (
            "Release discovery is bounded by the current application/bundle "
            "selector; no directory enumeration is attempted."
        ),
        severity="warning",
        stage="discover",
        source=APP_URL,
        details={"authority_url": bundle_url, "rule": "last advertised release entry"},
    )
    return ReleaseDiscovery(
        releases,
        release_ids[-1],
        bundle_url,
        bundle.sha256,
        bundle.observed_at,
        shell,
        bundle,
        templates,
        [warning],
        {
            "shell": shell.provenance(parser="livebench.discovery"),
            "bundle": bundle.provenance(parser="livebench.discovery"),
        },
    )


def _discover_snapshot(path: Path) -> ReleaseDiscovery:
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise_expected(
            "SNAPSHOT_INVALID",
            "Release snapshot could not be read.",
            {"path": str(path), "error": str(exc)},
        )
    digest = sha256_bytes(body)
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise_expected(
            "SNAPSHOT_INVALID",
            "Release snapshot must be valid JSON.",
            {"path": str(path), "error": str(exc)},
        )
    if isinstance(parsed, Mapping) and parsed.get("releases") is not None:
        raw_entries = parsed
        authority_url = str(parsed.get("authority_url") or f"fixture://{path}")
        templates = (
            {str(k): str(v) for k, v in dict(parsed.get("asset_templates", {})).items()}
            if isinstance(parsed.get("asset_templates"), Mapping)
            else {}
        )
    else:
        raw_entries = {"releases": parsed}
        authority_url = f"fixture://{path}"
        templates = {}
    entries = parse_release_list(raw_entries)
    for entry in entries:
        identifier = str(entry["id"])
        entry.setdefault(
            "assets",
            _release_entry(identifier, templates).get("assets", {}),
        )
    latest = (
        str(parsed.get("latest"))
        if isinstance(parsed, Mapping) and parsed.get("latest")
        else str(entries[-1]["id"])
    )
    if latest not in {str(entry["id"]) for entry in entries}:
        latest = str(entries[-1]["id"])
    warning = make_diagnostic(
        "HISTORICAL_SNAPSHOT",
        "An explicit release snapshot is being used.",
        severity="warning",
        stage="discover",
        source=authority_url,
        details={"path": str(path)},
    )
    return ReleaseDiscovery(
        entries,
        latest,
        authority_url,
        digest,
        utc_now(),
        None,
        None,
        templates,
        [warning],
        {"snapshot_path": str(path), "sha256": digest},
    )


def _release_ids(bundle: str) -> list[str]:
    # Prefer an array assigned to the selector's "last entry" expression.
    # Minified bundles often contain model metadata arrays with dates too;
    # those are not release IDs and must not win merely because they occur
    # later in the source.
    candidates: list[tuple[int, int, list[str]]] = []
    assignment = re.compile(
        r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*="
        r"\s*(\[[^\]]{0,1200}\])",
        re.DOTALL,
    )
    for match in assignment.finditer(bundle):
        name, literal = match.groups()
        values = _DATE_RE.findall(literal)
        if len(set(values)) < 2:  # noqa: PLR2004
            continue
        selector_pattern = (
            rf"\b{re.escape(name)}\s*\[\s*{re.escape(name)}"
            rf"\.length\s*-\s*1\s*\]"
        )
        score = 1 if re.search(selector_pattern, bundle[match.end() :]) else 0
        candidates.append((score, match.start(), values))
    if candidates:
        values = max(
            candidates,
            key=lambda item: (item[0], -item[1]),
        )[2]
    else:
        values = _DATE_RE.findall(bundle)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _asset_templates(bundle: str, base_url: str) -> dict[str, str]:
    result: dict[str, str] = {}
    # Keep only URL/path literals actually exposed by the official bundle.
    # Bundlers commonly leave the release segment as a template expression
    # (for example ``./table_${release}.csv``), while older deployments
    # contain one concrete dated filename.  Support both representations
    # without inventing a directory or filename.
    release_fragment = r"(?:\d{4}_\d{2}_\d{2}|\$\{[A-Za-z_$][A-Za-z0-9_$]*\})"
    patterns = (
        (
            "table",
            rf"""(?:https?://[^"'`\s]+/)?[^"'`\\\s]*table_{release_fragment}\.csv""",
        ),
        (
            "category",
            rf"""(?:https?://[^"'`\s]+/)?[^"'`\\\s]*categories_{release_fragment}\.json""",
        ),
        (
            "cost",
            rf"""(?:https?://[^"'`\s]+/)?[^"'`\\\s]*cost_{release_fragment}\.csv""",
        ),
    )
    for kind, pattern in patterns:
        matches = list(re.finditer(pattern, bundle))
        if not matches:
            continue
        literal = matches[-1].group(0)
        normalized = re.sub(
            release_fragment,
            "{release}",
            literal,
        )
        result[kind] = urljoin(base_url, normalized)
    return result


def _release_entry(
    identifier: str,
    templates: Mapping[str, str],
) -> dict[str, object]:
    transformed = identifier.replace("-", "_")
    assets: dict[str, str] = {}
    for kind, template in templates.items():
        assets[kind] = template.replace("{release}", transformed)
    return {"id": identifier, "date": identifier, "assets": assets}
