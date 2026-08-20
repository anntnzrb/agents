"""Read-only Polymarket public-data command line interface."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import NoReturn, TextIO
from urllib.parse import quote

from .contracts import (
    ContractError,
    normalize_clob_market_info,
    normalize_event,
    normalize_events_payload,
    normalize_last_trade,
    normalize_live_volume,
    normalize_market,
    normalize_market_by_token,
    normalize_markets_payload,
    normalize_midpoint,
    normalize_open_interest,
    normalize_orderbook,
    normalize_price,
    normalize_price_history,
    normalize_search_payload,
)
from .provider import DEFAULT_TIMEOUT, FetchResult, PolymarketClient, ProviderError

SCHEMA_VERSION = 1
_COMMANDS = frozenset(
    {
        "markets",
        "events",
        "search",
        "market",
        "event",
        "market-by-token",
        "market-info",
        "orderbook",
        "price",
        "midpoint",
        "last-trade",
        "price-history",
        "live-volume",
        "open-interest",
    }
)
_UNSUPPORTED_COMMANDS = frozenset(
    {
        "positions",
        "trades",
        "comments",
        "comment",
        "wallet",
        "profile",
        "profiles",
        "holders",
        "leaderboard",
        "history",
        "volume",
        "closed-positions",
        "market-positions",
        "v1/market-positions",
        "history/volume",
    }
)
_UNSUPPORTED_FLAG_NAMES = frozenset(
    {
        "--out",
        "--output",
        "--format",
        "--auth",
        "--authentication",
        "--credential",
        "--credentials",
        "--api-key",
        "--api-key-file",
        "--private-key",
        "--secret",
        "--password",
        "--cookie",
        "--cookies",
        "--wallet",
        "--signature",
        "--token",
        "--token-id",
        "--access-token",
        "--bearer-token",
        "--client-id",
        "--search-profiles",
    }
)
_POSITIVE_ID_RE = re.compile(r"^[0-9]+$")
_CONDITION_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
_CURSOR_RE = re.compile(r"^[A-Za-z0-9._~+/=-]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_DIAGNOSTIC = 240
_MAX_ERROR_TEXT = 160


def _bounded_text(value: object, limit: int = _MAX_ERROR_TEXT) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class CliError(RuntimeError):
    """An expected CLI failure rendered as a JSON envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        details: object | None = None,
        *,
        exit_code: int = 2,
    ) -> None:
        bounded_message = _bounded_text(message)
        super().__init__(bounded_message)
        self.code = _bounded_text(code)
        self.message = bounded_message
        self.details = {} if details is None else details
        self.exit_code = exit_code


class _ArgumentParser(argparse.ArgumentParser):
    """Argument parser that raises structured usage errors."""

    def error(self, message: str) -> NoReturn:
        raise CliError("usage", message, exit_code=2)


@dataclass(frozen=True, slots=True)
class _Prepared:
    provider: str
    endpoint: str
    params: tuple[tuple[str, str], ...]
    request: dict[str, object]
    normalize: Callable[[object], object]
    coverage: Callable[[object], dict[str, object]]


def _positive_int_arg(raw: str) -> int:
    if not _POSITIVE_ID_RE.fullmatch(raw):
        raise argparse.ArgumentTypeError("must be a positive integer")
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _nonnegative_int_arg(raw: str) -> int:
    if not _POSITIVE_ID_RE.fullmatch(raw):
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return int(raw)


def _bounded_int_arg(raw: str, *, minimum: int, maximum: int, label: str) -> int:
    if not _POSITIVE_ID_RE.fullmatch(raw):
        raise argparse.ArgumentTypeError(label)
    value = int(raw)
    if value < minimum or value > maximum:
        raise argparse.ArgumentTypeError(label)
    return value


def _limit_arg(raw: str) -> int:
    return _bounded_int_arg(raw, minimum=1, maximum=100, label="limit must be 1..100")


def _search_limit_arg(raw: str) -> int:
    return _bounded_int_arg(
        raw, minimum=1, maximum=50, label="limit-per-type must be 1..50"
    )


def _page_arg(raw: str) -> int:
    return _bounded_int_arg(raw, minimum=1, maximum=1000, label="page must be 1..1000")


def _timeout_arg(raw: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("timeout must be 1..60 seconds") from exc
    if not math.isfinite(value) or value < 1 or value > 60:
        raise argparse.ArgumentTypeError("timeout must be 1..60 seconds")
    return value


def _zero_one_arg(raw: str) -> int:
    if raw not in {"0", "1"}:
        raise argparse.ArgumentTypeError("must be 0 or 1")
    return int(raw)


def _add_shared_options(parser: argparse.ArgumentParser, *, root: bool = False) -> None:
    default_pretty: object = False if root else argparse.SUPPRESS
    default_timeout: object = DEFAULT_TIMEOUT if root else argparse.SUPPRESS
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=default_pretty,
        help="indent JSON output without changing values",
    )
    parser.add_argument(
        "--timeout",
        type=_timeout_arg,
        default=default_timeout,
        help="HTTP timeout in seconds (1..60)",
    )


def _add_bool_option(parser: argparse.ArgumentParser, name: str, dest: str) -> None:
    parser.add_argument(
        name,
        dest=dest,
        action=argparse.BooleanOptionalAction,
        default=None,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the exact public command grammar."""
    parser = _ArgumentParser(
        prog="polymarket-query",
        description="Read public Polymarket market data through official APIs.",
    )
    _add_shared_options(parser, root=True)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    markets = commands.add_parser("markets", help="list one bounded market page")
    _add_shared_options(markets)
    markets.add_argument("--limit", type=_limit_arg, default=20)
    markets.add_argument("--after-cursor")
    markets.add_argument("--order")
    _add_bool_option(markets, "--ascending", "ascending")
    _add_bool_option(markets, "--closed", "closed")
    markets.add_argument("--id", dest="ids", action="append")
    markets.add_argument("--slug", dest="slugs", action="append")
    markets.add_argument("--clob-token-id", dest="clob_token_ids", action="append")
    markets.add_argument("--condition-id", dest="condition_ids", action="append")
    markets.add_argument("--tag-id", dest="tag_ids", action="append")
    markets.add_argument("--liquidity-num-min")
    markets.add_argument("--liquidity-num-max")
    markets.add_argument("--volume-num-min")
    markets.add_argument("--volume-num-max")
    _add_bool_option(markets, "--decimalized", "decimalized")
    _add_bool_option(markets, "--related-tags", "related_tags")
    markets.add_argument("--tag-match")
    _add_bool_option(markets, "--include-tag", "include_tag")

    events = commands.add_parser("events", help="list one bounded event page")
    _add_shared_options(events)
    events.add_argument("--limit", type=_limit_arg, default=20)
    events.add_argument("--after-cursor")
    events.add_argument("--order")
    _add_bool_option(events, "--ascending", "ascending")
    _add_bool_option(events, "--closed", "closed")
    _add_bool_option(events, "--live", "live")
    _add_bool_option(events, "--featured", "featured")
    events.add_argument("--id", dest="ids", action="append")
    events.add_argument("--slug", dest="slugs", action="append")
    events.add_argument("--title-search")
    events.add_argument("--liquidity-min")
    events.add_argument("--liquidity-max")
    events.add_argument("--volume-min")
    events.add_argument("--volume-max")
    events.add_argument("--tag-id", dest="tag_ids", action="append")
    events.add_argument("--tag-slug")
    events.add_argument("--exclude-tag-id", dest="exclude_tag_ids", action="append")
    _add_bool_option(events, "--related-tags", "related_tags")
    events.add_argument("--tag-match")
    events.add_argument("--series-id", dest="series_ids", action="append")
    events.add_argument("--game-id", dest="game_ids", action="append")
    events.add_argument("--recurrence")
    events.add_argument("--event-date")
    events.add_argument("--event-week", type=_nonnegative_int_arg)

    search = commands.add_parser("search", help="search one bounded result page")
    _add_shared_options(search)
    search.add_argument("query")
    search.add_argument("--limit-per-type", type=_search_limit_arg, default=20)
    search.add_argument("--page", type=_page_arg, default=1)
    search.add_argument("--events-status")
    search.add_argument("--events-tag", dest="events_tags", action="append")
    search.add_argument("--keep-closed-markets", type=_zero_one_arg)
    search.add_argument("--sort")
    _add_bool_option(search, "--ascending", "ascending")
    _add_bool_option(search, "--search-tags", "search_tags")
    search.add_argument("--recurrence")
    search.add_argument("--exclude-tag-id", dest="exclude_tag_ids", action="append")
    _add_bool_option(search, "--optimized", "optimized")
    _add_bool_option(search, "--cache", "cache")

    market = commands.add_parser("market", help="get one market by ID or slug")
    _add_shared_options(market)
    market_keys = market.add_mutually_exclusive_group(required=True)
    market_keys.add_argument("--id")
    market_keys.add_argument("--slug")
    _add_bool_option(market, "--include-tag", "include_tag")

    event = commands.add_parser("event", help="get one event by ID or slug")
    _add_shared_options(event)
    event_keys = event.add_mutually_exclusive_group(required=True)
    event_keys.add_argument("--id")
    event_keys.add_argument("--slug")

    market_by_token = commands.add_parser(
        "market-by-token", help="get a market parent by explicit token ID"
    )
    _add_shared_options(market_by_token)
    market_by_token.add_argument("token_id")

    market_info = commands.add_parser(
        "market-info", help="get CLOB market information by condition ID"
    )
    _add_shared_options(market_info)
    market_info.add_argument("condition_id")

    orderbook = commands.add_parser("orderbook", help="get one token order book")
    _add_shared_options(orderbook)
    orderbook.add_argument("token_id")

    price = commands.add_parser("price", help="get the current price for one token")
    _add_shared_options(price)
    price.add_argument("token_id")
    price.add_argument("--side", choices=("BUY", "SELL"), required=True)

    midpoint = commands.add_parser("midpoint", help="get one token midpoint")
    _add_shared_options(midpoint)
    midpoint.add_argument("token_id")

    last_trade = commands.add_parser("last-trade", help="get one token last trade")
    _add_shared_options(last_trade)
    last_trade.add_argument("token_id")

    history = commands.add_parser(
        "price-history", help="get bounded token price history"
    )
    _add_shared_options(history)
    history.add_argument("token_id")
    history.add_argument(
        "--interval",
        choices=("max", "all", "1m", "1w", "1d", "6h", "1h"),
    )
    history.add_argument("--start-ts")
    history.add_argument("--end-ts")
    history.add_argument("--fidelity", type=_positive_int_arg)

    live_volume = commands.add_parser(
        "live-volume", help="get aggregate live volume for one event"
    )
    _add_shared_options(live_volume)
    live_volume.add_argument("event_id")

    open_interest = commands.add_parser(
        "open-interest", help="get aggregate open interest by condition ID"
    )
    _add_shared_options(open_interest)
    open_interest.add_argument(
        "--market", dest="markets", action="append", required=True
    )
    return parser


def _details_mapping(details: object) -> dict[str, object]:
    if isinstance(details, Mapping):
        return dict(details)
    return {"details": details}


def _error(
    code: str,
    message: str,
    details: object | None = None,
    *,
    exit_code: int = 2,
) -> CliError:
    return CliError(code, message, details, exit_code=exit_code)


def _validate_positive_id(raw: object, field: str) -> str:
    if not isinstance(raw, str) or _POSITIVE_ID_RE.fullmatch(raw) is None:
        raise _error(
            f"invalid_{field}", f"{field} must be a positive integer", {field: raw}
        )
    if int(raw) <= 0:
        raise _error(
            f"invalid_{field}", f"{field} must be a positive integer", {field: raw}
        )
    return raw


def _validate_slug(raw: object, field: str = "slug") -> str:
    if not isinstance(raw, str) or _SLUG_RE.fullmatch(raw) is None:
        raise _error(
            f"invalid_{field}",
            f"{field} must be a non-empty URL-safe path segment",
            {field: raw},
        )
    return raw


def _validate_token(raw: object, field: str = "token_id") -> str:
    if not isinstance(raw, str) or _TOKEN_RE.fullmatch(raw) is None:
        raise _error(
            f"invalid_{field}",
            f"{field} must be a non-empty URL-safe token ID",
            {field: raw},
        )
    return raw


def _validate_condition_id(raw: object, field: str = "condition_id") -> str:
    if not isinstance(raw, str) or _CONDITION_ID_RE.fullmatch(raw) is None:
        raise _error(
            f"invalid_{field}",
            f"{field} must be 0x followed by exactly 64 hexadecimal characters",
            {field: raw},
        )
    return raw


def _validate_cursor(raw: object) -> str:
    if not isinstance(raw, str) or _CURSOR_RE.fullmatch(raw) is None:
        raise _error(
            "invalid_cursor",
            "cursor must be a non-empty opaque URL-safe token",
            {"cursor": raw},
        )
    return raw


def _validate_query(raw: object) -> str:
    if (
        not isinstance(raw, str)
        or not raw
        or not raw.strip()
        or _CONTROL_RE.search(raw)
    ):
        raise _error(
            "invalid_query",
            "query must contain safe non-whitespace text",
            {"query": raw},
        )
    return " ".join(raw.split())


def _validate_component(raw: object, field: str) -> str:
    if (
        not isinstance(raw, str)
        or not raw
        or raw != raw.strip()
        or _CONTROL_RE.search(raw)
    ):
        raise _error(
            f"invalid_{field}", f"{field} must be a safe non-empty value", {field: raw}
        )
    if any(char in raw for char in "&#?"):
        raise _error(
            f"invalid_{field}", f"{field} contains a forbidden delimiter", {field: raw}
        )
    return raw


def _validate_number(raw: object, field: str, *, nonnegative: bool = True) -> str:
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise _error(
            f"invalid_{field}", f"{field} must be a finite number", {field: raw}
        )
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise _error(
            f"invalid_{field}", f"{field} must be a finite number", {field: raw}
        ) from None
    if not value.is_finite() or (nonnegative and value < 0):
        raise _error(
            f"invalid_{field}", f"{field} must be a finite number", {field: raw}
        )
    return raw


def _validate_list(
    values: object, validator: Callable[[object], str], field: str
) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise _error(f"invalid_{field}", f"{field} must be a list", {field: values})
    return [validator(value) for value in values]


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"


def _append_param(
    params: list[tuple[str, str]], key: str, value: object, *, allow_false: bool = True
) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        if not allow_false and value is False:
            return
        params.append((key, _bool_text(value)))
        return
    params.append((key, str(value)))


def _append_many(
    params: list[tuple[str, str]], key: str, values: Sequence[str]
) -> None:
    params.extend((key, value) for value in values)


def _path_segment(value: str) -> str:
    return quote(value, safe="")


def _prepare_markets(args: argparse.Namespace) -> _Prepared:
    limit = args.limit
    cursor = (
        _validate_cursor(args.after_cursor) if args.after_cursor is not None else None
    )
    slugs = _validate_list(args.slugs, _validate_slug, "slug")
    ids = _validate_list(
        args.ids, lambda value: _validate_positive_id(value, "id"), "id"
    )
    token_ids = _validate_list(args.clob_token_ids, _validate_token, "clob_token_id")
    condition_ids = _validate_list(
        args.condition_ids, _validate_condition_id, "condition_id"
    )
    tag_ids = _validate_list(
        args.tag_ids, lambda value: _validate_positive_id(value, "tag_id"), "tag_id"
    )
    params: list[tuple[str, str]] = [("limit", str(limit))]
    _append_param(
        params,
        "order",
        _validate_component(args.order, "order") if args.order is not None else None,
    )
    _append_param(params, "ascending", args.ascending)
    _append_param(params, "after_cursor", cursor)
    _append_many(params, "id", ids)
    _append_many(params, "slug", slugs)
    _append_many(params, "clob_token_ids", token_ids)
    _append_many(params, "condition_ids", condition_ids)
    _append_many(params, "tag_id", tag_ids)
    for attr, wire in (
        ("liquidity_num_min", "liquidity_num_min"),
        ("liquidity_num_max", "liquidity_num_max"),
        ("volume_num_min", "volume_num_min"),
        ("volume_num_max", "volume_num_max"),
    ):
        value = getattr(args, attr)
        _append_param(
            params, wire, _validate_number(value, attr) if value is not None else None
        )
    _append_param(params, "closed", args.closed)
    _append_param(params, "decimalized", args.decimalized)
    _append_param(params, "related_tags", args.related_tags)
    _append_param(
        params,
        "tag_match",
        _validate_component(args.tag_match, "tag_match")
        if args.tag_match is not None
        else None,
    )
    _append_param(params, "include_tag", args.include_tag)
    request: dict[str, object] = {"limit": limit}
    if cursor is not None:
        request["after_cursor"] = cursor
    for key, value in (
        ("order", args.order),
        ("ascending", args.ascending),
        ("closed", args.closed),
        ("decimalized", args.decimalized),
        ("related_tags", args.related_tags),
        ("tag_match", args.tag_match),
        ("include_tag", args.include_tag),
    ):
        if value is not None:
            request[key] = value
    for key, values in (
        ("id", ids),
        ("slug", slugs),
        ("clob_token_ids", token_ids),
        ("condition_ids", condition_ids),
        ("tag_id", tag_ids),
    ):
        if values:
            request[key] = values
    for attr in (
        "liquidity_num_min",
        "liquidity_num_max",
        "volume_num_min",
        "volume_num_max",
    ):
        value = getattr(args, attr)
        if value is not None:
            request[attr] = value
    return _Prepared(
        "gamma",
        "/markets/keyset",
        tuple(params),
        request,
        normalize_markets_payload,
        lambda value: _keyset_coverage(value, limit, cursor, "markets"),
    )


def _prepare_events(args: argparse.Namespace) -> _Prepared:
    limit = args.limit
    cursor = (
        _validate_cursor(args.after_cursor) if args.after_cursor is not None else None
    )
    slugs = _validate_list(args.slugs, _validate_slug, "slug")
    ids = _validate_list(
        args.ids, lambda value: _validate_positive_id(value, "id"), "id"
    )
    tag_ids = _validate_list(
        args.tag_ids, lambda value: _validate_positive_id(value, "tag_id"), "tag_id"
    )
    exclude_tag_ids = _validate_list(
        args.exclude_tag_ids,
        lambda value: _validate_positive_id(value, "exclude_tag_id"),
        "exclude_tag_id",
    )
    series_ids = _validate_list(
        args.series_ids,
        lambda value: _validate_positive_id(value, "series_id"),
        "series_id",
    )
    game_ids = _validate_list(
        args.game_ids, lambda value: _validate_component(value, "game_id"), "game_id"
    )
    params: list[tuple[str, str]] = [("limit", str(limit))]
    _append_param(
        params,
        "order",
        _validate_component(args.order, "order") if args.order is not None else None,
    )
    _append_param(params, "ascending", args.ascending)
    _append_param(params, "after_cursor", cursor)
    _append_many(params, "id", ids)
    _append_many(params, "slug", slugs)
    for attr, wire in (
        ("closed", "closed"),
        ("live", "live"),
        ("featured", "featured"),
        ("related_tags", "related_tags"),
    ):
        _append_param(params, wire, getattr(args, attr))
    for attr, wire in (
        ("title_search", "title_search"),
        ("tag_slug", "tag_slug"),
        ("tag_match", "tag_match"),
        ("recurrence", "recurrence"),
        ("event_date", "event_date"),
    ):
        value = getattr(args, attr)
        _append_param(
            params,
            wire,
            _validate_component(value, attr) if value is not None else None,
        )
    for attr, wire in (
        ("liquidity_min", "liquidity_min"),
        ("liquidity_max", "liquidity_max"),
        ("volume_min", "volume_min"),
        ("volume_max", "volume_max"),
    ):
        value = getattr(args, attr)
        _append_param(
            params, wire, _validate_number(value, attr) if value is not None else None
        )
    _append_many(params, "tag_id", tag_ids)
    _append_many(params, "exclude_tag_id", exclude_tag_ids)
    _append_many(params, "series_id", series_ids)
    _append_many(params, "game_id", game_ids)
    _append_param(params, "event_week", args.event_week)
    request: dict[str, object] = {"limit": limit}
    if cursor is not None:
        request["after_cursor"] = cursor
    for key, value in (
        ("order", args.order),
        ("ascending", args.ascending),
        ("closed", args.closed),
        ("live", args.live),
        ("featured", args.featured),
        ("related_tags", args.related_tags),
        ("title_search", args.title_search),
        ("tag_slug", args.tag_slug),
        ("tag_match", args.tag_match),
        ("recurrence", args.recurrence),
        ("event_date", args.event_date),
        ("event_week", args.event_week),
    ):
        if value is not None:
            request[key] = value
    for attr in ("liquidity_min", "liquidity_max", "volume_min", "volume_max"):
        value = getattr(args, attr)
        if value is not None:
            request[attr] = value
    for key, values in (
        ("id", ids),
        ("slug", slugs),
        ("tag_id", tag_ids),
        ("exclude_tag_id", exclude_tag_ids),
        ("series_id", series_ids),
        ("game_id", game_ids),
    ):
        if values:
            request[key] = values
    return _Prepared(
        "gamma",
        "/events/keyset",
        tuple(params),
        request,
        normalize_events_payload,
        lambda value: _keyset_coverage(value, limit, cursor, "events"),
    )


def _prepare_search(args: argparse.Namespace) -> _Prepared:
    query = _validate_query(args.query)
    limit = args.limit_per_type
    page = args.page
    events_tags = _validate_list(
        args.events_tags,
        lambda value: _validate_component(value, "events_tag"),
        "events_tag",
    )
    exclude_tag_ids = _validate_list(
        args.exclude_tag_ids,
        lambda value: _validate_positive_id(value, "exclude_tag_id"),
        "exclude_tag_id",
    )
    params: list[tuple[str, str]] = [
        ("q", query),
        ("limit_per_type", str(limit)),
        ("page", str(page)),
    ]
    for attr, wire in (
        ("cache", "cache"),
        ("ascending", "ascending"),
        ("search_tags", "search_tags"),
        ("optimized", "optimized"),
    ):
        _append_param(params, wire, getattr(args, attr))
    for attr, wire in (
        ("events_status", "events_status"),
        ("sort", "sort"),
        ("recurrence", "recurrence"),
    ):
        value = getattr(args, attr)
        _append_param(
            params,
            wire,
            _validate_component(value, attr) if value is not None else None,
        )
    _append_param(params, "keep_closed_markets", args.keep_closed_markets)
    _append_many(params, "events_tag", events_tags)
    _append_many(params, "exclude_tag_id", exclude_tag_ids)
    params.append(("search_profiles", "false"))
    request: dict[str, object] = {
        "q": query,
        "limit_per_type": limit,
        "page": page,
        "search_profiles": False,
    }
    for key, value in (
        ("cache", args.cache),
        ("events_status", args.events_status),
        ("sort", args.sort),
        ("ascending", args.ascending),
        ("search_tags", args.search_tags),
        ("recurrence", args.recurrence),
        ("keep_closed_markets", args.keep_closed_markets),
        ("optimized", args.optimized),
    ):
        if value is not None:
            request[key] = value
    if events_tags:
        request["events_tag"] = events_tags
    if exclude_tag_ids:
        request["exclude_tag_id"] = exclude_tag_ids
    return _Prepared(
        "gamma",
        "/public-search",
        tuple(params),
        request,
        normalize_search_payload,
        lambda value: _search_coverage(value, limit, page),
    )


def _prepare_lookup(args: argparse.Namespace, *, event: bool) -> _Prepared:
    command = "event" if event else "market"
    if args.id is not None:
        ident = _validate_positive_id(args.id, "id")
        endpoint = f"/{'events' if event else 'markets'}/{_path_segment(ident)}"
        request: dict[str, object] = {"id": ident}
    elif args.slug is not None:
        slug = _validate_slug(args.slug)
        endpoint = f"/{'events' if event else 'markets'}/slug/{_path_segment(slug)}"
        request = {"slug": slug}
    else:
        raise _error(
            "invalid_identifier", f"{command} requires exactly one of id or slug"
        )
    params: list[tuple[str, str]] = []
    if not event:
        _append_param(params, "include_tag", args.include_tag)
        if args.include_tag is not None:
            request["include_tag"] = args.include_tag
    return _Prepared(
        "gamma",
        endpoint,
        tuple(params),
        request,
        normalize_event if event else normalize_market,
        _single_coverage,
    )


def _prepare_token(args: argparse.Namespace, command: str) -> _Prepared:
    token = _validate_token(args.token_id)
    routes = {
        "market-by-token": (
            "clob",
            f"/markets-by-token/{_path_segment(token)}",
            normalize_market_by_token,
        ),
        "orderbook": ("clob", "/book", normalize_orderbook),
        "price": ("clob", "/price", normalize_price),
        "midpoint": ("clob", "/midpoint", normalize_midpoint),
        "last-trade": ("clob", "/last-trade-price", normalize_last_trade),
    }
    provider, endpoint, normalizer = routes[command]
    params: list[tuple[str, str]] = []
    request: dict[str, object] = {"token_id": token}
    if command != "market-by-token":
        params.append(("token_id", token))
    if command == "price":
        params.append(("side", args.side))
        request["side"] = args.side
    return _Prepared(
        provider, endpoint, tuple(params), request, normalizer, _single_coverage
    )


def _prepare_market_info(args: argparse.Namespace) -> _Prepared:
    condition_id = _validate_condition_id(args.condition_id)
    return _Prepared(
        "clob",
        f"/clob-markets/{_path_segment(condition_id)}",
        (),
        {"condition_id": condition_id},
        normalize_clob_market_info,
        _single_coverage,
    )


def _prepare_history(args: argparse.Namespace) -> _Prepared:
    token = _validate_token(args.token_id)
    start = args.start_ts
    end = args.end_ts
    if (start is None) != (end is None):
        raise _error(
            "invalid_history_range", "start-ts and end-ts must be supplied together"
        )
    if args.interval is not None and (start is not None or end is not None):
        raise _error(
            "invalid_history_range",
            "interval and absolute bounds are mutually exclusive",
        )
    if start is not None:
        start = _validate_number(start, "start_ts")
        end = _validate_number(end, "end_ts")
    params: list[tuple[str, str]] = [("market", token)]
    _append_param(params, "startTs", start)
    _append_param(params, "endTs", end)
    _append_param(params, "interval", args.interval)
    _append_param(params, "fidelity", args.fidelity)
    request: dict[str, object] = {"market": token}
    for key, value in (
        ("startTs", start),
        ("endTs", end),
        ("interval", args.interval),
        ("fidelity", args.fidelity),
    ):
        if value is not None:
            request[key] = value
    return _Prepared(
        "clob",
        "/prices-history",
        tuple(params),
        request,
        normalize_price_history,
        _single_coverage,
    )


def _prepare_live_volume(args: argparse.Namespace) -> _Prepared:
    event_id = _validate_positive_id(args.event_id, "event_id")
    return _Prepared(
        "data",
        "/live-volume",
        (("id", event_id),),
        {"id": event_id},
        normalize_live_volume,
        _single_coverage,
    )


def _prepare_open_interest(args: argparse.Namespace) -> _Prepared:
    values = _validate_list(args.markets, _validate_condition_id, "market")
    if not 1 <= len(values) <= 100:
        raise _error(
            "invalid_market",
            "open-interest accepts 1..100 condition IDs",
            {"count": len(values)},
        )
    joined = ",".join(values)
    return _Prepared(
        "data",
        "/oi",
        (("market", joined),),
        {"market": values},
        normalize_open_interest,
        _single_coverage,
    )


def _prepare(args: argparse.Namespace) -> _Prepared:
    command = args.command
    if command == "markets":
        return _prepare_markets(args)
    if command == "events":
        return _prepare_events(args)
    if command == "search":
        return _prepare_search(args)
    if command == "market":
        return _prepare_lookup(args, event=False)
    if command == "event":
        return _prepare_lookup(args, event=True)
    if command in {"market-by-token", "orderbook", "price", "midpoint", "last-trade"}:
        return _prepare_token(args, command)
    if command == "market-info":
        return _prepare_market_info(args)
    if command == "price-history":
        return _prepare_history(args)
    if command == "live-volume":
        return _prepare_live_volume(args)
    if command == "open-interest":
        return _prepare_open_interest(args)
    raise _error("unsupported_command", f"unsupported command: {command}")


def _keyset_coverage(
    value: object, requested: int, input_cursor: str | None, root: str
) -> dict[str, object]:
    if not isinstance(value, Mapping) or not isinstance(value.get(root), list):
        raise _error(
            "invalid_provider_payload",
            f"normalized {root} response has no list root",
            exit_code=1,
        )
    returned = len(value[root])
    output_cursor = value.get("next_cursor")
    has_more = output_cursor is not None
    return {
        "mode": "keyset",
        "requested_count": requested,
        "returned_count": returned,
        "input_cursor": input_cursor,
        "output_cursor": output_cursor,
        "has_more": has_more,
        "complete": not has_more,
        "complete_reason": "bounded_page" if has_more else "provider_exhausted",
    }


def _search_coverage(value: object, requested: int, page: int) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _error(
            "invalid_provider_payload",
            "normalized search response is not an object",
            exit_code=1,
        )
    events = value.get("events")
    tags = value.get("tags")
    returned_counts = {
        "events": len(events) if isinstance(events, list) else 0,
        "tags": len(tags) if isinstance(tags, list) else 0,
    }
    has_more: bool | None = None
    total_results: object = None
    pagination = value.get("pagination")
    if isinstance(pagination, Mapping):
        candidate_more = pagination.get("hasMore")
        candidate_total = pagination.get("totalResults")
        if (
            isinstance(candidate_more, bool)
            and isinstance(candidate_total, int)
            and not isinstance(candidate_total, bool)
            and candidate_total >= 0
        ):
            has_more = candidate_more
            total_results = candidate_total
    if has_more is True:
        complete: bool | None = False
        reason = "bounded_page"
    elif has_more is False:
        complete = True
        reason = "provider_exhausted"
    else:
        complete = None
        reason = "provider_incomplete"
    return {
        "mode": "search_page",
        "requested_limit_per_type": requested,
        "returned_counts": returned_counts,
        "input_page": page,
        "has_more": has_more,
        "total_results": total_results,
        "complete": complete,
        "complete_reason": reason,
    }


def _single_coverage(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        if isinstance(value.get("history"), list):
            returned = len(value["history"])
        else:
            returned = 1
    elif isinstance(value, list):
        returned = len(value)
    else:
        returned = None
    return {
        "mode": "single_response",
        "returned_count": returned,
        "complete": None,
        "complete_reason": "single_response_not_population_complete",
    }


def _provider_error_details(error: ProviderError) -> dict[str, object]:
    return _details_mapping(error.details)


def _contract_failure(error: ContractError, result: FetchResult) -> CliError:
    details = _details_mapping(error.details)
    details.setdefault("source_url", result.source_url)
    details.setdefault("endpoint", result.endpoint)
    details.setdefault("http_status", result.http_status)
    return _error(error.code, error.message, details, exit_code=1)


def _normalize(prepared: _Prepared, result: FetchResult) -> object:
    try:
        return prepared.normalize(result.payload)
    except ContractError as error:
        raise _contract_failure(error, result) from error


def _ensure_success(result: FetchResult) -> None:
    if 200 <= result.http_status < 300:
        return
    raise _error(
        "provider_http_error",
        f"provider returned HTTP {result.http_status}",
        {
            "http_status": result.http_status,
            "source_url": result.source_url,
            "endpoint": result.endpoint,
        },
        exit_code=1,
    )


def _provenance(provider: str, result: FetchResult) -> dict[str, object]:
    return {
        "provider": provider,
        "official": True,
        "auth_mode": "none",
        "source_url": result.source_url,
        "endpoint": result.endpoint,
        "http_status": result.http_status,
        "fetched_at": result.fetched_at,
    }


def _run(prepared: _Prepared, timeout: float) -> dict[str, object]:
    client = PolymarketClient(provider=prepared.provider, timeout=timeout)
    result = client.get(prepared.endpoint, prepared.params)
    _ensure_success(result)
    normalized = _normalize(prepared, result)
    coverage = prepared.coverage(normalized)
    return {
        "provenance": _provenance(prepared.provider, result),
        "request": prepared.request,
        "coverage": coverage,
        "result": normalized,
    }


def _command_hint(values: Sequence[str]) -> str:
    index = 0
    while index < len(values):
        value = values[index]
        if value == "--pretty":
            index += 1
            continue
        if value == "--timeout":
            index += 2
            continue
        if value.startswith("--timeout="):
            index += 1
            continue
        if value.startswith("-"):
            index += 1
            continue
        return value
    return "unknown"


def _preflight(values: Sequence[str]) -> None:
    for value in values:
        if not value.startswith("--"):
            continue
        name = value.split("=", 1)[0]
        if name in _UNSUPPORTED_FLAG_NAMES or name.startswith(
            (
                "--auth-",
                "--credential-",
                "--private-",
                "--secret-",
                "--password-",
                "--out-",
                "--output-",
                "--format-",
            )
        ):
            raise _error(
                "unsupported_command",
                f"unsupported option: {name}",
                {"option": name},
            )


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _bounded_text(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _error_safe(value: object, depth: int = 0) -> object:
    if depth > 4:
        return _bounded_text(type(value).__name__)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _bounded_text(value)
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, Mapping):
        return {
            _bounded_text(key): _error_safe(item, depth + 1)
            for index, (key, item) in enumerate(value.items())
            if index < 16
        }
    if isinstance(value, (list, tuple)):
        return [_error_safe(item, depth + 1) for item in value[:16]]
    return _bounded_text(value)


def _failure(command: str, error: CliError) -> dict[str, object]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": _error_safe(error.details),
        },
    }


def _success(command: str, data: Mapping[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "data": _json_safe(data),
    }


def _emit(value: object, stream: TextIO, *, pretty: bool) -> None:
    if pretty:
        text = json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
    else:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    print(text, file=stream)


def _diagnostic(command: str, error: CliError, stream: TextIO) -> None:
    text = " ".join(f"{command}: {error.code}: {error.message}".split())
    if len(text) > _MAX_DIAGNOSTIC:
        text = text[: _MAX_DIAGNOSTIC - 1] + "…"
    print(text, file=stream)


def main(
    argv: Sequence[str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse one command, perform one GET, and emit one JSON envelope."""
    del stdin
    values = list(sys.argv[1:] if argv is None else argv)
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    command = _command_hint(values)
    pretty = "--pretty" in values
    try:
        _preflight(values)
        if command in _UNSUPPORTED_COMMANDS:
            raise _error(
                "unsupported_command",
                f"unsupported command: {command}",
                {"command": command},
            )
        args = build_parser().parse_args(values)
        command = args.command
        pretty = bool(getattr(args, "pretty", pretty))
        prepared = _prepare(args)
        data = _run(prepared, args.timeout)
    except CliError as error:
        _emit(_failure(command, error), out, pretty=pretty)
        _diagnostic(command, error, err)
        return error.exit_code
    except ProviderError as error:
        cli_error = _error(
            error.code, error.message, _provider_error_details(error), exit_code=1
        )
        _emit(_failure(command, cli_error), out, pretty=pretty)
        _diagnostic(command, cli_error, err)
        return 1
    except ContractError as error:
        cli_error = _error(
            error.code, error.message, _details_mapping(error.details), exit_code=1
        )
        _emit(_failure(command, cli_error), out, pretty=pretty)
        _diagnostic(command, cli_error, err)
        return 1
    except Exception as error:  # noqa: BLE001
        cli_error = _error(
            "internal_error",
            "unexpected CLI failure",
            {"reason": str(error)},
            exit_code=1,
        )
        _emit(_failure(command, cli_error), out, pretty=pretty)
        _diagnostic(command, cli_error, err)
        return 1
    _emit(_success(command, data), out, pretty=pretty)
    return 0


__all__ = ["build_parser", "main"]
