"""Merge per-provider search payloads into one JSON envelope."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeGuard

if TYPE_CHECKING:
    from models import (
        SearchError,
        SearchFailurePayload,
        SearchResult,
        SearchSource,
        SearchSuccessPayload,
    )


def _is_success(result: SearchResult) -> TypeGuard[SearchSuccessPayload]:
    """Narrow a search result union to the success payload."""
    return result["ok"]


def _is_failure(result: SearchResult) -> TypeGuard[SearchFailurePayload]:
    """Narrow a search result union to the failure payload."""
    return not result["ok"]


def merge_parallel_results(
    fallback_query: str,
    results: list[SearchResult],
    compact: bool,
) -> SearchResult:
    """Merge parallel provider results; dedupe sources; join answers."""
    successful: list[SearchSuccessPayload] = []
    for r in results:
        if _is_success(r):
            successful.append(r)

    if not successful:
        first_error: SearchError = {
            "code": "all_providers_failed",
            "message": "All parallel providers failed",
        }
        for r in results:
            if _is_failure(r):
                first_error = r["error"]
                break

        failure_payload: SearchFailurePayload = {
            "ok": False,
            "query": fallback_query,
            "provider": " | ".join(r["provider"] or "unknown" for r in results),
            "providers": [r["provider"] or "unknown" for r in results],
            "providers_count": len(results),
            "answer": "",
            "sources": [],
            "sources_count": 0,
            "truncated": False,
            "compact": compact,
            "parsed": False,
            "error": first_error,
            "exit_code": 1,
        }
        return failure_payload

    merged_sources: list[SearchSource] = []
    seen_sources: set[str] = set()
    answer_sections: list[str] = []
    used_providers: list[str] = []

    for r in successful:
        prov = r["provider"] or "Unknown"
        used_providers.append(prov)
        ans = r["answer"].strip()
        if ans:
            answer_sections.append(f"### [{prov}]\n{ans}")

        for src in r["sources"]:
            title = src["title"].strip()
            domain = src["domain"].strip()
            key = f"{title.lower()}|{domain.lower()}"
            if key not in seen_sources:
                seen_sources.add(key)
                merged_sources.append(
                    {
                        "title": title,
                        "domain": domain,
                        "age": src.get("age"),
                    }
                )

    success_payload: SearchSuccessPayload = {
        "ok": True,
        "query": fallback_query,
        "provider": "+".join(used_providers),
        "providers": used_providers,
        "providers_count": len(used_providers),
        "answer": "\n\n".join(answer_sections),
        "sources": merged_sources,
        "sources_count": len(merged_sources),
        "truncated": any(r["truncated"] for r in successful),
        "compact": compact,
        "parsed": True,
        "exit_code": 0,
    }

    return success_payload
