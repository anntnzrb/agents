"""DeepSWE identity-kernel contract tests."""

from __future__ import annotations

from typing import cast

from deepswe.identity import canonical_identity, classify_duplicates, identity_json


def _row(**values: object) -> dict[str, object]:
    row: dict[str, object] = {
        "model": "model",
        "reasoning_effort": "high",
        "harness": "runner",
        "config": "base",
    }
    row.update(values)
    return row


def test_structured_identity_does_not_collide_on_delimiters() -> None:
    left = _row(model="model|high", reasoning_effort="runner", harness="config")
    right = _row(model="model", reasoning_effort="high", harness="runner|config")

    assert canonical_identity(left) != canonical_identity(right)
    assert identity_json(left) != identity_json(right)
    assert identity_json(left) == '["model|high","runner","config","base"]'


def test_null_and_empty_tuple_members_are_preserved() -> None:
    null_config = _row(config=None)
    empty_config = _row(config="")

    assert canonical_identity(null_config)[3] is None
    assert canonical_identity(empty_config)[3] == ""
    assert identity_json(null_config) != identity_json(empty_config)


def test_published_fallback_requires_wholly_absent_configuration_tuple() -> None:
    assert canonical_identity({"id": "published-1"}) == (
        "published_id",
        "id",
        "published-1",
    )
    assert canonical_identity({"name": "published-name", "id": None}) == (
        "published_id",
        "name",
        "published-name",
    )
    partial = {"model": None, "id": "must-not-win"}
    assert canonical_identity(partial) == (None, None, None, None)


def test_duplicate_groups_keep_raw_rows_and_classify_identical_conflicts() -> None:
    identical_a = _row(id="same", config="same", pass_at_1=0.5)
    identical_b = {
        "pass_at_1": 0.5,
        **{key: identical_a[key] for key in identical_a if key != "pass_at_1"},
    }
    conflicting = _row(id="conflict", config="conflict", pass_at_1=0.2)
    conflicting_other = {**conflicting, "pass_at_1": 0.8}

    result = classify_duplicates(
        [identical_a, identical_b, conflicting, conflicting_other]
    )

    assert len(result["identical"]) == 1
    assert len(result["conflicting"]) == 1
    assert result["identical"][0]["row_indexes"] == [0, 1]
    assert result["conflicting"][0]["row_indexes"] == [2, 3]
    assert len(cast("list[object]", result["identical"][0]["rows"])) == 2
    assert len(cast("list[object]", result["conflicting"][0]["rows"])) == 2
    assert {item["code"] for item in result["diagnostics"]} == {
        "DUPLICATE_IDENTITY",
        "DUPLICATE_CONFLICT",
    }


def test_duplicate_classification_order_is_independent() -> None:
    rows = [
        _row(id="x", config="x", value=1),
        _row(id="x", config="x", value=2),
        _row(id="y", config="y", value=3),
    ]
    forward = classify_duplicates(rows)
    reverse = classify_duplicates(list(reversed(rows)))

    def comparable(result: dict[str, list[dict[str, object]]]) -> tuple[object, ...]:
        return tuple(
            (
                group["identity"],
                tuple(cast("list[object]", group["signatures"])),
                len(cast("list[object]", group["rows"])),
            )
            for bucket in ("identical", "conflicting")
            for group in result[bucket]
        )

    assert comparable(forward) == comparable(reverse)
