"""Resolve the model endpoint configuration for autommit."""

import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from autommit.errors import AutommitError

# owner defaults; flags and environment variables override each one
DEFAULT_MODEL: Final[str] = "gemini-3.8-flash-high"
DEFAULT_API_KEY: Final[str] = "keyless"
DEFAULT_REASONING_EFFORT: Final[str] = "medium"
DEFAULT_TIMEOUT: Final[float] = 300.0

# Sync installs the shared agents settings here; its gateway is the default
# endpoint.
AGENTS_SETTINGS: Final[Path] = Path.home() / ".local/share/agents/agents.toml"

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
    if isinstance(candidate, int | float | str | bytes | bytearray):
        try:
            value = float(candidate)
        except ValueError as error:
            raise AutommitError(
                "invalid_config", f"Autommit timeout must be a number: {candidate}."
            ) from error
    else:
        raise AutommitError(
            "invalid_config", f"Autommit timeout must be a number: {candidate}."
        )
    if value <= 0:
        raise AutommitError("invalid_config", "Autommit timeout must be positive.")
    return value


def _first_timeout(candidates: Sequence[object], default: float) -> float:
    for candidate in candidates:
        parsed = _parse_timeout(candidate)
        if parsed is not None:
            return parsed
    return default


def gateway_base_url(settings: Path) -> str:
    """Read the gateway endpoint from the installed agents settings."""
    try:
        data = tomllib.loads(settings.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise AutommitError(
            "invalid_config",
            f"No base URL: set AUTOMMIT_BASE_URL or run sync to install {settings}.",
        ) from error
    gateway = data.get("gateway")
    base_url = gateway.get("base_url") if isinstance(gateway, dict) else None
    if not isinstance(base_url, str) or not base_url.strip():
        raise AutommitError(
            "invalid_config", f"{settings} has no gateway.base_url string."
        )
    return base_url.strip()


def load_config(
    *,
    overrides: ConfigOverrides | None = None,
    environ: Mapping[str, str] | None = None,
    settings: Path = AGENTS_SETTINGS,
) -> AutommitConfig:
    """Resolve settings: overrides beat the environment, then the defaults."""
    chosen = overrides or ConfigOverrides()
    resolved_env = os.environ if environ is None else environ

    model = _first_text(
        (chosen.model, _first_env(resolved_env, MODEL_ENV)),
        DEFAULT_MODEL,
    )
    explicit_base_url = _first_text(
        (chosen.base_url, _first_env(resolved_env, BASE_URL_ENV)), ""
    )
    base_url = (explicit_base_url or gateway_base_url(settings)).rstrip("/")
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
