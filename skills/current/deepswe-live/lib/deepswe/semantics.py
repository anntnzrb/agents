"""Published DeepSWE metric semantics.

The registry is deliberately source-local.  A field's name alone is not a
portable unit declaration: these meanings describe the fields published by a
DeepSWE leaderboard artifact and are used only when that artifact is selected.
"""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast


@dataclass(frozen=True, slots=True)
class MetricSemantics:
    """Meaning and comparison metadata for one published DeepSWE field."""

    field: str
    unit: str
    minimum: int | float | None = None
    maximum: int | float | None = None
    comparator: str = "max"
    scope: str | None = None
    denominator: str | None = None
    family: str | None = None

    @property
    def range(self) -> tuple[int | float | None, int | float | None]:
        """Return the source-declared inclusive range."""
        return self.minimum, self.maximum

    def as_dict(self) -> dict[str, object]:
        """Return JSON-shaped semantic metadata."""
        result: dict[str, object] = {
            "field": self.field,
            "unit": self.unit,
            "range": [self.minimum, self.maximum],
            "comparator": self.comparator,
            "scope": self.scope,
            "denominator": self.denominator,
        }
        if self.family is not None:
            result["family"] = self.family
        return result


# Ratios are represented as fractions in [0, 1] in the canonical aggregate.
# Percent strings are accepted by the normalizer and converted to this ratio.
_RATIO_FIELDS: Final[dict[str, dict[str, object]]] = {
    "pass_rate": {
        "scope": "attempts",
        "denominator": "n_attempted",
    },
    "pass_at_1": {
        "scope": "tasks",
        "denominator": "n_tasks_attempted",
    },
    "pass_at_4": {
        "scope": "tasks",
        "denominator": "n_tasks_attempted",
    },
    "ci_lo": {
        "scope": "tasks",
        "denominator": "n_tasks_attempted",
        "family": "pass_at_1_confidence_interval",
    },
    "ci_hi": {
        "scope": "tasks",
        "denominator": "n_tasks_attempted",
        "family": "pass_at_1_confidence_interval",
    },
    "ci_half": {
        "scope": "tasks",
        "denominator": "n_tasks_attempted",
        "family": "pass_at_1_confidence_interval",
    },
}

_COUNT_FIELDS: Final[dict[str, dict[str, object]]] = {
    "n_passed": {"scope": "attempts"},
    "n_attempted": {"scope": "attempts"},
    "n_tasks_attempted": {"scope": "tasks"},
    "n_tasks_passed_any": {"scope": "tasks"},
    "ci_passed": {
        "scope": "attempts",
        "family": "pass_at_1_confidence_interval",
    },
    "ci_attempted": {
        "scope": "attempts",
        "family": "pass_at_1_confidence_interval",
    },
}


def _ratio(field: str, metadata: dict[str, object]) -> MetricSemantics:
    return MetricSemantics(
        field=field,
        unit="ratio",
        minimum=0,
        maximum=1,
        comparator="max",
        scope=cast("str | None", metadata.get("scope")),
        denominator=cast("str | None", metadata.get("denominator")),
        family=cast("str | None", metadata.get("family")),
    )


def _count(field: str, metadata: dict[str, object]) -> MetricSemantics:
    return MetricSemantics(
        field=field,
        unit="count",
        minimum=0,
        maximum=None,
        comparator="max",
        scope=cast("str | None", metadata.get("scope")),
        denominator=cast("str | None", metadata.get("denominator")),
        family=cast("str | None", metadata.get("family")),
    )


SEMANTIC_REGISTRY: Final[dict[str, MetricSemantics]] = {
    **{field: _ratio(field, metadata) for field, metadata in _RATIO_FIELDS.items()},
    **{field: _count(field, metadata) for field, metadata in _COUNT_FIELDS.items()},
    "mean_output_tokens": MetricSemantics(
        field="mean_output_tokens",
        unit="tokens",
        minimum=0,
        maximum=None,
        comparator="min",
        scope="attempts",
        denominator="n_attempted",
        family="output_tokens",
    ),
    "mean_cost_usd": MetricSemantics(
        field="mean_cost_usd",
        unit="usd",
        minimum=0,
        maximum=None,
        comparator="min",
        scope="attempts",
        denominator="n_attempted",
        family="cost",
    ),
    "mean_agent_steps": MetricSemantics(
        field="mean_agent_steps",
        unit="count",
        minimum=0,
        maximum=None,
        comparator="min",
        scope="attempts",
        denominator="n_attempted",
        family="agent_steps",
    ),
}

# Public aliases make the registry easy to discover without creating a second
# source of truth.
KNOWN_METRICS: Final[tuple[str, ...]] = tuple(SEMANTIC_REGISTRY)
PUBLISHED_METRICS: Final[tuple[str, ...]] = KNOWN_METRICS
METRIC_SEMANTICS: Final[dict[str, MetricSemantics]] = SEMANTIC_REGISTRY
REGISTRY: Final[dict[str, MetricSemantics]] = SEMANTIC_REGISTRY


def metric_semantics(field: object) -> MetricSemantics | None:
    """Return semantics for an exact published field name, if known."""
    if not isinstance(field, str):
        return None
    return SEMANTIC_REGISTRY.get(field.strip())


def get_metric_semantics(field: str) -> MetricSemantics | None:
    """Compatibility alias for :func:`metric_semantics`."""
    return metric_semantics(field)


def is_known_metric(field: str) -> bool:
    """Whether ``field`` has a published DeepSWE semantic definition."""
    return metric_semantics(field) is not None


__all__ = [
    "KNOWN_METRICS",
    "METRIC_SEMANTICS",
    "PUBLISHED_METRICS",
    "REGISTRY",
    "SEMANTIC_REGISTRY",
    "MetricSemantics",
    "get_metric_semantics",
    "is_known_metric",
    "metric_semantics",
]
