# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync planning data structures and plan generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

from sync.core.cliproxy_deployment import (
    AGENTS_SETTINGS_FILE,
    AgentsSettings,
    CliProxyEndpointTarget,
    has_cliproxy_endpoint_placeholder,
    read_agents_settings,
)
from sync.core.harness import (
    SKILLS_DST_DIR,
    SKILLS_SOURCE_SUBDIR,
    SOURCE_AGENT_FILE,
    Harness,
    SyncEnv,
    harness_instruction_target,
    harness_managed_state_path,
    harness_root,
    harness_source_root,
)
from sync.core.harness_adapters import ExtensionDepsHook
from sync.runtime.errors import assert_never, panic_message


@dataclass(frozen=True, slots=True)
class DirJob:
    """Directory synchronization job."""

    src: str
    dst: str
    kind: Literal["Dir"] = "Dir"
    scope: Literal["Tree", "Children"] = "Tree"
    preserve_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FileJob:
    """Single file copy/synchronization job."""

    src: str
    dst: str
    endpoint_template: bool = False
    deployment: AgentsSettings | None = None
    kind: Literal["File"] = "File"


@dataclass(frozen=True, slots=True)
class PreserveJsonKeysJob:
    """JSON configuration copy job preserving declared destination keys."""

    src: str
    dst: str
    preserve_paths: tuple[str, ...] = ()
    kind: Literal["PreserveJsonKeys"] = "PreserveJsonKeys"


@dataclass(frozen=True, slots=True)
class CliProxyReadinessJob:
    """CLI proxy readiness probe job."""

    deployment: AgentsSettings
    kind: Literal["CliProxyReadiness"] = "CliProxyReadiness"


@dataclass(frozen=True, slots=True)
class CliProxyEndpointTemplatesJob:
    """CLI proxy endpoint templates publication job."""

    targets: tuple[CliProxyEndpointTarget, ...]
    deployment: AgentsSettings
    kind: Literal["CliProxyEndpointTemplates"] = "CliProxyEndpointTemplates"


@dataclass(frozen=True, slots=True)
class SyncRuntimeInstallJob:
    """Self-hosted sync runtime immutable release installation job."""

    source_root: str
    releases_root: str
    current_link: str
    timeout_ms: int
    kind: Literal["SyncRuntimeInstall"] = "SyncRuntimeInstall"


type Job = (
    DirJob
    | FileJob
    | PreserveJsonKeysJob
    | CliProxyReadinessJob
    | CliProxyEndpointTemplatesJob
    | SyncRuntimeInstallJob
)


@dataclass(frozen=True, slots=True)
class ExtensionDepsHookPlan:
    """Hook plan for installing extension dependencies."""

    harness: Harness
    job_root: str
    root: str
    source_root: str
    relative_root: str
    state_path: str
    timeout_ms: int
    kind: Literal["ExtensionDeps"] = "ExtensionDeps"


@dataclass(frozen=True, slots=True)
class HarnessPlan:
    """Per-harness planning metadata and associated hooks."""

    harness: Harness
    state_path: str
    root: str
    source_root: str
    instruction_target: str
    current_entry_names: tuple[str, ...]
    cleanup_entry_names: tuple[str, ...]
    hooks: tuple[ExtensionDepsHookPlan, ...]


@dataclass(frozen=True, slots=True)
class SyncPlan:
    """Complete aggregated synchronization plan."""

    harnesses: tuple[HarnessPlan, ...]
    jobs: tuple[Job, ...]
    hooks: tuple[ExtensionDepsHookPlan, ...]
    cli_proxy_deployment: AgentsSettings


def top_level_entry_names(root: str) -> list[str]:
    """Return sorted unique top-level entry names in a directory."""
    path = Path(root)
    if not path.is_dir():
        return []
    try:
        return sorted({entry.name for entry in path.iterdir()})
    except OSError as error:
        message = f"read {root} ({panic_message(error)})"
        raise RuntimeError(message) from error


def _skills_source_exists(sync_env: SyncEnv) -> bool:
    return (Path(sync_env.skills_home) / SKILLS_SOURCE_SUBDIR).is_dir()


def _build_hook_plans(
    sync_env: SyncEnv,
    harness: Harness,
    root: str,
    source_root: str,
) -> list[ExtensionDepsHookPlan]:
    hook_plans: list[ExtensionDepsHookPlan] = []
    for hook in harness.hooks:
        match hook:
            case ExtensionDepsHook():
                hook_plans.append(
                    ExtensionDepsHookPlan(
                        harness=harness,
                        job_root=root,
                        root=str(Path(root) / hook.root_dir),
                        source_root=str(Path(source_root) / hook.root_dir),
                        relative_root="" if hook.root_dir == "." else hook.root_dir,
                        state_path=str(
                            Path(sync_env.managed_state_home)
                            / f"{harness.source_name}.extension-deps.json"
                        ),
                        timeout_ms=sync_env.install_timeout_ms,
                    )
                )
            case _:
                assert_never(hook)
    return hook_plans


def _build_skill_hook_plan(
    sync_env: SyncEnv,
    harness: Harness,
    root: str,
) -> ExtensionDepsHookPlan | None:
    if not _skills_source_exists(sync_env):
        return None
    return ExtensionDepsHookPlan(
        harness=harness,
        job_root=str(Path(root) / SKILLS_DST_DIR),
        root=str(Path(root) / SKILLS_DST_DIR),
        source_root=str(Path(sync_env.skills_home) / SKILLS_SOURCE_SUBDIR),
        relative_root="",
        state_path=str(
            Path(sync_env.managed_state_home)
            / f"{harness.source_name}.skills-deps.json"
        ),
        timeout_ms=sync_env.install_timeout_ms,
    )


def _current_managed_entry_names(
    harness: Harness,
    source_root: str,
    *,
    has_skills_source: bool,
) -> list[str]:
    names: set[str] = {harness.instruction_file, *top_level_entry_names(source_root)}
    if has_skills_source:
        names.add(SKILLS_DST_DIR)
    return sorted(names)


def _build_harness_plan(sync_env: SyncEnv, harness: Harness) -> HarnessPlan:
    root = harness_root(harness)
    source_root = harness_source_root(harness, sync_env.harnesses_home)
    instruction_target = harness_instruction_target(harness)
    has_skills = _skills_source_exists(sync_env)
    current_entry_names = tuple(
        _current_managed_entry_names(harness, source_root, has_skills_source=has_skills)
    )
    cleanup_entry_names = current_entry_names
    hooks: list[ExtensionDepsHookPlan] = _build_hook_plans(
        sync_env, harness, root, source_root
    )
    if (skill_hook := _build_skill_hook_plan(sync_env, harness, root)) is not None:
        hooks.append(skill_hook)

    return HarnessPlan(
        harness=harness,
        state_path=harness_managed_state_path(harness, sync_env.managed_state_home),
        root=root,
        source_root=source_root,
        instruction_target=instruction_target,
        current_entry_names=current_entry_names,
        cleanup_entry_names=cleanup_entry_names,
        hooks=tuple(hooks),
    )


def _cli_proxy_template_paths(
    source_root: str,
    candidates: tuple[str, ...],
) -> tuple[str, ...]:
    """Return adapter-declared template paths that carry an endpoint placeholder."""
    found: list[str] = []
    for rel_path in candidates:
        source_path = Path(source_root) / rel_path
        if source_path.is_file() and has_cliproxy_endpoint_placeholder(
            source_path.read_text(encoding="utf-8")
        ):
            found.append(rel_path)
    return tuple(found)


def _config_jobs(
    sync_env: SyncEnv,
    harnesses: Sequence[HarnessPlan],
    deployment: AgentsSettings,
    template_paths_by_id: dict[str, tuple[str, ...]],
) -> list[Job]:
    ssot = Path(sync_env.ssot_home)
    endpoint_targets: list[CliProxyEndpointTarget] = [
        CliProxyEndpointTarget(
            src=str(Path(plan.source_root) / rel_path),
            dst=str(Path(plan.root) / rel_path),
            preserve_top_levels=plan.harness.cliproxy_preserve_top_levels.get(
                rel_path, ()
            ),
        )
        for plan in harnesses
        for rel_path in template_paths_by_id.get(plan.harness.id, ())
    ]

    return [
        CliProxyReadinessJob(
            deployment=deployment,
        ),
        FileJob(
            src=str(ssot / AGENTS_SETTINGS_FILE),
            dst=str(Path(sync_env.runtime_home) / AGENTS_SETTINGS_FILE),
        ),
        FileJob(
            src=str(ssot / "tools" / "mcporter" / "mcporter.jsonc"),
            dst=str(Path(sync_env.mcporter_home) / "mcporter.json"),
        ),
        FileJob(
            src=str(ssot / "tools" / "summarize" / "config.json"),
            dst=str(Path(sync_env.summarize_home) / "config.json"),
            endpoint_template=True,
            deployment=deployment,
        ),
        CliProxyEndpointTemplatesJob(
            targets=tuple(endpoint_targets),
            deployment=deployment,
        ),
    ]


def build_sync_plan(sync_env: SyncEnv) -> SyncPlan:
    """Build the complete synchronization plan for all harnesses and tools."""
    harnesses = tuple(
        _build_harness_plan(sync_env, harness) for harness in sync_env.harnesses
    )
    ssot = Path(sync_env.ssot_home)
    runtime_home = Path(sync_env.runtime_home)
    cli_proxy_deployment = read_agents_settings(ssot / AGENTS_SETTINGS_FILE)
    template_paths_by_id = {
        plan.harness.id: _cli_proxy_template_paths(
            plan.source_root, plan.harness.cliproxy_templates
        )
        for plan in harnesses
    }

    jobs: list[Job] = [
        SyncRuntimeInstallJob(
            source_root=str(ssot / "sync"),
            releases_root=str(runtime_home / "sync-releases"),
            current_link=str(runtime_home / "sync-current"),
            timeout_ms=sync_env.install_timeout_ms,
        ),
        *(
            DirJob(
                src=plan.source_root,
                dst=plan.root,
                scope="Children",
                preserve_paths=(
                    *template_paths_by_id.get(plan.harness.id, ()),
                    *plan.harness.preserve_json_keys,
                ),
            )
            for plan in harnesses
        ),
        *(
            PreserveJsonKeysJob(
                src=str(Path(plan.source_root) / rel_path),
                dst=str(Path(plan.root) / rel_path),
                preserve_paths=preserve_paths,
            )
            for plan in harnesses
            for rel_path, preserve_paths in plan.harness.preserve_json_keys.items()
        ),
        *(
            DirJob(
                src=str(Path(sync_env.skills_home) / SKILLS_SOURCE_SUBDIR),
                dst=str(Path(plan.root) / SKILLS_DST_DIR),
                scope="Tree",
            )
            for plan in harnesses
        ),
        *(
            FileJob(
                src=str(Path(sync_env.ssot_home) / SOURCE_AGENT_FILE),
                dst=plan.instruction_target,
            )
            for plan in harnesses
        ),
        *_config_jobs(
            sync_env,
            harnesses,
            cli_proxy_deployment,
            template_paths_by_id,
        ),
    ]

    hooks = tuple(hook for plan in harnesses for hook in plan.hooks)

    return SyncPlan(
        harnesses=harnesses,
        jobs=tuple(jobs),
        hooks=hooks,
        cli_proxy_deployment=cli_proxy_deployment,
    )


__all__ = [
    "CliProxyEndpointTemplatesJob",
    "CliProxyReadinessJob",
    "DirJob",
    "ExtensionDepsHookPlan",
    "FileJob",
    "Job",
    "PreserveJsonKeysJob",
    "SyncRuntimeInstallJob",
    "build_sync_plan",
    "top_level_entry_names",
]
