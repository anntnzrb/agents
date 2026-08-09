from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext

_CONDITION_ID = re.compile(r"^0x[0-9a-fA-F]{64}$")
_MAX_DETAIL_KEYS = 8
_MAX_DETAIL_TEXT = 120
_MAX_DEPTH = 100


class ContractError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        bounded_details: dict[str, object] = {}
        if details is not None:
            for key, value in details.items():
                if len(bounded_details) >= _MAX_DETAIL_KEYS:
                    break
                if not isinstance(key, str):
                    continue
                bounded_key = key[:_MAX_DETAIL_TEXT]
                if isinstance(value, (type(None), bool, int)):
                    safe_value: object = value
                elif isinstance(value, float) and math.isfinite(value):
                    safe_value = value
                elif isinstance(value, str):
                    safe_value = value[:_MAX_DETAIL_TEXT]
                else:
                    safe_value = type(value).__name__[:_MAX_DETAIL_TEXT]
                bounded_details[bounded_key] = safe_value
        bounded_code = (
            code[:_MAX_DETAIL_TEXT] if isinstance(code, str) else "contract_error"
        )
        bounded_message = (
            message[:_MAX_DETAIL_TEXT] if isinstance(message, str) else "contract error"
        )
        super().__init__(bounded_message)
        self.code = bounded_code
        self.message = bounded_message
        self.details = bounded_details


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__[:_MAX_DETAIL_TEXT]


def _path(field: str, part: str | int) -> str:
    text = f"{field}.{part}" if isinstance(part, str) else f"{field}[{part}]"
    return text[:_MAX_DETAIL_TEXT]


def _error(
    code: str,
    message: str,
    *,
    field: str,
    expected: str,
    value: object = None,
    index: int | None = None,
) -> ContractError:
    details: dict[str, object] = {
        "field": field[:_MAX_DETAIL_TEXT],
        "expected": expected[:_MAX_DETAIL_TEXT],
        "actual_type": _type_name(value),
    }
    if index is not None:
        details["index"] = index
    return ContractError(code, message, details)


def _clone_json(value: object, *, field: str, depth: int = 0) -> object:
    if depth > _MAX_DEPTH:
        raise _error(
            "malformed_payload",
            f"{field} is too deeply nested",
            field=field,
            expected="JSON value",
            value=value,
        )
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(
                "invalid_numeric",
                f"{field} must be finite",
                field=field,
                expected="finite JSON number",
                value=value,
            )
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error(
                    "malformed_payload",
                    f"{field} has a non-string key",
                    field=field,
                    expected="JSON object with string keys",
                    value=key,
                )
            result[key] = _clone_json(item, field=_path(field, key), depth=depth + 1)
        return result
    if isinstance(value, list):
        return [
            _clone_json(item, field=_path(field, index), depth=depth + 1)
            for index, item in enumerate(value)
        ]
    raise _error(
        "malformed_payload",
        f"{field} is not JSON-safe",
        field=field,
        expected="JSON value",
        value=value,
    )


def _object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _error(
            "malformed_payload",
            f"{field} must be an object",
            field=field,
            expected="object",
            value=value,
        )
    cloned = _clone_json(value, field=field)
    if not isinstance(cloned, dict):
        raise _error(
            "malformed_payload",
            f"{field} must be an object",
            field=field,
            expected="object",
            value=value,
        )
    return cloned


def _required(obj: Mapping[str, object], key: str, *, field: str) -> object:
    if key not in obj:
        raise _error(
            "missing_field",
            f"{field} is required",
            field=field,
            expected="present field",
        )
    return obj[key]


def _required_string(
    obj: Mapping[str, object],
    key: str,
    *,
    field: str,
    allow_empty: bool = False,
) -> str:
    value = _required(obj, key, field=field)
    if not isinstance(value, str):
        raise _error(
            "invalid_field",
            f"{field} must be a string",
            field=field,
            expected="string",
            value=value,
        )
    if not allow_empty and not value:
        raise _error(
            "invalid_field",
            f"{field} must not be empty",
            field=field,
            expected="non-empty string",
            value=value,
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _error(
            "invalid_field",
            f"{field} contains a control character",
            field=field,
            expected="string without control characters",
            value=value,
        )
    return value


def _required_array(obj: Mapping[str, object], key: str, *, field: str) -> list[object]:
    value = _required(obj, key, field=field)
    if not isinstance(value, list):
        raise _error(
            "invalid_field",
            f"{field} must be an array",
            field=field,
            expected="array",
            value=value,
        )
    return value


def _optional_array(
    obj: Mapping[str, object], key: str, *, field: str
) -> list[object] | None:
    if key not in obj:
        return None
    value = obj[key]
    if not isinstance(value, list):
        raise _error(
            "invalid_field",
            f"{field} must be an array",
            field=field,
            expected="array",
            value=value,
        )
    return value


def _condition_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _CONDITION_ID.fullmatch(value) is None:
        raise _error(
            "invalid_identifier",
            f"{field} must be a 0x-prefixed 64-hex condition ID",
            field=field,
            expected="^0x[0-9a-fA-F]{64}$",
            value=value,
        )
    return value


def _token_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _error(
            "invalid_identifier",
            f"{field} must be a non-empty token ID",
            field=field,
            expected="non-empty string",
            value=value,
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _error(
            "invalid_identifier",
            f"{field} contains a control character",
            field=field,
            expected="token ID without control characters",
            value=value,
        )
    return value


def _finite_number(
    value: object,
    *,
    field: str,
    index: int | None = None,
    nonnegative: bool = False,
) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(
            "invalid_numeric",
            f"{field} must be a number",
            field=field,
            expected="finite number",
            value=value,
            index=index,
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise _error(
            "invalid_numeric",
            f"{field} must be finite",
            field=field,
            expected="finite number",
            value=value,
            index=index,
        )
    if nonnegative and value < 0:
        raise _error(
            "invalid_numeric",
            f"{field} must not be negative",
            field=field,
            expected="finite non-negative number",
            value=value,
            index=index,
        )
    return value


def _decimal_number(
    value: object,
    *,
    field: str,
    index: int | None = None,
    nonnegative: bool = False,
    strings: bool = True,
    numbers: bool = True,
) -> Decimal:
    if isinstance(value, bool):
        raise _error(
            "invalid_numeric",
            f"{field} must be numeric",
            field=field,
            expected="finite decimal",
            value=value,
            index=index,
        )
    if isinstance(value, str):
        if not strings or not value or value.strip() != value:
            raise _error(
                "invalid_numeric",
                f"{field} must be a finite decimal",
                field=field,
                expected="finite decimal string",
                value=value,
                index=index,
            )
        source: object = value
    elif isinstance(value, (int, float)):
        if not numbers or (isinstance(value, float) and not math.isfinite(value)):
            raise _error(
                "invalid_numeric",
                f"{field} must be a finite decimal",
                field=field,
                expected="finite decimal",
                value=value,
                index=index,
            )
        source = str(value)
    else:
        raise _error(
            "invalid_numeric",
            f"{field} must be numeric",
            field=field,
            expected="finite decimal",
            value=value,
            index=index,
        )
    try:
        decimal = Decimal(source)
    except (InvalidOperation, ValueError):
        raise _error(
            "invalid_numeric",
            f"{field} must be a finite decimal",
            field=field,
            expected="finite decimal",
            value=value,
            index=index,
        ) from None
    if not decimal.is_finite():
        raise _error(
            "invalid_numeric",
            f"{field} must be finite",
            field=field,
            expected="finite decimal",
            value=value,
            index=index,
        )
    if nonnegative and decimal < 0:
        raise _error(
            "invalid_numeric",
            f"{field} must not be negative",
            field=field,
            expected="finite non-negative decimal",
            value=value,
            index=index,
        )
    return decimal


def _integer(value: object, *, field: str, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(
            "invalid_timestamp",
            f"{field} must be an integer",
            field=field,
            expected="integer",
            value=value,
        )
    if nonnegative and value < 0:
        raise _error(
            "invalid_timestamp",
            f"{field} must not be negative",
            field=field,
            expected="non-negative integer",
            value=value,
        )
    return value


def _numeric_text(value: object, *, field: str, nonnegative: bool = False) -> str:
    text = _required_string({"value": value}, "value", field=field)
    _decimal_number(text, field=field, nonnegative=nonnegative)
    return text


def _decode_array(value: object, *, field: str) -> list[object]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        raise _error(
            "invalid_field",
            f"{field} must be an array or encoded JSON array",
            field=field,
            expected="array or JSON array string",
            value=value,
        )
    try:
        decoded = json.loads(
            value, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token))
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        raise _error(
            "invalid_field",
            f"{field} contains malformed JSON",
            field=field,
            expected="JSON array string",
            value=value,
        ) from None
    if not isinstance(decoded, list):
        raise _error(
            "invalid_field",
            f"{field} must decode to an array",
            field=field,
            expected="JSON array",
            value=decoded,
        )
    return decoded


def _add_derived(
    result: dict[str, object], key: str, value: object, *, field: str
) -> None:
    existing = result.get("derived")
    if existing is None and "derived" not in result:
        derived: dict[str, object] = {}
    elif isinstance(existing, Mapping):
        derived = dict(existing)
    else:
        raise _error(
            "invalid_field",
            f"{field}.derived must be an object",
            field=f"{field}.derived",
            expected="object",
            value=existing,
        )
    derived[key] = value
    result["derived"] = derived


def _normalize_outcome_associations(result: dict[str, object], *, field: str) -> None:
    fields = ("outcomes", "outcomePrices", "clobTokenIds")
    present = [name for name in fields if name in result]
    if not present:
        return
    if len(present) != len(fields):
        missing = next(name for name in fields if name not in result)
        raise _error(
            "missing_field",
            f"{field}.{missing} is required when outcome fields are present",
            field=f"{field}.{missing}",
            expected="outcome triplet",
        )
    outcomes = _decode_array(result["outcomes"], field=f"{field}.outcomes")
    prices = _decode_array(result["outcomePrices"], field=f"{field}.outcomePrices")
    tokens = _decode_array(result["clobTokenIds"], field=f"{field}.clobTokenIds")
    for index, label in enumerate(outcomes):
        if not isinstance(label, str) or not label:
            raise _error(
                "invalid_field",
                f"{field}.outcomes[{index}] must be a non-empty string",
                field=f"{field}.outcomes[{index}]",
                expected="non-empty string",
                value=label,
                index=index,
            )
    for index, price in enumerate(prices):
        _decimal_number(
            price,
            field=f"{field}.outcomePrices[{index}]",
            index=index,
            nonnegative=True,
        )
    for index, token in enumerate(tokens):
        _token_id(token, field=f"{field}.clobTokenIds[{index}]")
    if not (len(outcomes) == len(prices) == len(tokens)):
        raise _error(
            "inconsistent_arrays",
            f"{field} outcome arrays must have equal lengths",
            field=field,
            expected="equal-length outcome arrays",
        )
    associations: list[dict[str, object]] = []
    for index, (label, price, token) in enumerate(
        zip(outcomes, prices, tokens, strict=True)
    ):
        associations.append(
            {
                "outcome_index": index,
                "label": label,
                "token_id": _token_id(token, field=f"{field}.clobTokenIds[{index}]"),
                "price": price,
            }
        )
    _add_derived(result, "outcome_associations", associations, field=field)


def normalize_market(raw: object) -> dict[str, object]:
    result = _object(raw, field="market")
    if "conditionId" in result:
        _condition_id(result["conditionId"], field="market.conditionId")
    _normalize_outcome_associations(result, field="market")
    return result


def normalize_event(raw: object) -> dict[str, object]:
    result = _object(raw, field="event")
    if "conditionId" in result:
        _condition_id(result["conditionId"], field="event.conditionId")
    if "markets" in result:
        markets = _required_array(result, "markets", field="event.markets")
        result["markets"] = [normalize_market(item) for item in markets]
    return result


def normalize_markets_payload(payload: object) -> dict[str, object]:
    result = _object(payload, field="markets_payload")
    markets = _required_array(result, "markets", field="markets_payload.markets")
    result["markets"] = [normalize_market(item) for item in markets]
    if "next_cursor" in result:
        _required_string(result, "next_cursor", field="markets_payload.next_cursor")
    return result


def normalize_events_payload(payload: object) -> dict[str, object]:
    result = _object(payload, field="events_payload")
    events = _required_array(result, "events", field="events_payload.events")
    result["events"] = [normalize_event(item) for item in events]
    if "next_cursor" in result:
        _required_string(result, "next_cursor", field="events_payload.next_cursor")
    return result


def normalize_search_payload(payload: object) -> dict[str, object]:
    source = _object(payload, field="search_payload")
    result = {key: value for key, value in source.items() if key != "profiles"}
    if "events" in source and source["events"] is not None:
        events = _optional_array(source, "events", field="search_payload.events")
        if events is None:
            raise _error(
                "invalid_field",
                "search_payload.events must be an array or null",
                field="search_payload.events",
                expected="array or null",
                value=source["events"],
            )
        result["events"] = [normalize_event(item) for item in events]
    if "tags" in source and source["tags"] is not None:
        tags = _optional_array(source, "tags", field="search_payload.tags")
        if tags is None:
            raise _error(
                "invalid_field",
                "search_payload.tags must be an array or null",
                field="search_payload.tags",
                expected="array or null",
                value=source["tags"],
            )
        normalized_tags: list[dict[str, object]] = []
        for index, tag in enumerate(tags):
            normalized_tags.append(_object(tag, field=f"search_payload.tags[{index}]"))
        result["tags"] = normalized_tags
    if "pagination" in source:
        raw_pagination = source["pagination"]
        if raw_pagination is None:
            result["pagination"] = None
        elif isinstance(raw_pagination, Mapping):
            # Keep provider pagination fields as data; CLI coverage decides
            # whether the hasMore/totalResults pair is complete enough.
            result["pagination"] = dict(raw_pagination)
        else:
            # A malformed pagination root makes coverage incomplete, not the
            # event/tag result unusable.
            result["pagination"] = raw_pagination
    return result


def normalize_market_by_token(raw: object) -> dict[str, object]:
    result = _object(raw, field="market_by_token")
    condition_id = _required(
        result, "condition_id", field="market_by_token.condition_id"
    )
    _condition_id(condition_id, field="market_by_token.condition_id")
    _token_id(
        _required(result, "primary_token_id", field="market_by_token.primary_token_id"),
        field="market_by_token.primary_token_id",
    )
    _token_id(
        _required(
            result, "secondary_token_id", field="market_by_token.secondary_token_id"
        ),
        field="market_by_token.secondary_token_id",
    )
    return result


def normalize_clob_market_info(raw: object) -> dict[str, object]:
    result = _object(raw, field="clob_market_info")
    tokens = _required_array(result, "t", field="clob_market_info.t")
    associations: list[dict[str, str]] = []
    normalized_tokens: list[dict[str, object]] = []
    for index, token in enumerate(tokens):
        normalized = _object(token, field=f"clob_market_info.t[{index}]")
        token_id = _token_id(
            _required(normalized, "t", field=f"clob_market_info.t[{index}].t"),
            field=f"clob_market_info.t[{index}].t",
        )
        outcome = _required_string(
            normalized,
            "o",
            field=f"clob_market_info.t[{index}].o",
        )
        normalized_tokens.append(normalized)
        associations.append({"token_id": token_id, "outcome": outcome})
    result["t"] = normalized_tokens
    _add_derived(result, "token_outcomes", associations, field="clob_market_info")
    return result


def _normalize_book_side(raw: object, *, field: str) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        raise _error(
            "invalid_field",
            f"{field} must be an array",
            field=field,
            expected="array",
            value=raw,
        )
    normalized_levels: list[dict[str, object]] = []
    for index, level in enumerate(raw):
        item = _object(level, field=f"{field}[{index}]")
        price = _required_string(item, "price", field=f"{field}[{index}].price")
        size = _required_string(item, "size", field=f"{field}[{index}].size")
        _decimal_number(
            price,
            field=f"{field}[{index}].price",
            index=index,
            nonnegative=True,
        )
        _decimal_number(
            size,
            field=f"{field}[{index}].size",
            index=index,
            nonnegative=True,
        )
        item["price"] = price
        item["size"] = size
        normalized_levels.append(item)
    return normalized_levels


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value, "f")


def normalize_orderbook(raw: object) -> dict[str, object]:
    result = _object(raw, field="orderbook")
    market = _required(result, "market", field="orderbook.market")
    _condition_id(market, field="orderbook.market")
    _token_id(
        _required(result, "asset_id", field="orderbook.asset_id"),
        field="orderbook.asset_id",
    )
    timestamp = _required_string(result, "timestamp", field="orderbook.timestamp")
    if not timestamp.isascii() or not timestamp.isdigit():
        raise _error(
            "invalid_timestamp",
            "orderbook.timestamp must be a Unix-second integer string",
            field="orderbook.timestamp",
            expected="non-negative integer string",
            value=timestamp,
        )
    _required_string(result, "hash", field="orderbook.hash")
    bids = _normalize_book_side(
        _required(result, "bids", field="orderbook.bids"),
        field="orderbook.bids",
    )
    asks = _normalize_book_side(
        _required(result, "asks", field="orderbook.asks"),
        field="orderbook.asks",
    )
    _numeric_text(
        _required(result, "min_order_size", field="orderbook.min_order_size"),
        field="orderbook.min_order_size",
        nonnegative=True,
    )
    _numeric_text(
        _required(result, "tick_size", field="orderbook.tick_size"),
        field="orderbook.tick_size",
        nonnegative=True,
    )
    if not isinstance(_required(result, "neg_risk", field="orderbook.neg_risk"), bool):
        raise _error(
            "invalid_field",
            "orderbook.neg_risk must be boolean",
            field="orderbook.neg_risk",
            expected="boolean",
            value=result["neg_risk"],
        )
    _numeric_text(
        _required(result, "last_trade_price", field="orderbook.last_trade_price"),
        field="orderbook.last_trade_price",
        nonnegative=True,
    )
    result["bids"] = bids
    result["asks"] = asks
    bid_values = [
        (_decimal_number(level["price"], field="orderbook.bids.price"), level["price"])
        for level in bids
    ]
    ask_values = [
        (_decimal_number(level["price"], field="orderbook.asks.price"), level["price"])
        for level in asks
    ]
    best_bid = max(bid_values, key=lambda value: value[0]) if bid_values else None
    best_ask = min(ask_values, key=lambda value: value[0]) if ask_values else None
    derived: dict[str, object] = {
        "best_bid": best_bid[1] if best_bid is not None else None,
        "best_ask": best_ask[1] if best_ask is not None else None,
        "spread": None,
        "midpoint": None,
    }
    if best_bid is not None and best_ask is not None:
        precision = (
            max(
                len(best_bid[0].as_tuple().digits),
                len(best_ask[0].as_tuple().digits),
                28,
            )
            + 4
        )
        with localcontext() as context:
            context.prec = precision
            derived["spread"] = _decimal_text(best_ask[0] - best_bid[0])
            derived["midpoint"] = _decimal_text(
                (best_ask[0] + best_bid[0]) / Decimal(2),
            )
    _add_derived(result, "best_bid", derived["best_bid"], field="orderbook")
    _add_derived(result, "best_ask", derived["best_ask"], field="orderbook")
    _add_derived(result, "spread", derived["spread"], field="orderbook")
    _add_derived(result, "midpoint", derived["midpoint"], field="orderbook")
    return result


def normalize_price(raw: object) -> dict[str, object]:
    result = _object(raw, field="price")
    _finite_number(
        _required(result, "price", field="price.price"),
        field="price.price",
        nonnegative=True,
    )
    return result


def normalize_midpoint(raw: object) -> dict[str, object]:
    result = _object(raw, field="midpoint")
    value = _required_string(result, "mid_price", field="midpoint.mid_price")
    _decimal_number(value, field="midpoint.mid_price", nonnegative=True)
    return result


def normalize_last_trade(raw: object) -> dict[str, object]:
    result = _object(raw, field="last_trade")
    value = _required_string(result, "price", field="last_trade.price")
    _decimal_number(value, field="last_trade.price", nonnegative=True)
    side = _required_string(result, "side", field="last_trade.side", allow_empty=True)
    if side not in {"BUY", "SELL", ""}:
        raise _error(
            "invalid_field",
            "last_trade.side must be BUY, SELL, or empty",
            field="last_trade.side",
            expected="BUY, SELL, or empty string",
            value=side,
        )
    return result


def normalize_price_history(raw: object) -> dict[str, object]:
    result = _object(raw, field="price_history")
    history = _required_array(result, "history", field="price_history.history")
    normalized: list[dict[str, object]] = []
    for index, point in enumerate(history):
        item = _object(point, field=f"price_history.history[{index}]")
        timestamp = _integer(
            _required(item, "t", field=f"price_history.history[{index}].t"),
            field=f"price_history.history[{index}].t",
            nonnegative=True,
        )
        price = _finite_number(
            _required(item, "p", field=f"price_history.history[{index}].p"),
            field=f"price_history.history[{index}].p",
            index=index,
            nonnegative=True,
        )
        item["t"] = timestamp
        item["p"] = price
        normalized.append(item)
    result["history"] = normalized
    return result


def normalize_live_volume(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        raise _error(
            "malformed_payload",
            "live_volume must be an array",
            field="live_volume",
            expected="array",
            value=raw,
        )
    normalized_rows: list[dict[str, object]] = []
    for index, row in enumerate(raw):
        item = _object(row, field=f"live_volume[{index}]")
        _finite_number(
            _required(item, "total", field=f"live_volume[{index}].total"),
            field=f"live_volume[{index}].total",
            index=index,
            nonnegative=True,
        )
        markets = _required_array(
            item, "markets", field=f"live_volume[{index}].markets"
        )
        normalized_markets: list[dict[str, object]] = []
        for market_index, market in enumerate(markets):
            market_item = _object(
                market,
                field=f"live_volume[{index}].markets[{market_index}]",
            )
            _condition_id(
                _required(
                    market_item,
                    "market",
                    field=f"live_volume[{index}].markets[{market_index}].market",
                ),
                field=f"live_volume[{index}].markets[{market_index}].market",
            )
            _finite_number(
                _required(
                    market_item,
                    "value",
                    field=f"live_volume[{index}].markets[{market_index}].value",
                ),
                field=f"live_volume[{index}].markets[{market_index}].value",
                index=market_index,
                nonnegative=True,
            )
            normalized_markets.append(market_item)
        item["markets"] = normalized_markets
        normalized_rows.append(item)
    return normalized_rows


def normalize_open_interest(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        raise _error(
            "malformed_payload",
            "open_interest must be an array",
            field="open_interest",
            expected="array",
            value=raw,
        )
    normalized_rows: list[dict[str, object]] = []
    for index, row in enumerate(raw):
        item = _object(row, field=f"open_interest[{index}]")
        _condition_id(
            _required(item, "market", field=f"open_interest[{index}].market"),
            field=f"open_interest[{index}].market",
        )
        _finite_number(
            _required(item, "value", field=f"open_interest[{index}].value"),
            field=f"open_interest[{index}].value",
            index=index,
            nonnegative=True,
        )
        normalized_rows.append(item)
    return normalized_rows


__all__ = [
    "ContractError",
    "normalize_clob_market_info",
    "normalize_event",
    "normalize_events_payload",
    "normalize_last_trade",
    "normalize_live_volume",
    "normalize_market",
    "normalize_market_by_token",
    "normalize_markets_payload",
    "normalize_midpoint",
    "normalize_open_interest",
    "normalize_orderbook",
    "normalize_price",
    "normalize_price_history",
    "normalize_search_payload",
]
