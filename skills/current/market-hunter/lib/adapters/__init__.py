"""Marketplace adapters package (port of lib/adapters/index.ts)."""

from __future__ import annotations

from adapters.common import (
    RawScrapedItem,
    detect_delivery_format,
    normalize_raw_items,
    parse_price,
    parse_rating,
    parse_sales,
)
from adapters.funpay import FunPayAdapter
from adapters.g2a import G2aAdapter
from adapters.kinguin import KinguinAdapter
from adapters.plati import PlatiAdapter
from adapters.z2u import Z2uAdapter
from registry import get_available_adapters, register_adapter

__all__ = [
    "FunPayAdapter",
    "G2aAdapter",
    "KinguinAdapter",
    "PlatiAdapter",
    "RawScrapedItem",
    "Z2uAdapter",
    "detect_delivery_format",
    "normalize_raw_items",
    "parse_price",
    "parse_rating",
    "parse_sales",
    "register_builtin_adapters",
]

_state = {"initialized": False}


def register_builtin_adapters() -> None:
    """Initialize and register all built-in marketplace adapters."""
    if _state["initialized"] and get_available_adapters():
        return
    register_adapter(G2aAdapter())
    register_adapter(KinguinAdapter())
    register_adapter(PlatiAdapter())
    register_adapter(Z2uAdapter())
    register_adapter(FunPayAdapter())
    _state["initialized"] = True
