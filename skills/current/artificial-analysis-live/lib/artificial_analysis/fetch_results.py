# ruff: noqa: D103
"""Fetch-result adaptation and conditional cache validation."""

import hashlib
from typing import TYPE_CHECKING

from .contracts import as_dict, is_str_dict
from .rsc import CacheError, FetchResult

if TYPE_CHECKING:
    from typing import NoReturn

NOT_MODIFIED = 304


def _artifact_record_metadata(record: dict[str, object]) -> dict[str, object]:
    return as_dict(record.get("metadata"))


def result_headers(result: object) -> dict[str, str]:
    headers = getattr(result, "headers", None)
    if not is_str_dict(headers):
        return {}
    return {str(k): str(v) for k, v in headers.items()}


def result_header(result: object, name: str) -> str | None:
    headers = result_headers(result)
    value = headers.get(name)
    if isinstance(value, str) and value:
        return value
    folded_name = name.casefold()
    for key, candidate in headers.items():
        if key.casefold() == folded_name and candidate:
            return candidate
    return None


def result_fetched_at(result: object) -> str:
    value = getattr(result, "fetched_at", None)
    return value if isinstance(value, str) else ""


def result_etag(result: object) -> str | None:
    value = getattr(result, "etag", None)
    if isinstance(value, str) and value:
        return value
    return result_header(result, "etag")


def result_last_modified(result: object) -> str | None:
    value = getattr(result, "last_modified", None)
    if isinstance(value, str) and value:
        return value
    return result_header(result, "last-modified")


def result_final_url(result: object, fallback: str | None = None) -> str | None:
    value = getattr(result, "final_url", None)
    return value if isinstance(value, str) and value else fallback


def result_sha256(result: object) -> str | None:
    value = getattr(result, "sha256", None)
    if isinstance(value, str) and value:
        return value
    body = getattr(result, "body", None)
    if isinstance(body, str):
        return hashlib.sha256(body.encode("utf-8")).hexdigest()
    return None


def result_byte_length(result: object) -> int | None:
    value = getattr(result, "byte_length", None)
    if isinstance(value, int):
        return value
    body = getattr(result, "body", None)
    if isinstance(body, str):
        return len(body.encode("utf-8"))
    return None


def result_artifact_ref(result: object) -> str | None:
    value = getattr(result, "artifact_ref", None)
    return value if isinstance(value, str) and value else None


def materialize_fetch_result(
    result: object,
    *,
    fallback_url: str,
) -> FetchResult:
    if isinstance(result, FetchResult):
        return result
    body = getattr(result, "body", None)
    status_code = getattr(result, "status_code", None)
    fetched_at = result_fetched_at(result)
    if not isinstance(body, str) or not isinstance(status_code, int):
        message = "FetchResult compatibility object is missing base fields"
        raise TypeError(message)
    return FetchResult(
        body=body,
        status_code=status_code,
        headers=result_headers(result),
        fetched_at=fetched_at,
        final_url=result_final_url(result, fallback_url),
        etag=result_etag(result),
        last_modified=result_last_modified(result),
        sha256=result_sha256(result),
        byte_length=result_byte_length(result),
        artifact_ref=result_artifact_ref(result),
    )


def validator_from(
    cache_meta: object,
    record: dict[str, object] | None,
    name: str,
) -> str | None:
    value: object = None
    if record is not None:
        value = _artifact_record_metadata(record).get(name)
    if not isinstance(value, str) and cache_meta is not None:
        value = getattr(cache_meta, name, None)
    return value if isinstance(value, str) and value else None


def validate_304(
    result: FetchResult,
    cached: tuple[bytes, dict[str, object]] | None,
    *,
    sent_etag: str | None,
    sent_last_modified: str | None,
) -> FetchResult:
    if cached is None:
        _raise_cache_failure(
            "CACHE_MISSING",
            "Upstream returned 304 but no matching cached artifact exists.",
        )
    raw, record = cached
    cached_etag = validator_from(None, record, "etag") or sent_etag
    cached_last_modified = (
        validator_from(None, record, "last_modified") or sent_last_modified
    )
    response_etag = result_etag(result)
    response_last_modified = result_last_modified(result)
    if (
        response_etag is not None
        and cached_etag is not None
        and response_etag != cached_etag
    ) or (
        response_last_modified is not None
        and cached_last_modified is not None
        and response_last_modified != cached_last_modified
    ):
        _raise_cache_failure(
            "CACHE_VALIDATOR_INVALID",
            "Upstream returned a validator that does not match cached bytes.",
            {
                "etag_sent": sent_etag,
                "etag_received": response_etag,
                "last_modified_sent": sent_last_modified,
                "last_modified_received": response_last_modified,
            },
        )
    if not any(
        (
            response_etag,
            response_last_modified,
            cached_etag,
            cached_last_modified,
        ),
    ):
        _raise_cache_failure(
            "CACHE_VALIDATOR_INVALID",
            "Upstream returned 304 without a returned or known validator.",
        )
    body = raw.decode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    return FetchResult(
        body=body,
        status_code=NOT_MODIFIED,
        headers=dict(result_headers(result)),
        fetched_at=result_fetched_at(result),
        final_url=result_final_url(result),
        last_modified=response_last_modified or cached_last_modified,
        sha256=digest,
        byte_length=len(raw),
        artifact_ref=(
            str(record.get("raw_path")) if record.get("raw_path") is not None else None
        ),
    )


def _raise_cache_failure(
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> NoReturn:
    raise CacheError(code, message, details)
