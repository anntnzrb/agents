"""Resolve the model endpoint configuration for autommit."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from autommit.errors import AutommitError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# owner defaults; flags and environment variables override each one
DEFAULT_MODEL: Final[str] = "gemini-3.8-flash-high"
DEFAULT_BASE_URL: Final[str] = "http://munich.trex-gamut.ts.net:8317/v1"
DEFAULT_API_KEY: Final[str] = "keyless"
DEFAULT_REASONING_EFFORT: Final[str] = "high"
DEFAULT_TIMEOUT: Final[float] = 300.0

MODEL_ENV: Final[tuple[str, ...]] = ("AUTOMMIT_MODEL",)
BASE_URL_ENV: Final[tuple[str, ...]] = ("AUTOMMIT_BASE_URL", "OPENAI_BASE_URL")
API_KEY_ENV: Final[tuple[str, ...]] = ("AUTOMMIT_API_KEY", "OPENAI_API_KEY")
TIMEOUT_ENV: Final[tuple[str, ...]] = ("AUTOMMIT_TIMEOUT",)
REASONING_EFFORT_ENV: Final[tuple[str, ...]] = ("AUTOMMIT_REASONING_EFFORT",)


@dataclass(frozen=True, slots=True)
class AutommitConfig:
    """Resolved model endpoint settings."""

    model: str
    base_url: str
    api_key: str
    timeout: float
    reasoning_effort: str


@dataclass(frozen=True, slots=True)
class ConfigOverrides:
    """Explicit caller overrides that win over the environment."""

    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout: float | None = None
    reasoning_effort: str | None = None


def _first_env(environ: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = environ.get(name, "").strip()
        if value:
            return value
    return None


def _first_text(candidates: Sequence[object], default: str) -> str:
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return default


def _parse_timeout(candidate: object) -> float | None:
    if candidate is None:
        return None
    try:
        value = float(cast("float", candidate))
    except (TypeError, ValueError) as error:
        raise AutommitError(
            "invalid_config", f"Autommit timeout must be a number: {candidate}."
        ) from error
    if value <= 0:
        raise AutommitError("invalid_config", "Autommit timeout must be positive.")
    return value


def _first_timeout(candidates: Sequence[object], default: float) -> float:
    for candidate in candidates:
        parsed = _parse_timeout(candidate)
        if parsed is not None:
            return parsed
    return default


def load_config(
    *,
    overrides: ConfigOverrides | None = None,
    environ: Mapping[str, str] | None = None,
) -> AutommitConfig:
    """Resolve settings: explicit overrides beat the environment, which beats defaults."""
    chosen = overrides or ConfigOverrides()
    resolved_env = os.environ if environ is None else environ

    model = _first_text(
        (chosen.model, _first_env(resolved_env, MODEL_ENV)),
        DEFAULT_MODEL,
    )
    base_url = _first_text(
        (chosen.base_url, _first_env(resolved_env, BASE_URL_ENV)),
        DEFAULT_BASE_URL,
    ).rstrip("/")
    api_key = _first_text(
        (chosen.api_key, _first_env(resolved_env, API_KEY_ENV)),
        DEFAULT_API_KEY,
    )
    timeout = _first_timeout(
        (chosen.timeout, _first_env(resolved_env, TIMEOUT_ENV)),
        DEFAULT_TIMEOUT,
    )
    reasoning_effort = _first_text(
        (chosen.reasoning_effort, _first_env(resolved_env, REASONING_EFFORT_ENV)),
        DEFAULT_REASONING_EFFORT,
    )

    return AutommitConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        reasoning_effort=reasoning_effort,
    )
