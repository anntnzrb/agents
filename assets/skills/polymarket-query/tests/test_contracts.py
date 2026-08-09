"""Boundary tests for Polymarket provider response normalizers."""

from __future__ import annotations

import math
from collections.abc import Callable

import _path  # noqa: F401
import pytest
from polymarket_query.contracts import (
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

CONDITION_ID = "0x" + "a" * 64
OTHER_CONDITION_ID = "0x" + "b" * 64
TOKEN_YES = "token-yes"
TOKEN_NO = "token-no"


def _assert_contract_error(expected: str, call: Callable[[], object]) -> None:
    with pytest.raises(ContractError) as exc_info:
        call()
    assert exc_info.value.code == expected


def _triplet(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "conditionId": CONDITION_ID,
        "outcomes": ["No", "Yes"],
        "outcomePrices": ["0.63", "0.37"],
        "clobTokenIds": [TOKEN_NO, TOKEN_YES],
    }
    payload.update(overrides)
    return payload


def _book_payload(
    *,
    bids: object = None,
    asks: object = None,
    market: object = CONDITION_ID,
    asset_id: object = TOKEN_YES,
    timestamp: object = "1700000000",
) -> dict[str, object]:
    return {
        "market": market,
        "asset_id": asset_id,
        "timestamp": timestamp,
        "hash": "book-hash",
        "bids": [] if bids is None else bids,
        "asks": [] if asks is None else asks,
        "min_order_size": "0.01",
        "tick_size": "0.01",
        "neg_risk": False,
        "last_trade_price": "0.15",
    }


def test_gamma_outcome_triplets_accept_encoded_and_array_forms_in_wire_order() -> None:
    cases = (
        (
            {
                "outcomes": '["No", "Yes"]',
                "outcomePrices": '["0.63", "0.37"]',
                "clobTokenIds": '["token-no", "token-yes"]',
            },
            [
                {
                    "outcome_index": 0,
                    "label": "No",
                    "token_id": TOKEN_NO,
                    "price": "0.63",
                },
                {
                    "outcome_index": 1,
                    "label": "Yes",
                    "token_id": TOKEN_YES,
                    "price": "0.37",
                },
            ],
        ),
        (
            {
                "outcomes": ["Yes", "No"],
                "outcomePrices": [0.37, 0.63],
                "clobTokenIds": [TOKEN_YES, TOKEN_NO],
            },
            [
                {
                    "outcome_index": 0,
                    "label": "Yes",
                    "token_id": TOKEN_YES,
                    "price": 0.37,
                },
                {
                    "outcome_index": 1,
                    "label": "No",
                    "token_id": TOKEN_NO,
                    "price": 0.63,
                },
            ],
        ),
    )
    for fields, expected_associations in cases:
        raw = _triplet(**fields)
        # Keep the additive extension separate from the triplet fields; the
        # normalizer must not infer labels from position or rewrite source fields.
        raw["vendorExtension"] = {"source": "gamma", "nested": [1, True]}
        normalized = normalize_market(raw)

        assert normalized["outcomes"] == fields["outcomes"]
        assert normalized["outcomePrices"] == fields["outcomePrices"]
        assert normalized["clobTokenIds"] == fields["clobTokenIds"]
        assert normalized["vendorExtension"] == {"source": "gamma", "nested": [1, True]}
        assert normalized["derived"] == {"outcome_associations": expected_associations}
        assert "derived" not in raw


def test_gamma_outcome_triplets_reject_missing_mismatched_malformed_and_nonfinite_arrays() -> (
    None
):
    missing = _triplet()
    del missing["clobTokenIds"]
    cases = (
        (missing, "missing_field"),
        (_triplet(outcomePrices=["0.5"]), "inconsistent_arrays"),
        (_triplet(outcomes='["Yes"'), "invalid_field"),
        (_triplet(outcomePrices=["NaN"]), "invalid_numeric"),
        (_triplet(outcomePrices=[math.inf]), "invalid_numeric"),
    )
    for raw, expected in cases:
        _assert_contract_error(expected, lambda raw=raw: normalize_market(raw))


def test_event_and_collection_normalizers_preserve_additive_fields_and_nested_markets() -> (
    None
):
    market = _triplet(
        id=123,
        question="Nested question",
        vendorExtension={"market_flag": True},
    )
    event = {
        "id": 456,
        "conditionId": OTHER_CONDITION_ID,
        "title": "Event title",
        "markets": [market],
        "eventExtension": {"nested": {"keep": "me"}},
    }

    normalized_event = normalize_event(event)
    assert normalized_event["eventExtension"] == {"nested": {"keep": "me"}}
    assert normalized_event["markets"][0]["vendorExtension"] == {"market_flag": True}
    assert (
        normalized_event["markets"][0]["derived"]["outcome_associations"][0]["label"]
        == "No"
    )
    assert "derived" not in event["markets"][0]

    normalized_markets = normalize_markets_payload(
        {
            "markets": [market],
            "next_cursor": "opaque-cursor",
            "pageExtension": {"x": 1},
        },
    )
    assert normalized_markets["next_cursor"] == "opaque-cursor"
    assert normalized_markets["pageExtension"] == {"x": 1}
    assert normalized_markets["markets"][0]["id"] == 123

    normalized_events = normalize_events_payload(
        {"events": [event], "next_cursor": "opaque-events", "extra": "preserved"},
    )
    assert normalized_events["events"][0]["title"] == "Event title"
    assert normalized_events["extra"] == "preserved"


def test_search_normalizer_omits_profiles_but_preserves_event_tag_and_pagination_roots() -> (
    None
):
    payload = {
        "events": [{"id": 1, "title": "Event"}],
        "tags": [{"id": 9, "label": "Tag", "extension": "kept"}],
        "profiles": [{"username": "must-not-be-returned"}],
        "pagination": {"hasMore": True, "totalResults": 12, "extra": "kept"},
        "searchExtension": {"source": "gamma"},
    }

    normalized = normalize_search_payload(payload)

    assert normalized["events"] == [{"id": 1, "title": "Event"}]
    assert normalized["tags"] == [{"id": 9, "label": "Tag", "extension": "kept"}]
    assert normalized["pagination"] == {
        "hasMore": True,
        "totalResults": 12,
        "extra": "kept",
    }
    assert normalized["searchExtension"] == {"source": "gamma"}
    assert "profiles" not in normalized


def test_clob_market_info_keeps_raw_t_and_o_fields_and_derives_explicit_associations() -> (
    None
):
    raw = {
        "t": [
            {"t": TOKEN_YES, "o": "Yes", "tokenExtension": {"rank": 1}},
            {"t": TOKEN_NO, "o": "No", "tokenExtension": {"rank": 2}},
        ],
        "condition_id": CONDITION_ID,
        "clobExtension": "kept",
    }

    normalized = normalize_clob_market_info(raw)

    assert normalized["condition_id"] == CONDITION_ID
    assert normalized["clobExtension"] == "kept"
    assert normalized["t"] == raw["t"]
    assert normalized["derived"] == {
        "token_outcomes": [
            {"token_id": TOKEN_YES, "outcome": "Yes"},
            {"token_id": TOKEN_NO, "outcome": "No"},
        ],
    }
    assert "probability" not in normalized["derived"]
    assert "recommendation" not in normalized["derived"]


@pytest.mark.parametrize(
    ("normalizer", "payload"),
    [
        (normalize_market, {"conditionId": "0x" + "a" * 63}),
        (normalize_market, {"conditionId": "0X" + "a" * 64}),
        (
            normalize_market_by_token,
            {
                "condition_id": "0x" + "g" * 64,
                "primary_token_id": TOKEN_YES,
                "secondary_token_id": TOKEN_NO,
            },
        ),
        (
            normalize_orderbook,
            _book_payload(market="0x" + "a" * 63),
        ),
    ],
)
def test_condition_ids_are_exactly_prefixed_64_hex_values(normalizer, payload) -> None:
    _assert_contract_error("invalid_identifier", lambda: normalizer(payload))


@pytest.mark.parametrize(
    ("normalizer", "payload"),
    [
        (
            normalize_market_by_token,
            {
                "condition_id": CONDITION_ID,
                "primary_token_id": "",
                "secondary_token_id": TOKEN_NO,
            },
        ),
        (
            normalize_market_by_token,
            {
                "condition_id": CONDITION_ID,
                "primary_token_id": "token\nwith-control",
                "secondary_token_id": TOKEN_NO,
            },
        ),
        (
            normalize_clob_market_info,
            {"t": [{"t": "", "o": "Yes"}]},
        ),
        (
            normalize_orderbook,
            _book_payload(asset_id="token\twith-control"),
        ),
    ],
)
def test_token_ids_are_nonempty_and_control_character_free(normalizer, payload) -> None:
    _assert_contract_error("invalid_identifier", lambda: normalizer(payload))


def test_market_by_token_requires_valid_condition_and_preserves_opaque_token_ids() -> (
    None
):
    raw = {
        "condition_id": CONDITION_ID,
        "primary_token_id": "90071992547409931234567890",
        "secondary_token_id": "90071992547409931234567891",
        "provider_extension": {"keep": True},
    }

    normalized = normalize_market_by_token(raw)

    assert normalized == raw
    assert isinstance(normalized["primary_token_id"], str)
    assert normalized["primary_token_id"] != normalized["secondary_token_id"]


def test_empty_orderbook_sides_produce_null_derived_extrema_not_zero() -> None:
    normalized = normalize_orderbook(_book_payload())

    assert normalized["bids"] == []
    assert normalized["asks"] == []
    assert normalized["derived"] == {
        "best_bid": None,
        "best_ask": None,
        "spread": None,
        "midpoint": None,
    }
    assert 0 not in normalized["derived"].values()
    assert "probability" not in normalized["derived"]
    assert "recommendation" not in normalized["derived"]


def test_orderbook_extrema_are_numeric_and_decimal_precision_is_preserved() -> None:
    best_bid = "0.1234567890123456789012345678"
    best_ask = "0.1234567890123456789012345680"
    normalized = normalize_orderbook(
        _book_payload(
            bids=[
                {"price": "0.12", "size": "1"},
                {"price": best_bid, "size": "2"},
                {"price": "0.09", "size": "3"},
            ],
            asks=[
                {"price": "0.4", "size": "1"},
                {"price": best_ask, "size": "2"},
                {"price": "0.2", "size": "3"},
            ],
        ),
    )

    assert normalized["bids"][1]["price"] == best_bid
    assert normalized["bids"][1]["size"] == "2"
    assert normalized["asks"][1]["price"] == best_ask
    assert normalized["derived"] == {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": "0.0000000000000000000000000002",
        "midpoint": "0.1234567890123456789012345679",
    }


@pytest.mark.parametrize(
    ("bad_levels", "expected"),
    [
        ([{"price": "-0.1", "size": "1"}], "invalid_numeric"),
        ([{"price": "not-a-decimal", "size": "1"}], "invalid_numeric"),
        ([{"price": "0.1", "size": "NaN"}], "invalid_numeric"),
        ([{"price": 0.1, "size": "1"}], "invalid_field"),
        ([{"price": "0.1"}], "missing_field"),
    ],
)
def test_orderbook_rejects_invalid_level_prices_and_sizes(bad_levels, expected) -> None:
    _assert_contract_error(
        expected,
        lambda: normalize_orderbook(_book_payload(bids=bad_levels)),
    )


def test_scalar_price_normalizers_preserve_provider_values_without_advisory_derivations() -> (
    None
):
    price = normalize_price({"price": 0.12345678901234568, "extension": "kept"})
    midpoint = normalize_midpoint({"mid_price": "0.1234567890123456789012345678"})
    last_trade = normalize_last_trade({"price": "0.1234567890123456789", "side": "BUY"})

    assert price["price"] == 0.12345678901234568
    assert price["extension"] == "kept"
    assert midpoint["mid_price"] == "0.1234567890123456789012345678"
    assert last_trade == {"price": "0.1234567890123456789", "side": "BUY"}
    for result in (price, midpoint, last_trade):
        assert "derived" not in result
        assert "probability" not in result
        assert "recommendation" not in result


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, "0.5"])
def test_price_normalizer_requires_finite_nonnegative_numeric_price(value) -> None:
    _assert_contract_error(
        "invalid_numeric", lambda value=value: normalize_price({"price": value})
    )


def test_price_history_accepts_unix_seconds_and_keeps_interval_metadata_independent() -> (
    None
):
    history = [
        {"t": 0, "p": 0.0},
        {"t": 1_700_000_000, "p": 0.12345678901234568},
    ]
    interval_payload = normalize_price_history(
        {"history": history, "interval": "1h", "fidelity": 10, "extension": {"x": 1}},
    )
    absolute_payload = normalize_price_history(
        {
            "history": history,
            "startTs": 1_700_000_000,
            "endTs": 1_700_003_600,
            "extension": {"x": 2},
        },
    )

    assert interval_payload["history"] == history
    assert absolute_payload["history"] == history
    assert interval_payload["interval"] == "1h"
    assert interval_payload["fidelity"] == 10
    assert absolute_payload["startTs"] == 1_700_000_000
    assert absolute_payload["endTs"] == 1_700_003_600
    assert "derived" not in interval_payload
    assert "probability" not in interval_payload
    assert "recommendation" not in interval_payload


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ({"t": -1, "p": 0.5}, "invalid_timestamp"),
        ({"t": 1.5, "p": 0.5}, "invalid_timestamp"),
        ({"t": True, "p": 0.5}, "invalid_timestamp"),
        ({"t": 1_700_000_000, "p": "NaN"}, "invalid_numeric"),
        ({"t": 1_700_000_000, "p": math.nan}, "invalid_numeric"),
        ({"t": 1_700_000_000, "p": -0.1}, "invalid_numeric"),
    ],
)
def test_price_history_rejects_non_unix_second_timestamps_and_nonfinite_prices(
    point, expected
) -> None:
    _assert_contract_error(
        expected,
        lambda: normalize_price_history({"history": [point]}),
    )


def test_data_aggregate_normalizers_require_bare_array_roots_and_validate_rows() -> (
    None
):
    live_volume = normalize_live_volume(
        [
            {
                "total": 12.5,
                "markets": [
                    {"market": CONDITION_ID, "value": 7.25, "marketExtension": "kept"},
                ],
                "rowExtension": {"source": "data"},
            },
        ],
    )
    open_interest = normalize_open_interest(
        [
            {"market": OTHER_CONDITION_ID, "value": 99.0, "rowExtension": True},
        ],
    )

    assert isinstance(live_volume, list)
    assert live_volume[0]["markets"][0] == {
        "market": CONDITION_ID,
        "value": 7.25,
        "marketExtension": "kept",
    }
    assert live_volume[0]["rowExtension"] == {"source": "data"}
    assert isinstance(open_interest, list)
    assert open_interest[0] == {
        "market": OTHER_CONDITION_ID,
        "value": 99.0,
        "rowExtension": True,
    }

    _assert_contract_error(
        "malformed_payload", lambda: normalize_live_volume({"data": []})
    )
    _assert_contract_error(
        "malformed_payload", lambda: normalize_open_interest({"data": []})
    )
    assert normalize_live_volume([]) == []
    assert normalize_open_interest([]) == []


@pytest.mark.parametrize(
    ("normalizer", "payload"),
    [
        (
            normalize_live_volume,
            [{"total": math.inf, "markets": []}],
        ),
        (
            normalize_live_volume,
            [{"total": 1, "markets": [{"market": CONDITION_ID, "value": -1}]}],
        ),
        (
            normalize_open_interest,
            [{"market": CONDITION_ID, "value": math.nan}],
        ),
        (
            normalize_open_interest,
            [{"market": "not-a-condition-id", "value": 1}],
        ),
    ],
)
def test_data_aggregate_rows_reject_nonfinite_values_and_invalid_conditions(
    normalizer, payload
) -> None:
    expected = (
        "invalid_identifier"
        if normalizer is normalize_open_interest
        and payload[0]["market"] == "not-a-condition-id"
        else "invalid_numeric"
    )
    _assert_contract_error(expected, lambda: normalizer(payload))


def test_normalizers_do_not_create_probability_or_recommendation_fields() -> None:
    market = normalize_market(_triplet())
    clob_info = normalize_clob_market_info(
        {"t": [{"t": TOKEN_YES, "o": "Yes"}]},
    )
    book = normalize_orderbook(
        _book_payload(
            bids=[{"price": "0.2", "size": "1"}],
            asks=[{"price": "0.4", "size": "1"}],
        ),
    )

    assert set(market["derived"]) == {"outcome_associations"}
    assert set(clob_info["derived"]) == {"token_outcomes"}
    assert set(book["derived"]) == {"best_bid", "best_ask", "spread", "midpoint"}
    for result in (market, clob_info, book):
        assert "probability" not in result
        assert "recommendation" not in result
        assert "probability" not in result["derived"]
        assert "recommendation" not in result["derived"]
