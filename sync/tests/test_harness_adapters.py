# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant tests for the harness adapter registry.

`HARNESS_ADAPTERS` is the single source of truth for harness launch and sync
metadata. These tests make the registry safe to grow to N adapters: they pin the
registration order that drives discovery, plan, and wrapper output, and they
prove that each invariant has teeth by feeding it a deliberately broken table.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast, get_args

import pytest

from sync.core.harness import assert_path_component
from sync.core.harness_adapters import (
    HARNESS_ADAPTERS,
    HarnessAdapter,
    HarnessId,
    NpmLauncherSpec,
)
from sync.core.tool_launchers import TOOL_LAUNCHERS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sync.core.harness import HostPlatform

# Registration order is observable behavior: it fixes discovery order, plan job
# order, and wrapper reconciliation order. Append new adapters; do not reorder.
EXPECTED_ADAPTER_ORDER: tuple[str, ...] = (
    "codex",
    "deepseek",
    "devin",
    "opencode",
    "pi",
    "omp",
    "amp",
)

VALID_PLATFORMS: frozenset[str] = frozenset({"darwin", "linux"})


def _harness_id_values() -> tuple[str, ...]:
    """Return the values declared by the ``HarnessId`` alias on any runtime."""
    alias_value = getattr(HarnessId, "__value__", HarnessId)
    return tuple(get_args(alias_value))


def _assert_ids_declared_once(adapters: Sequence[HarnessAdapter]) -> None:
    """Require unique adapter ids; duplicates collide in state and cache paths."""
    ids = [adapter.id for adapter in adapters]
    assert len(ids) == len(set(ids)), f"duplicate adapter ids: {ids}"


def _assert_safe_path_components(adapters: Sequence[HarnessAdapter]) -> None:
    """Require adapter ids and home segments to be safe single path components."""
    for adapter in adapters:
        assert_path_component(adapter.id, f"{adapter.id} id")
        assert adapter.home_segments, f"{adapter.id} must declare home segments"
        for segment in adapter.home_segments:
            assert_path_component(segment, f"{adapter.id} home segment")


def _assert_unique_wrapper_bins(adapters: Sequence[HarnessAdapter]) -> None:
    """Require wrapper names to be unique across harnesses and tool launchers."""
    harness_bins = [adapter.launcher.bin for adapter in adapters]
    assert len(harness_bins) == len(set(harness_bins)), (
        f"duplicate harness wrapper bins: {harness_bins}"
    )
    tool_bins = [tool.bin for tool in TOOL_LAUNCHERS]
    overlap = sorted(set(harness_bins) & set(tool_bins))
    assert not overlap, f"harness wrapper bins collide with tool wrappers: {overlap}"


def _assert_supported_platforms(adapters: Sequence[HarnessAdapter]) -> None:
    """Require every adapter to declare at least one supported host platform."""
    for adapter in adapters:
        assert adapter.platforms, f"{adapter.id} must declare platforms"
        unsupported = sorted(set(adapter.platforms) - VALID_PLATFORMS)
        assert not unsupported, (
            f"{adapter.id} declares unsupported platforms: {unsupported}"
        )


def _assert_registry_invariants(adapters: Sequence[HarnessAdapter]) -> None:
    """Apply every registry invariant to a candidate adapter table."""
    _assert_ids_declared_once(adapters)
    _assert_safe_path_components(adapters)
    _assert_unique_wrapper_bins(adapters)
    _assert_supported_platforms(adapters)


def test_harness_id_alias_matches_adapter_registry() -> None:
    """``HarnessId`` must declare exactly the registered adapter ids."""
    values = _harness_id_values()
    assert len(values) == len(set(values)), f"duplicate HarnessId values: {values}"
    assert set(values) == {adapter.id for adapter in HARNESS_ADAPTERS}


def test_opencode_launcher_uses_v2_package() -> None:
    """Keep the existing wrapper name while resolving the V2 distribution."""
    adapter = next(adapter for adapter in HARNESS_ADAPTERS if adapter.id == "opencode")
    assert isinstance(adapter.launcher, NpmLauncherSpec)
    assert adapter.launcher.package == "@opencode/cli"
    assert adapter.launcher.bin == "opencode"


def test_adapter_registration_order_is_stable() -> None:
    """Registration order is observable behavior and must only grow by appending."""
    assert tuple(adapter.id for adapter in HARNESS_ADAPTERS) == EXPECTED_ADAPTER_ORDER


def test_adapter_registry_satisfies_every_invariant() -> None:
    """The committed adapter table must satisfy every registry invariant."""
    _assert_registry_invariants(HARNESS_ADAPTERS)


def test_invariants_reject_duplicate_adapter_ids() -> None:
    """A duplicate id must fail the unique-id invariant."""
    duplicate = replace(HARNESS_ADAPTERS[0], id=HARNESS_ADAPTERS[1].id)
    with pytest.raises(AssertionError, match="duplicate adapter ids"):
        _assert_ids_declared_once([*HARNESS_ADAPTERS, duplicate])


def test_invariants_reject_unsafe_home_segments() -> None:
    """A traversal home segment must fail the path-component invariant."""
    unsafe = replace(HARNESS_ADAPTERS[0], home_segments=("..", "escape"))
    with pytest.raises(ValueError, match="invalid"):
        _assert_safe_path_components([unsafe])


def test_invariants_reject_empty_home_segments() -> None:
    """An empty home segment list would target the user home itself."""
    empty = replace(HARNESS_ADAPTERS[0], home_segments=())
    with pytest.raises(AssertionError, match="must declare home segments"):
        _assert_safe_path_components([empty])


def test_invariants_reject_duplicate_wrapper_bins() -> None:
    """Two adapters sharing a wrapper name must fail the unique-bin invariant."""
    first, second = HARNESS_ADAPTERS[0], HARNESS_ADAPTERS[1]
    colliding = replace(second, launcher=first.launcher)
    with pytest.raises(AssertionError, match="duplicate harness wrapper bins"):
        _assert_unique_wrapper_bins([first, colliding])


def test_invariants_reject_wrapper_bin_colliding_with_tool_launcher() -> None:
    """A harness bin equal to a tool bin must fail the cross-table invariant."""
    tool = TOOL_LAUNCHERS[0]
    colliding = replace(
        HARNESS_ADAPTERS[0],
        launcher=NpmLauncherSpec(package=tool.package, bin=tool.bin),
    )
    with pytest.raises(AssertionError, match="collide with tool wrappers"):
        _assert_unique_wrapper_bins([colliding])


def test_invariants_reject_unsupported_platforms() -> None:
    """An unsupported host platform must fail the platform invariant."""
    unsupported = replace(
        HARNESS_ADAPTERS[0],
        platforms=cast("tuple[HostPlatform, ...]", ("windows",)),
    )
    with pytest.raises(AssertionError, match="unsupported platforms"):
        _assert_supported_platforms([unsupported])
