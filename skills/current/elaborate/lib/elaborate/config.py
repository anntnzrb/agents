# Copyright (c) 2026
"""Load, merge, and validate deterministic configuration."""

import os
import re
import tomllib
from pathlib import Path

from .data import (
    InputError,
    Table,
    canonical,
    digest,
    integer,
    narrow,
    number,
    string,
    strings,
    table,
)


def _merge(defaults: Table, override: Table, prefix: str = "") -> Table:
    merged = defaults.copy()
    for key, value in override.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if key not in defaults:
            if prefix == "lang":
                merged[key] = _merge(table(defaults["en"]), table(value), dotted)
                continue
            raise InputError(f"Unknown config key: {dotted}")
        baseline = defaults[key]
        if isinstance(baseline, dict):
            merged[key] = _merge(baseline, table(value), dotted)
        elif isinstance(baseline, bool):
            if not isinstance(value, bool):
                raise InputError(f"Expected boolean: {dotted}")
            merged[key] = value
        elif isinstance(baseline, (int, float)):
            _ = integer(value) if isinstance(baseline, int) else number(value)
            merged[key] = value
        elif isinstance(baseline, list):
            _ = strings(value)
            merged[key] = value
        else:
            _ = string(value)
            merged[key] = value
    return merged


def section(config: Table, name: str) -> Table:
    """Access a known configuration table."""
    return table(config[name])


def language(config: Table, lang: str) -> Table | None:
    """Return configured language rules, if present."""
    value = section(config, "lang").get(lang)
    return table(value) if value is not None else None


def labels(config: Table, lang: str) -> dict[str, str]:
    """Use configured labels or the English fallback."""
    rules = language(config, lang) or section(section(config, "lang"), "en")
    return {key: string(value) for key, value in section(rules, "labels").items()}


def fingerprint(config: Table) -> str:
    """Hash the merged configuration."""
    return digest(canonical(config))


def _validate(config: Table) -> None:
    ingest = section(config, "ingest")
    for key in ("toc_depth", "max_unit_words", "min_unit_words"):
        if integer(ingest[key]) < 1:
            raise InputError(f"ingest.{key} must be positive")
    for pattern in strings(ingest["matter_patterns"]):
        try:
            _ = re.compile(pattern)
        except re.error as error:
            raise InputError(f"Invalid matter pattern: {pattern}") from error
    build = section(config, "build")
    if integer(build["words_per_minute"]) < 1:
        raise InputError("build.words_per_minute must be positive")
    if build["aside_style"] not in ("plain", "italic"):
        raise InputError("build.aside_style must be plain or italic")
    try:
        _ = string(build["title_template"]).format(title="Book")
        for rules in section(config, "lang").values():
            _ = string(section(table(rules), "labels")["progress"]).format(
                index=1, total=1, percent=100, minutes=1
            )
    except (KeyError, ValueError, IndexError) as error:
        raise InputError(f"Invalid format template: {error}") from error
    _validate_gates(config)


def _validate_gates(config: Table) -> None:
    for code, value in section(config, "lang").items():
        if integer(table(value)["stem_length"]) < 1:
            raise InputError(f"lang.{code}.stem_length must be positive")
    for gid, value in section(config, "gates").items():
        gate = table(value)
        if gate["severity"] not in ("error", "warn"):
            raise InputError(f"gates.{gid}.severity must be error or warn")
        for key, parameter in gate.items():
            if key not in ("enabled", "severity") and number(parameter) < 0:
                raise InputError(f"gates.{gid}.{key} must not be negative")
    for gid, key in (("F-coverage", "stem_length"), ("V-aside-cadence", "per_words")):
        if integer(section(section(config, "gates"), gid)[key]) < 1:
            raise InputError(f"gates.{gid}.{key} must be positive")


def _read_toml(path: Path) -> Table:
    with path.open("rb") as handle:
        return table(narrow(tomllib.load(handle)))


def load_config(path: Path | None = None) -> Table:
    """Deep merge defaults and the explicit or environment override."""
    defaults = Path(__file__).with_name("defaults.toml")
    config = _read_toml(defaults)
    location = path or (
        Path(value) if (value := os.environ.get("ELABORATE_CONFIG")) else None
    )
    if location is not None:
        try:
            override = _read_toml(location)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise InputError(f"Cannot read config: {error}") from error
        config = _merge(config, override)
    _validate(config)
    return config
