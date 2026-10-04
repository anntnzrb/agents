# ruff: noqa: C901, D103
"""Value and provenance evidence projection for public payloads."""

from .contracts import as_dict as _as_dict
from .contracts import is_object_list, is_object_tuple, is_str_dict
from .values import parse_numeric


def numeric_scalar(value: object) -> bool:
    """Recognize numeric values including non-finite values for evidence."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def evidence_record(  # noqa: PLR0913
    raw_value: object,
    *,
    source_path: str | None,
    source_field: str | None,
    artifact_hash: str | None = None,
    value_status: str = "published",
    semantics: str = "known",
    unit: str | None = None,
    normalization: str | None = None,
    blocked_reasons: tuple[str, ...] = (),
    formula: str | None = None,
    input_paths: tuple[str, ...] = (),
) -> dict[str, object]:
    """Project ``values.parse_numeric`` into the additive CLI evidence shape."""
    parsed = parse_numeric(
        raw_value,
        unit=unit,
        normalization=normalization,
        source_path=source_path,
        source_field=source_field,
        value_status=value_status,
        metric_semantics_status=semantics,
        blocked_reasons=blocked_reasons,
        parser="artificial-analysis.cli",
        parser_version="1",
        sha256=artifact_hash,
    )
    evidence: dict[str, object] = parsed.to_dict()
    if value_status == "derived" and evidence.get("normalized_value") is None:
        # ``parse_numeric`` classifies a null/raw-unparseable value as missing
        # or unparsed.  A declared derived path still describes provenance as
        # derived; only its usability is unavailable.
        raw_reasons = evidence.get("blocked_reasons")
        reasons: list[object] = (
            [
                reason
                for reason in raw_reasons
                if reason not in {"missing_value", "unparsed_value"}
            ]
            if is_object_list(raw_reasons)
            else []
        )
        if "MISSING_REQUIRED_INPUT" not in reasons:
            reasons.append("MISSING_REQUIRED_INPUT")
        evidence["value_status"] = "derived"
        evidence["comparison_eligibility"] = "blocked"
        evidence["blocked_reasons"] = reasons
    # Keep the values.py names and expose the concise contract aliases.  This
    # lets old consumers use source_field/value_status while new consumers can
    # inspect field/status without a translation table.
    raw_blockers = evidence.get("blocked_reasons")
    blockers_list: list[object] = (
        [str(r) for r in raw_blockers]
        if is_object_list(raw_blockers) or is_object_tuple(raw_blockers)
        else []
    )
    evidence.update(
        {
            "raw": evidence.get("raw_value"),
            "normalized": evidence.get("normalized_value"),
            "field": evidence.get("source_field"),
            "version": evidence.get("parser_version"),
            "artifact_hash": evidence.get("sha256"),
            "status": evidence.get("value_status"),
            "semantics": evidence.get("metric_semantics_status"),
            "eligibility": evidence.get("comparison_eligibility"),
            "blockers": blockers_list,
        },
    )
    if formula is not None:
        evidence["formula"] = formula
        evidence["input_paths"] = list(input_paths)
    return evidence


def lookup_path(row: dict[str, object], path: str) -> object:
    current: object = row
    for part in path.split("."):
        if not is_str_dict(current):
            return None
        current = current.get(part)
    return current


def source_hash_from_payload(payload: dict[str, object]) -> str | None:
    for container_key in ("source", "meta"):
        container = _as_dict(payload.get(container_key))
        for key in ("sha256", "artifact_hash", "source_hash"):
            value = container.get(key)
            if isinstance(value, str) and value:
                return value
        nested = _as_dict(container.get("source"))
        value = nested.get("sha256")
        if isinstance(value, str) and value:
            return value
    return None


def attach_row_evidence(  # noqa: PLR0913
    row: dict[str, object],
    *,
    metric_paths: tuple[str, ...] = (),
    source_prefix: str = "$",
    artifact_hash: str | None = None,
    derived_paths: dict[str, tuple[str, tuple[str, ...]] | None] | None = None,
    raw_values: dict[str, object] | None = None,
    unknown_paths: tuple[str, ...] = (),
) -> dict[str, object]:
    """Attach evidence for source and derived scalars without changing values."""
    metric_evidence: dict[str, object] = _as_dict(row.get("metric_evidence"))
    resolved_derived_paths = derived_paths or {}
    resolved_raw_values = raw_values or {}
    unknown_set = set(unknown_paths)

    def add(path: str, value: object, *, unknown: bool = False) -> None:
        if path in metric_evidence:
            return
        formula_and_inputs = resolved_derived_paths.get(path)
        if formula_and_inputs is not None:
            formula, input_paths = formula_and_inputs
            metric_evidence[path] = evidence_record(
                value,
                source_path=f"{source_prefix}.{path}",
                source_field=path.rsplit(".", 1)[-1],
                artifact_hash=artifact_hash,
                value_status="derived",
                semantics="known",
                formula=formula,
                input_paths=input_paths,
            )
            return
        metric_evidence[path] = evidence_record(
            resolved_raw_values.get(path, value),
            source_path=f"{source_prefix}.{path}",
            source_field=path.rsplit(".", 1)[-1],
            artifact_hash=artifact_hash,
            semantics="unknown" if (unknown or path in unknown_set) else "known",
        )

    for path in metric_paths:
        add(
            path,
            lookup_path(row, path),
            unknown=path.startswith(("raw_fields.", "unknowns.")),
        )

    def walk(node: object, prefix: str) -> None:
        if is_str_dict(node):
            for key, value in node.items():
                if key in {"metric_evidence", "raw_metadata"}:
                    continue
                path = f"{prefix}.{key}" if prefix else key
                if numeric_scalar(value):
                    add(
                        path,
                        value,
                        unknown=prefix.startswith(("raw_fields", "unknowns")),
                    )
                elif is_str_dict(value):
                    walk(value, path)
                elif is_object_list(value):
                    for index, item in enumerate(value):
                        walk(item, f"{path}[{index}]")
        elif is_object_list(node):
            for index, item in enumerate(node):
                walk(item, f"{prefix}[{index}]")

    walk(row, "")
    row["metric_evidence"] = metric_evidence
    return row


def attach_payload_evidence(
    payload: dict[str, object],
    *,
    artifact_hash: str | None = None,
) -> dict[str, object]:
    """Attach evidence for payload-level derived scalar fields."""
    resolved_hash = artifact_hash or source_hash_from_payload(payload)
    metric_evidence: dict[str, object] = _as_dict(payload.get("metric_evidence"))

    def walk(node: object, prefix: str) -> None:
        if is_str_dict(node):
            for key, value in node.items():
                if key in {"metric_evidence", "raw_metadata"}:
                    continue
                path = f"{prefix}.{key}" if prefix else key
                if numeric_scalar(value):
                    if path not in metric_evidence:
                        metric_evidence[path] = evidence_record(
                            value,
                            source_path=f"$.{path}",
                            source_field=key,
                            artifact_hash=resolved_hash,
                            value_status="derived",
                        )
                elif is_str_dict(value) or is_object_list(value):
                    walk(value, path)
        elif is_object_list(node):
            for index, item in enumerate(node):
                walk(item, f"{prefix}[{index}]")

    walk(payload, "")
    payload["metric_evidence"] = metric_evidence
    return payload
