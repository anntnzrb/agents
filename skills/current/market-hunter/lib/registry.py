"""Dynamic marketplace adapter registry (port of lib/registry.ts)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import MarketplaceAdapter, MarketplaceId

_adapters_registry: dict[MarketplaceId, MarketplaceAdapter] = {}


def register_adapter(adapter: MarketplaceAdapter) -> None:
    """Register a marketplace adapter into the dynamic registry."""
    _adapters_registry[adapter.id] = adapter


def unregister_adapter(adapter_id: MarketplaceId) -> bool:
    """Unregister a marketplace adapter by ID."""
    if adapter_id in _adapters_registry:
        del _adapters_registry[adapter_id]
        return True
    return False


def get_available_adapters() -> list[MarketplaceAdapter]:
    """Get all currently registered marketplace adapters."""
    return list(_adapters_registry.values())


def resolve_adapters(
    filter: Sequence[str] | None = None,
) -> list[MarketplaceAdapter]:
    """Resolve which adapters to execute based on an optional filter list.

    If filter is omitted or empty, returns all adapters with
    is_enabled_by_default: True.
    """
    if not filter:
        return [a for a in get_available_adapters() if a.is_enabled_by_default]

    normalized = [f.strip().lower() for f in filter]
    resolved: list[MarketplaceAdapter] = []

    for name in normalized:
        for adapter_id, adapter in _adapters_registry.items():
            if (
                adapter_id.lower() == name or name in adapter.display_name.lower()
            ) and not any(r.id == adapter.id for r in resolved):
                resolved.append(adapter)

    return (
        resolved
        if len(resolved) > 0
        else [a for a in get_available_adapters() if a.is_enabled_by_default]
    )


def clear_registry() -> None:
    """Clear all registered adapters (useful for test isolation)."""
    _adapters_registry.clear()
