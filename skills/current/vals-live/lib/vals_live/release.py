# Copyright 2026 Vals-live contributors.
"""Runtime Vals version and snapshot-only release resolution."""

from __future__ import annotations

from .identity import release_identity


def resolve(
    root: object, raw: bytes, requested: str | None = None
) -> dict[str, object]:
    """Resolve an exact requested release or content snapshot identity."""
    source_release, snapshot = release_identity(root, raw)
    if (
        requested
        and requested not in {"latest", ""}
        and source_release
        and str(source_release) != requested
    ):
        return {
            "ok": False,
            "code": "RELEASE_NOT_FOUND",
            "message": (
                "The requested Vals release/version was not present in the source."
            ),
            "details": {"requested": requested, "resolved": source_release},
        }
    if (
        requested
        and requested not in {"latest", ""}
        and not source_release
        and requested != snapshot
    ):
        return {
            "ok": False,
            "code": "RELEASE_NOT_FOUND",
            "message": (
                "This Vals source exposes no source-defined release; "
                "use its snapshot identity."
            ),
            "details": {"requested": requested, "snapshot": snapshot},
        }
    selected = source_release or snapshot
    return {
        "ok": True,
        "requested": requested or "latest",
        "id": selected,
        "source_release_id": source_release,
        "snapshot_id": snapshot,
        "source_defined": bool(source_release),
        "latest": requested in (None, "", "latest"),
        "date": None,
        "generated_at": None,
    }
