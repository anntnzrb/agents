"""Resolve the model endpoint configuration for autommit."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from autommit.errors import AutommitError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

DEFAULT_TIMEOUT: Final[float] = 300.0
CONFIG_FILENAME: Final[str] = ".autommit.json"
MAX_CONFIG_BYTES: Final[int] = 16 * 1024

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
    api_key: str | None
    timeout: float
    reasoning_effort: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigOverrides:
    """Explicit caller overrides that win over environment and file values."""

    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout: float | None = None
    reasoning_effort: str | None = None
    config_file: Path | None = None


def _read_config_file(path: Path) -> dict[str, object]:
    """Read a bounded JSON object without following symlinks."""
    if path.is_symlink() or not path.is_file():
        raise AutommitError(
            "invalid_file", f"Autommit config file must be a regular file: {path}."
        )
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_CONFIG_BYTES)
    except OSError as error:
        raise AutommitError(
            "file_io", f"Unable to read autommit config file: {error}."
        ) from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AutommitError(
            "invalid_json", f"Autommit config is not valid JSON: {error}."
        ) from error
    if not isinstance(value, dict):
        raise AutommitError("invalid_config", "Autommit config must be a JSON object.")
    return cast("dict[str, object]", value)


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
    repo: Path,
    *,
    overrides: ConfigOverrides | None = None,
    environ: Mapping[str, str] | None = None,
) -> AutommitConfig:
    """Resolve settings: overrides beat env, env beats the repo file, file beats defaults."""
    chosen = overrides or ConfigOverrides()
    resolved_env = os.environ if environ is None else environ
    if chosen.config_file is not None:
        file_values = _read_config_file(chosen.config_file)
    elif (repo / CONFIG_FILENAME).is_file():
        file_values = _read_config_file(repo / CONFIG_FILENAME)
    else:
        file_values = {}

    model = _first_text(
        (chosen.model, _first_env(resolved_env, MODEL_ENV), file_values.get("model")),
        "",
    )
    base_url = _first_text(
        (
            chosen.base_url,
            _first_env(resolved_env, BASE_URL_ENV),
            file_values.get("base_url"),
        ),
        "",
    ).rstrip("/")
    if not model:
        raise AutommitError(
            "missing_model",
            "Set AUTOMMIT_MODEL or pass --model; autommit has no model default.",
        )
    if not base_url:
        raise AutommitError(
            "missing_base_url",
            "Set AUTOMMIT_BASE_URL or pass --base-url; autommit has no endpoint default.",
        )
    api_key = _first_text(
        (
            chosen.api_key,
            _first_env(resolved_env, API_KEY_ENV),
            file_values.get("api_key"),
        ),
        "",
    )
    timeout = _first_timeout(
        (
            chosen.timeout,
            _first_env(resolved_env, TIMEOUT_ENV),
            file_values.get("timeout"),
        ),
        DEFAULT_TIMEOUT,
    )
    reasoning_effort = _first_text(
        (
            chosen.reasoning_effort,
            _first_env(resolved_env, REASONING_EFFORT_ENV),
            file_values.get("reasoning_effort"),
        ),
        "",
    )

    return AutommitConfig(
        model=model,
        base_url=base_url,
        api_key=api_key or None,
        timeout=timeout,
        reasoning_effort=reasoning_effort or None,
    )
