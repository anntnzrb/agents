# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Translate the shared mcporter registry at the Pi adapter boundary."""

import re
import shlex
from collections.abc import Mapping
from pathlib import Path

from sync.runtime.jsonc import is_obj_dict, is_obj_list

ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _config_value(value: str, env: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name, default = match.groups()
        if default is None or env.get(name):
            return f"${{{name}}}"
        return default

    return ENV_REF.sub(replace, value)


def _shell_value(value: str) -> str:
    parts: list[str] = []
    start = 0
    for match in ENV_REF.finditer(value):
        parts.append(shlex.quote(value[start : match.start()]))
        name, default = match.groups()
        fallback = (
            (default or "")
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
        parts.append(f'"${{{name}:-{fallback}}}"')
        start = match.end()
    parts.append(shlex.quote(value[start:]))
    return "".join(parts)


def _render_server(raw: dict[str, object], env: Mapping[str, str]) -> dict[str, object]:
    server = {key: raw[key] for key in ("command", "args", "description") if key in raw}
    if "serverUrl" in raw:
        server["url"] = raw["serverUrl"]
    for key in ("headers", "env"):
        if key not in raw:
            continue
        values = raw[key]
        if not is_obj_dict(values) or not all(
            isinstance(v, str) for v in values.values()
        ):
            message = f"mcporter {key} must contain strings"
            raise ValueError(message)
        translated = {
            k: _config_value(v, env) for k, v in values.items() if isinstance(v, str)
        }
        server[key] = {k: v for k, v in translated.items() if key != "headers" or v}
    args = raw.get("args", [])
    command = raw.get("command")
    if isinstance(command, str) and is_obj_list(args):
        if not all(isinstance(arg, str) for arg in args):
            message = "mcporter args must contain strings"
            raise ValueError(message)
        strings = [arg for arg in args if isinstance(arg, str)]
        if any(ENV_REF.search(arg) for arg in strings):
            # Pi expands env and headers, but passes command arguments literally.
            server["command"] = "sh"
            server["args"] = [
                "-c",
                "exec " + " ".join(_shell_value(arg) for arg in [command, *strings]),
            ]
    return server


def render_pi_mcp(
    source: dict[str, object], root: str, env: Mapping[str, str]
) -> tuple[dict[str, object], list[str]]:
    """Render native entries and exclusions, never substituting credential values."""
    raw_servers = source.get("mcpServers", {})
    if not is_obj_dict(raw_servers):
        message = "mcporter mcpServers must be an object"
        raise ValueError(message)
    servers: dict[str, object] = {}
    exclusions: list[str] = []
    for name, raw in raw_servers.items():
        if not is_obj_dict(raw):
            message = f"mcporter server {name} must be an object"
            raise ValueError(message)
        skill = raw.get("piSkill")
        if skill is not None:
            if not isinstance(skill, str) or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]*", skill
            ):
                message = f"mcporter server {name} has an invalid piSkill"
                raise ValueError(message)
            exclusions.append(f"-{Path(root) / 'skills' / skill}")
        servers[name] = _render_server(raw, env)
    return {"mcpServers": servers}, sorted(set(exclusions))
