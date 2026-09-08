"""Select canonical model releases and their published effort variants."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        return {str(k): v for k, v in mapping.items()}
    return {}


def _normalized(value: object) -> str:
    return (
        " ".join(re.findall(r"[a-z0-9]+", value.lower()))
        if isinstance(value, str)
        else ""
    )


def get_model_effort_info(model: dict[str, object]) -> dict[str, object]:
    """Read effort identity without interpreting model-name suffixes."""
    raw = _as_dict(model.get("raw_fields"))
    effort = _as_dict(raw.get("effort"))
    flags = [
        value
        for value in (model.get("reasoning_model"), raw.get("isReasoning"))
        if isinstance(value, bool)
    ]
    conflicting = bool(flags) and any(value != flags[0] for value in flags)
    reasoning = flags[0] if flags and not conflicting else None
    slug = effort.get("slug")
    label = effort.get("label")
    has_effort = isinstance(slug, str) and bool(slug.strip())
    if conflicting or (reasoning is False and has_effort):
        return {
            "slug": None,
            "label": None,
            "level": None,
            "is_reasoning": None,
            "kind": "conflicting",
            "raw": effort,
        }
    if has_effort:
        return {
            "slug": slug,
            "label": label,
            "level": effort.get("level"),
            "is_reasoning": reasoning,
            "kind": "effort",
            "raw": effort,
        }
    if reasoning is False:
        return {
            "slug": "non-reasoning",
            "label": "non-reasoning",
            "level": None,
            "is_reasoning": False,
            "kind": "non-reasoning",
            "raw": None,
        }
    return {
        "slug": None,
        "label": None,
        "level": None,
        "is_reasoning": reasoning,
        "kind": "unknown",
        "raw": effort or None,
    }


def extract_releases(models: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """Group only models with published release metadata."""
    releases: dict[str, dict[str, object]] = {}
    for model in models:
        release = _as_dict(_as_dict(model.get("raw_fields")).get("release"))
        slug = release.get("slug")
        name = release.get("name")
        if not isinstance(slug, str) or not slug.strip():
            continue
        if slug not in releases:
            releases[slug] = {"slug": slug, "name": name, "models": []}
        cast("list[dict[str, object]]", releases[slug]["models"]).append(model)
    return releases


def match_family(
    family_query: str,
    releases: dict[str, dict[str, object]],
    *,
    usage_error_factory: type[Exception] = ValueError,
) -> dict[str, object]:
    """Resolve an exact or unique whole-token published release name."""
    query = _normalized(family_query)
    if not query:
        msg = "Family selector must not be empty"
        raise usage_error_factory(msg)
    exact: list[dict[str, object]] = []
    partial: list[dict[str, object]] = []
    for release in releases.values():
        names = [_normalized(release.get(key)) for key in ("slug", "name")]
        if query in names:
            exact.append(release)
        elif any(f" {query} " in f" {name} " for name in names):
            partial.append(release)
    matches = exact or partial
    if len(matches) == 1:
        return matches[0]
    if matches:
        candidates = sorted(str(release["slug"]) for release in matches)
        msg = f"Ambiguous family selector {family_query!r}. Candidates: {candidates}"
        raise usage_error_factory(msg)
    msg = f"No published model release matches {family_query!r}"
    raise usage_error_factory(msg)


def _parse_selector(
    selector: str,
    *,
    usage_error_factory: type[Exception] = ValueError,
) -> tuple[str, list[str]]:
    """Split a selector into family name and validated effort list."""
    family, separator, effort_text = selector.partition(":")
    if not family.strip():
        msg = f"Empty family in selector {selector!r}"
        raise usage_error_factory(msg)
    requested = [part.strip() for part in effort_text.split(",")] if separator else []
    if separator and (not requested or any(not part for part in requested)):
        msg = f"Empty effort in selector {selector!r}"
        raise usage_error_factory(msg)
    return family.strip(), requested


def _match_requested_efforts(
    variants: list[tuple[dict[str, object], dict[str, object]]],
    requested: list[str],
    release_slug: object,
    available: list[str],
    *,
    usage_error_factory: type[Exception] = ValueError,
) -> list[tuple[dict[str, object], dict[str, object]]]:
    """Resolve requested efforts or return all variants if none requested."""
    if not requested:
        return variants
    matched: list[tuple[dict[str, object], dict[str, object]]] = []
    for effort in requested:
        effort_norm = _normalized(effort)
        candidates = [
            (model, info)
            for model, info in variants
            if effort_norm
            and effort_norm in {_normalized(info["slug"]), _normalized(info["label"])}
        ]
        if not candidates:
            msg = (
                f"Requested effort {effort!r} not found for {release_slug!r}. "
                f"Available efforts: {available}"
            )
            raise usage_error_factory(msg)
        matched.extend(candidates)
    return matched


def compare_models(
    snapshot: dict[str, object],
    snapshot_path: Path,
    selectors: list[str],
    *,
    usage_error_factory: type[Exception] = ValueError,
) -> dict[str, object]:
    """Select all requested variants, failing instead of returning partial matches."""
    values = snapshot.get("models")
    if not isinstance(values, list) or not selectors:
        msg = "compare requires canonical models and at least one selector"
        raise usage_error_factory(msg)
    raw_models = cast("list[object]", values)
    models = [
        cast("dict[str, object]", value)
        for value in raw_models
        if isinstance(value, dict)
    ]
    releases = extract_releases(models)
    rows: list[dict[str, object]] = []
    selections: list[dict[str, object]] = []
    seen: set[str] = set()

    for selector in selectors:
        family, requested = _parse_selector(
            selector, usage_error_factory=usage_error_factory
        )
        release = match_family(
            family, releases, usage_error_factory=usage_error_factory
        )
        family_models = cast("list[dict[str, object]]", release["models"])
        variants = [(model, get_model_effort_info(model)) for model in family_models]
        available = sorted(
            {str(info["slug"]) for _, info in variants if info["slug"] is not None}
        )
        matched = _match_requested_efforts(
            variants,
            requested,
            release["slug"],
            available,
            usage_error_factory=usage_error_factory,
        )

        matched_slugs: list[str] = []
        for model, info in matched:
            slug = model.get("slug")
            if not isinstance(slug, str) or not slug:
                msg = "Selected model has no canonical slug"
                raise usage_error_factory(msg)
            if info["kind"] == "conflicting":
                msg = f"Conflicting reasoning metadata for {slug!r}"
                raise usage_error_factory(msg)
            if slug not in matched_slugs:
                matched_slugs.append(slug)
            if slug in seen:
                continue
            seen.add(slug)
            row = dict(model)
            row.update(
                {
                    "release_slug": release["slug"],
                    "release_name": release["name"],
                    "effort_slug": info["slug"],
                    "effort_label": info["label"],
                    "effort_level": info["level"],
                    "is_reasoning": info["is_reasoning"],
                    "effort_status": info["kind"],
                }
            )
            rows.append(row)

        selections.append(
            {
                "selector": selector,
                "family_selector": family,
                "requested_efforts": requested,
                "matched_release": {"slug": release["slug"], "name": release["name"]},
                "available_efforts": available,
                "matched_model_slugs": matched_slugs,
            }
        )

    meta = _as_dict(snapshot.get("meta"))
    return {
        "snapshot": str(snapshot_path),
        "scope": "canonical_models",
        "source": {
            "fetched_at": meta.get("fetched_at"),
            "schema_version": meta.get("schema_version"),
            "sources": meta.get("sources"),
        },
        "coverage": "variants_observed_in_snapshot",
        "selections": selections,
        "matched_models": len(rows),
        "rows": rows,
    }
