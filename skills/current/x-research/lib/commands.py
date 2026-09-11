"""Command dispatch: validate inputs, perform one provider request, normalize."""

from typing import Any, Literal, NotRequired, TypedDict

from contracts import (
    normalize_conversation_payload,
    normalize_page_payload,
    normalize_query,
    normalize_status_payload,
    status_id_from_target,
    validate_count,
    validate_cursor,
    validate_feed,
    validate_handle,
    validate_lang,
    validate_numeric_id,
    validate_provider,
    validate_ranking_mode,
)
from models import CliError, ContractError
from provider import FetchResult, FxTwitterClient


class FetchCommandInput(TypedDict):
    command: Literal["fetch"]
    target: str
    provider: NotRequired[str | None]
    lang: NotRequired[str | None]
    summary: NotRequired[bool]
    pretty: NotRequired[bool]


class UserPostsCommandInput(TypedDict):
    command: Literal["user-posts"]
    handle: str
    count: NotRequired[int | None]
    cursor: NotRequired[str | None]
    includeReplies: NotRequired[bool]
    summary: NotRequired[bool]
    pretty: NotRequired[bool]


class SearchCommandInput(TypedDict):
    command: Literal["search"]
    query: str
    count: NotRequired[int | None]
    feed: NotRequired[str | None]
    cursor: NotRequired[str | None]
    summary: NotRequired[bool]
    pretty: NotRequired[bool]


class ConversationCommandInput(TypedDict):
    command: Literal["conversation"]
    id: str
    rankingMode: NotRequired[str | None]
    cursor: NotRequired[str | None]
    summary: NotRequired[bool]
    pretty: NotRequired[bool]


type CommandInput = (
    FetchCommandInput
    | UserPostsCommandInput
    | SearchCommandInput
    | ConversationCommandInput
)


def _build_provenance(result: FetchResult) -> dict[str, Any]:
    status = (
        result["provider_status"]
        if result["provider_status"] is not None
        else result["http_status"]
    )
    return {
        "provider": "fxtwitter",
        "official": False,
        "auth_mode": "none",
        "source_url": result["source_url"],
        "endpoint": result["endpoint"],
        "fetched_at": result["fetched_at"],
        "provider_status": status,
    }


def _with_provenance(data: dict[str, Any], result: FetchResult) -> dict[str, Any]:
    return {**data, **_build_provenance(result)}


def _enrich_contract_error(error: ContractError, result: FetchResult) -> ContractError:
    details = dict(error.details)
    if "source_url" not in details:
        details["source_url"] = result["source_url"]
    if "endpoint" not in details:
        details["endpoint"] = result["endpoint"]
    status = (
        result["provider_status"]
        if result["provider_status"] is not None
        else result["http_status"]
    )
    if "provider_status" not in details:
        details["provider_status"] = status
    if "http_status" not in details:
        details["http_status"] = result["http_status"]
    return ContractError(code=error.code, message=error.message, details=details)


def _invalid_payload_error(message: str, result: FetchResult) -> ContractError:
    return ContractError(
        code="invalid_provider_payload",
        message=message,
        details={
            "source_url": result["source_url"],
            "endpoint": result["endpoint"],
            "http_status": result["http_status"],
            "provider_status": result["provider_status"]
            if result["provider_status"] is not None
            else result["http_status"],
        },
    )


def run_command(command_input: CommandInput, client: FxTwitterClient) -> dict[str, Any]:
    if command_input["command"] == "fetch":
        parsed_target = status_id_from_target(command_input["target"])
        post_id: str = parsed_target["id"]
        target_url = parsed_target.get("targetUrl")
        params: list[tuple[str, str]] = []
        lang = command_input.get("lang")
        if lang:
            validate_lang(lang)
            params.append(("lang", lang))
        provider = command_input.get("provider")
        if provider:
            validate_provider(provider)

        endpoint = f"/2/status/{post_id}"
        result = client.request_json(endpoint, params)

        try:
            normalized = normalize_status_payload(result["payload"])
        except ContractError as err:
            raise _enrich_contract_error(err, result) from err
        except Exception as err:
            raise _invalid_payload_error(
                "provider status normalization did not return an object", result
            ) from err

        data: dict[str, Any] = {"post": normalized["post"]}
        if target_url:
            data["requested_url"] = target_url
        else:
            data["requested_id"] = post_id
        return _with_provenance(data, result)

    if command_input["command"] == "user-posts":
        requested_count = command_input.get("count")
        if requested_count is None:
            requested_count = 20
        handle = validate_handle(command_input["handle"])
        count = validate_count(requested_count)
        params = [
            ("count", str(count)),
            ("groupthreads", "0"),
        ]
        cursor = command_input.get("cursor")
        if cursor:
            validate_cursor(cursor)
            params.append(("cursor", cursor))
        if command_input.get("includeReplies"):
            params.append(("with_replies", "1"))

        endpoint = f"/2/profile/{handle}/statuses"
        result = client.request_json(endpoint, params)

        try:
            page = normalize_page_payload(result["payload"], count)
        except ContractError as err:
            raise _enrich_contract_error(err, result) from err
        except Exception as err:
            raise _invalid_payload_error(
                "provider page normalization did not return an object", result
            ) from err

        data = {"handle": handle, **page}
        return _with_provenance(data, result)

    if command_input["command"] == "search":
        requested_count = command_input.get("count")
        if requested_count is None:
            requested_count = 30
        feed = command_input.get("feed")
        if feed is None:
            feed = "latest"
        query = normalize_query(command_input["query"])
        count = validate_count(requested_count)
        validate_feed(feed)
        params = [
            ("q", query),
            ("count", str(count)),
            ("feed", feed),
        ]
        cursor = command_input.get("cursor")
        if cursor:
            validate_cursor(cursor)
            params.append(("cursor", cursor))

        endpoint = "/2/search"
        result = client.request_json(endpoint, params)

        try:
            page = normalize_page_payload(result["payload"], count)
        except ContractError as err:
            raise _enrich_contract_error(err, result) from err
        except Exception as err:
            raise _invalid_payload_error(
                "provider search page normalization did not return an object",
                result,
            ) from err

        data = {"query": query, "feed": feed, **page}
        return _with_provenance(data, result)

    if command_input["command"] == "conversation":
        ranking_mode = command_input.get("rankingMode")
        if ranking_mode is None:
            ranking_mode = "likes"
        post_id = validate_numeric_id(command_input["id"])
        validate_ranking_mode(ranking_mode)
        params = [("ranking_mode", ranking_mode)]
        cursor = command_input.get("cursor")
        if cursor:
            validate_cursor(cursor)
            params.append(("cursor", cursor))

        endpoint = f"/2/conversation/{post_id}"
        result = client.request_json(endpoint, params)

        try:
            conv = normalize_conversation_payload(result["payload"])
        except ContractError as err:
            raise _enrich_contract_error(err, result) from err
        except Exception as err:
            raise _invalid_payload_error(
                "provider conversation normalization did not return an object",
                result,
            ) from err

        data = {
            "requested_id": post_id,
            "ranking_mode": ranking_mode,
            **conv,
        }
        return _with_provenance(data, result)

    raise CliError(
        code="usage",
        message=f"unknown command: {command_input['command']}",
        details={},
    )
