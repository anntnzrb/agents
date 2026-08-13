# Copyright (c) 2026
"""Exact release resolution and atomic table/category/cost target planning."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .contracts import ResolvedRelease, SourceTarget, raise_expected

if TYPE_CHECKING:
    from .discovery import ReleaseDiscovery

_ALLOWED_HOSTS = {
    "livebench.ai",
    "www.livebench.ai",
    "github.com",
    "raw.githubusercontent.com",
}


def resolve_release(
    selector: str | None,
    discovery: ReleaseDiscovery,
    *,
    explicit_asset_urls: Mapping[str, str] | None = None,
) -> ResolvedRelease:
    """Resolve release for the LiveBench adapter."""
    requested = selector or "latest"
    entries = discovery.releases
    if not entries:
        raise_expected(
            "RELEASE_NOT_FOUND",
            "No LiveBench releases were discovered.",
            {},
        )
    if requested.casefold() == "latest":
        entry = entries[-1]
        resolved = str(entry["id"])
        is_latest = True
    else:
        matches = [entry for entry in entries if str(entry.get("id")) == requested]
        if (
            not matches
            and explicit_asset_urls
            and all(explicit_asset_urls.get(key) for key in ("table", "category"))
        ):
            # Exact caller-supplied official URLs are permitted for an
            # unadvertised release.
            entry = {
                "id": requested,
                "date": requested if len(requested) == 10 else None,  # noqa: PLR2004
                "assets": dict(explicit_asset_urls),
                "source_defined": True,
                "explicit_asset_plan": True,
            }
            discovery.releases.append(entry)
            matches = [entry]
        if not matches:
            raise_expected(
                "RELEASE_NOT_FOUND",
                (
                    "The requested LiveBench release is not advertised by "
                    "the current authority."
                ),
                {
                    "requested_release": requested,
                    "advertised_releases": [str(entry.get("id")) for entry in entries],
                },
            )
        entry = matches[0]
        resolved = str(entry["id"])
        is_latest = resolved == discovery.latest_id
    return ResolvedRelease(
        requested=requested,
        release_id=resolved,
        latest=is_latest,
        date=str(entry.get("date")) if entry.get("date") is not None else None,
        source_defined=True,
        authority_url=discovery.authority_url,
        authority_sha256=discovery.authority_sha256,
        discovered_at=discovery.discovered_at,
        generated_at=str(entry.get("generated_at"))
        if entry.get("generated_at")
        else None,
        metadata={
            k: v for k, v in entry.items() if k not in {"id", "date", "generated_at"}
        },
    )


def plan_targets(  # noqa: PLR0913
    release: ResolvedRelease,
    discovery: ReleaseDiscovery,
    *,
    table_url: str | None = None,
    categories_url: str | None = None,
    cost_url: str | None = None,
    discovered_from: str | None = None,
) -> list[SourceTarget]:
    """Plan targets for the LiveBench adapter."""
    entry = next(
        (
            item
            for item in discovery.releases
            if str(item.get("id")) == release.release_id
        ),
        None,
    )
    assets = entry.get("assets", {}) if isinstance(entry, Mapping) else {}
    if not isinstance(assets, Mapping):
        assets = {}
    table = table_url or _asset(assets, "table")
    category = (
        categories_url or _asset(assets, "category") or _asset(assets, "categories")
    )
    cost = cost_url or _asset(assets, "cost")
    if not table or not category:
        raise_expected(
            "REQUIRES_RENDERED_SOURCE",
            "The selected release has no exact official table/category asset plan.",
            {"release_id": release.release_id, "assets": dict(assets)},
        )
    return [
        SourceTarget(
            release_id=release.release_id,
            artifact_kind="score_table",
            url=_validate_target_url(table),
            discovered_from=discovered_from or discovery.authority_url,
            expected_content_types=("text/csv", "application/octet-stream"),
            required=True,
        ),
        SourceTarget(
            release_id=release.release_id,
            artifact_kind="category_map",
            url=_validate_target_url(category),
            discovered_from=discovered_from or discovery.authority_url,
            expected_content_types=("application/json", "text/json", "*/*"),
            required=True,
        ),
        *(
            [
                SourceTarget(
                    release_id=release.release_id,
                    artifact_kind="cost_table",
                    url=_validate_target_url(cost),
                    discovered_from=discovered_from or discovery.authority_url,
                    expected_content_types=("text/csv", "application/octet-stream"),
                    required=False,
                )
            ]
            if cost
            else []
        ),
    ]


def _asset(assets: Mapping[object, object], key: str) -> str | None:
    value = assets.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_target_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme in {"fixture", "file"} or not parsed.scheme:
        return url
    if parsed.scheme != "https" or parsed.netloc.casefold() not in _ALLOWED_HOSTS:
        raise_expected(
            "SOURCE_UNAVAILABLE",
            "Only exact official LiveBench/repository asset URLs are allowed.",
            {"attempted_url": url},
        )
    return url
