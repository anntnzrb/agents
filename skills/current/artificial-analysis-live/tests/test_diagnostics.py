"""Contract tests for diagnostic redaction and stable merging."""

# ruff: noqa: CPY001, INP001, S101, D103
from __future__ import annotations

import _path  # noqa: F401
from artificial_analysis.diagnostics import (
    REDACTED,
    Diagnostic,
    merge_diagnostics,
    redact,
    redact_query,
)


def test_redact_query_recursively_safe_urls_and_bare_queries() -> None:
    assert (
        redact_query("https://example.test/data?api_key=secret&limit=3#rows")
        == "https://example.test/data?api_key=[REDACTED]&limit=3#rows"
    )
    assert (
        redact_query("?access_token=secret&output_tokens=42&sort=latency")
        == "?access_token=[REDACTED]&output_tokens=42&sort=latency"
    )
    assert redact_query("model=opus&sort=latency") == "model=opus&sort=latency"
    assert redact_query("plain prose? no query") == "plain prose? no query"
    assert redact_query("not-a-query") == "not-a-query"


def test_redact_recurses_through_keys_values_and_sequences() -> None:
    value = {
        "api_key": "top-level-secret",
        "Authorization": "Bearer nested-secret",
        "nested": [
            {
                "password": "password-secret",
                "url": "https://example.test/?token=url-secret&keep=yes",
            },
            (
                "Basic dXNlcjpwYXNz",
                {"private_key": "private-key-secret"},
            ),
        ],
        "set_values": {"api_key=inline-secret", "safe text"},
        "query": "model=opus&token=query-secret&sort=latency",
    }

    assert redact(value) == {
        "api_key": REDACTED,
        "Authorization": REDACTED,
        "nested": [
            {
                "password": REDACTED,
                "url": "https://example.test/?token=[REDACTED]&keep=yes",
            },
            (
                "Basic [REDACTED]",
                {"private_key": REDACTED},
            ),
        ],
        "set_values": {"api_key=[REDACTED]", "safe text"},
        "query": "model=opus&token=[REDACTED]&sort=latency",
    }


def test_redact_string_credentials_and_pem_are_hidden() -> None:
    assert redact("api-key=inline-secret") == "api-key=[REDACTED]"
    assert redact("access_token: inline-secret") == "access_token: [REDACTED]"
    assert redact("Bearer bearer-secret, Basic basic-secret") == (
        "Bearer [REDACTED], Basic [REDACTED]"
    )
    assert (
        redact("-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----")
        == REDACTED
    )


def test_safe_metric_strings_and_numbers_are_retained() -> None:
    metrics = {
        "output_tokens": "123",
        "answer_tokens": 42,
        "reasoning_tokens": 81.5,
        "token_count": 246,
        "cost_per_token": "0.0001",
        "latency_ms": 12.5,
        "normal_text": "token is a metric label",
    }

    assert redact(metrics) == metrics


def test_diagnostic_to_dict_has_exact_optional_fields_and_redacted_details() -> None:
    diagnostic = Diagnostic(
        code="fetch_failed",
        severity="warning",
        stage="fetch",
        message="source unavailable",
        source_path="https://example.test/data?api_key=secret&kind=rsc",
        artifact_id="artifact-1",
        details={
            "api_key": "detail-secret",
            "metrics": {"output_tokens": 10, "latency_ms": 1.25},
        },
    )

    assert diagnostic.to_dict() == {
        "code": "fetch_failed",
        "severity": "warning",
        "stage": "fetch",
        "message": "source unavailable",
        "source_path": "https://example.test/data?api_key=[REDACTED]&kind=rsc",
        "artifact_id": "artifact-1",
        "details": {
            "api_key": REDACTED,
            "metrics": {"output_tokens": 10, "latency_ms": 1.25},
        },
    }


def test_diagnostic_to_dict_omits_unset_optional_fields() -> None:
    assert Diagnostic("code", "info", "stage", "message").to_dict() == {
        "code": "code",
        "severity": "info",
        "stage": "stage",
        "message": "message",
    }


def test_merge_diagnostics_deduplicates_in_first_seen_order() -> None:
    first = Diagnostic(
        "first",
        "warning",
        "parse",
        "first message",
        details={"b": 2, "a": 1},
    )
    equivalent_key_order = Diagnostic(
        "first",
        "warning",
        "parse",
        "first message",
        details={"a": 1, "b": 2},
    )
    second = {
        "code": "second",
        "severity": "error",
        "stage": "validate",
        "message": "second message",
        "source_path": "snapshot.json",
    }
    third = Diagnostic("third", "info", "emit", "third message")

    merged = merge_diagnostics(
        [first, equivalent_key_order, second],
        third,
        {
            "code": "third",
            "severity": "info",
            "stage": "emit",
            "message": "third message",
        },
    )

    assert [item.to_dict() for item in merged] == [
        first.to_dict(),
        Diagnostic(
            "second",
            "error",
            "validate",
            "second message",
            source_path="snapshot.json",
        ).to_dict(),
        third.to_dict(),
    ]


def test_merge_diagnostics_deduplicates_after_credential_redaction() -> None:
    first = Diagnostic(
        "auth",
        "error",
        "fetch",
        "credentials rejected",
        source_path="https://example.test/?api_key=one",
        details={"api_key": "one"},
    )
    same_after_redaction = Diagnostic(
        "auth",
        "error",
        "fetch",
        "credentials rejected",
        source_path="https://example.test/?api_key=two",
        details={"api_key": "two"},
    )

    merged = merge_diagnostics(first, [same_after_redaction])

    assert len(merged) == 1
    assert merged[0].to_dict() == {
        "code": "auth",
        "severity": "error",
        "stage": "fetch",
        "message": "credentials rejected",
        "source_path": "https://example.test/?api_key=[REDACTED]",
        "details": {"api_key": REDACTED},
    }
