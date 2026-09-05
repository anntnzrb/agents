# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync planning data structures and plan generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

from sync.core.cliproxy_deployment import (
    CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER,
    CLI_PROXY_SOURCE_DIR,
    CliProxyDeployment,
    CliProxyEndpointTarget,
    is_cliproxy_gateway_host,
    read_cliproxy_deployment,
)
from sync.core.harness import (
    SKILLS_DST_DIR,
    SKILLS_SOURCE_SUBDIR,
    SOURCE_AGENT_FILE,
    Harness,
    SyncEnv,
    harness_instruction_file_name,
    harness_instruction_target,
    harness_managed_state_path,
    harness_root,
    harness_source_root,
)
from sync.core.harness_adapters import ExtensionDepsHook, PackageBootstrapHook
from sync.runtime.errors import assert_never, panic_message

type JobKind = Literal[
    "Dir",
    "File",
    "SecretTemplate",
    "CliProxyReadiness",
    "CliProxyEndpointTemplates",
    "CliProxyConfig",
    "SyncRuntimeInstall",
]


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
    kind: Literal["File"] = "File"


@dataclass(frozen=True, slots=True)
class SecretTemplateJob:
    """Secret template rendering and deployment job."""

    src: str
    dst: str
    secrets_path: str
    kind: Literal["SecretTemplate"] = "SecretTemplate"


@dataclass(frozen=True, slots=True)
class CliProxyReadinessJob:
    """CLI proxy readiness probe job."""

    deployment: CliProxyDeployment
    gateway_host: bool
    kind: Literal["CliProxyReadiness"] = "CliProxyReadiness"


@dataclass(frozen=True, slots=True)
class CliProxyEndpointTemplatesJob:
    """CLI proxy endpoint templates publication job."""

    targets: tuple[CliProxyEndpointTarget, ...]
    deployment: CliProxyDeployment
    kind: Literal["CliProxyEndpointTemplates"] = "CliProxyEndpointTemplates"


@dataclass(frozen=True, slots=True)
class CliProxyConfigJob:
    """CLI proxy configuration rendering and synchronization job."""

    src: str
    dst: str
    secrets_path: str
    deployment: CliProxyDeployment
    gateway_host: bool = False
    kind: Literal["CliProxyConfig"] = "CliProxyConfig"


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
    | SecretTemplateJob
    | CliProxyReadinessJob
    | CliProxyEndpointTemplatesJob
    | CliProxyConfigJob
    | SyncRuntimeInstallJob
)


@dataclass(frozen=True, slots=True)
class PackageBootstrapHookPlan:
    """Hook plan for bootstrapping packages for a harness."""

    harness: Harness
    manifest_path: str
    runtime_settings_path: str
    cache_root: str
    timeout_ms: int
    kind: Literal["PackageBootstrap"] = "PackageBootstrap"


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


type SyncHookPlan = PackageBootstrapHookPlan | ExtensionDepsHookPlan


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
    hooks: tuple[SyncHookPlan, ...]


@dataclass(frozen=True, slots=True)
class SyncPlan:
    """Complete aggregated synchronization plan."""

    harnesses: tuple[HarnessPlan, ...]
    jobs: tuple[Job, ...]
    hooks: tuple[SyncHookPlan, ...]
    cli_proxy_deployment: CliProxyDeployment
    gateway_host: bool


CLIPROXY_ENDPOINT_TEMPLATE_PATHS: dict[str, tuple[str, ...]] = {
    "codex": ("config.toml",),
    "grok": ("config.toml",),
    "opencode": ("opencode.jsonc",),
    "omp": ("models.yml",),
}

DEFAULT_PACKAGE_CACHE_SUBDIR = ".local/share/agents/pi-packages"


def is_safe_managed_entry_name(entry_name: str) -> bool:
    """Return True if entry_name is a valid single top-level filename or dirname."""
    return (
        len(entry_name) > 0
        and not Path(entry_name).is_absolute()
        and "/" not in entry_name
        and "\\" not in entry_name
        and entry_name not in {".", ".."}
    )


def _dir_entry_names(root: str) -> list[str]:
    path = Path(root)
    if not path.is_dir():
        return []
    try:
        entries = [entry.name for entry in path.iterdir()]
    except OSError as error:
        message = f"read {root} ({panic_message(error)})"
        raise RuntimeError(message) from error
    return sorted(set(entries))


def top_level_entry_names(root: str) -> list[str]:
    """Return sorted unique top-level entry names in a directory."""
    return _dir_entry_names(root)


def _skills_source_exists(sync_env: SyncEnv) -> bool:
    return (Path(sync_env.skills_home) / SKILLS_SOURCE_SUBDIR).is_dir()


def _extension_hook_state_path(managed_state_home: str, harness: Harness) -> str:
    return str(Path(managed_state_home) / f"{harness.source_name}.extension-deps.json")


def _build_hook_plans(
    sync_env: SyncEnv,
    harness: Harness,
    root: str,
    source_root: str,
) -> list[SyncHookPlan]:
    hook_plans: list[SyncHookPlan] = []
    for hook in harness.hooks:
        match hook:
            case PackageBootstrapHook():
                manifest_file = hook.manifest_file or ""
                settings_file = hook.settings_file or ""
                cache_subdir = (
                    hook.cache_subdir
                    if hook.cache_subdir is not None
                    else DEFAULT_PACKAGE_CACHE_SUBDIR
                )
                hook_plans.append(
                    PackageBootstrapHookPlan(
                        harness=harness,
                        manifest_path=str(Path(source_root) / manifest_file),
                        runtime_settings_path=str(Path(root) / settings_file),
                        cache_root=str(Path(sync_env.home) / cache_subdir),
                        timeout_ms=sync_env.install_timeout_ms,
                    )
                )
            case ExtensionDepsHook():
                relative_root = "" if hook.root_dir == "." else hook.root_dir
                hook_plans.append(
                    ExtensionDepsHookPlan(
                        harness=harness,
                        job_root=root,
                        root=str(Path(root) / hook.root_dir),
                        source_root=str(Path(source_root) / hook.root_dir),
                        relative_root=relative_root,
                        state_path=_extension_hook_state_path(
                            sync_env.managed_state_home, harness
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
    skills_source = str(Path(sync_env.skills_home) / SKILLS_SOURCE_SUBDIR)
    return ExtensionDepsHookPlan(
        harness=harness,
        job_root=str(Path(root) / SKILLS_DST_DIR),
        root=str(Path(root) / SKILLS_DST_DIR),
        source_root=skills_source,
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
    names: set[str] = {harness_instruction_file_name(harness)}
    for entry_name in top_level_entry_names(source_root):
        names.add(entry_name)
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
    cleanup_entry_names = tuple(
        sorted(set(current_entry_names) | set(harness.compat_managed_entries))
    )
    skill_hook = _build_skill_hook_plan(sync_env, harness, root)
    hooks: list[SyncHookPlan] = _build_hook_plans(sync_env, harness, root, source_root)
    if skill_hook is not None:
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


def _cli_proxy_endpoint_template_paths(plan: HarnessPlan) -> list[str]:
    relative_paths = CLIPROXY_ENDPOINT_TEMPLATE_PATHS.get(plan.harness.id)
    if relative_paths is None:
        return []
    result: list[str] = []
    for relative_path in relative_paths:
        source_path = Path(plan.source_root) / relative_path
        if source_path.is_file():
            try:
                with source_path.open(encoding="utf-8") as file_handle:
                    content = file_handle.read()
                if CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER in content:
                    result.append(relative_path)
            except OSError:
                pass
    return result


def _runtime_jobs(sync_env: SyncEnv) -> list[Job]:
    source_root = str(Path(sync_env.ssot_home) / "sync")
    return [
        SyncRuntimeInstallJob(
            source_root=source_root,
            releases_root=str(Path(sync_env.runtime_home) / "sync-releases"),
            current_link=str(Path(sync_env.runtime_home) / "sync-current"),
            timeout_ms=sync_env.install_timeout_ms,
        )
    ]


def _harness_dir_jobs(harnesses: Sequence[HarnessPlan]) -> list[Job]:
    jobs: list[Job] = []
    for plan in harnesses:
        endpoint_template_paths = _cli_proxy_endpoint_template_paths(plan)
        preserve_paths = (
            tuple(endpoint_template_paths) if endpoint_template_paths else ()
        )
        jobs.append(
            DirJob(
                src=plan.source_root,
                dst=plan.root,
                scope="Children",
                preserve_paths=preserve_paths,
            )
        )
    return jobs


def _skills_jobs(sync_env: SyncEnv, harnesses: Sequence[HarnessPlan]) -> list[Job]:
    skills_source = str(Path(sync_env.skills_home) / SKILLS_SOURCE_SUBDIR)
    return [
        DirJob(
            src=skills_source,
            dst=str(Path(plan.root) / SKILLS_DST_DIR),
            scope="Tree",
        )
        for plan in harnesses
    ]


def _instruction_jobs(sync_env: SyncEnv, harnesses: Sequence[HarnessPlan]) -> list[Job]:
    return [
        FileJob(
            src=str(Path(sync_env.ssot_home) / SOURCE_AGENT_FILE),
            dst=plan.instruction_target,
        )
        for plan in harnesses
    ]


def _config_jobs(
    sync_env: SyncEnv,
    harnesses: Sequence[HarnessPlan],
    deployment: CliProxyDeployment,
    *,
    gateway_host: bool,
) -> list[Job]:
    endpoint_targets: list[CliProxyEndpointTarget] = []
    for plan in harnesses:
        relative_paths = _cli_proxy_endpoint_template_paths(plan)
        for relative_path in relative_paths:
            source_path = str(Path(plan.source_root) / relative_path)
            if plan.harness.id == "codex" and relative_path == "config.toml":
                endpoint_targets.append(
                    CliProxyEndpointTarget(
                        src=source_path,
                        dst=str(Path(plan.root) / relative_path),
                        preserve_top_levels=("hooks.state", "projects"),
                    )
                )
            else:
                endpoint_targets.append(
                    CliProxyEndpointTarget(
                        src=source_path,
                        dst=str(Path(plan.root) / relative_path),
                    )
                )

    jobs: list[Job] = [
        CliProxyReadinessJob(
            deployment=deployment,
            gateway_host=gateway_host,
        ),
        FileJob(
            src=str(Path(sync_env.ssot_home) / "tools" / "mcporter" / "mcporter.jsonc"),
            dst=str(Path(sync_env.mcporter_home) / "mcporter.json"),
        ),
        FileJob(
            src=str(Path(sync_env.ssot_home) / "tools" / "summarize" / "config.json"),
            dst=str(Path(sync_env.summarize_home) / "config.json"),
        ),
        CliProxyConfigJob(
            src=str(
                Path(sync_env.ssot_home) / CLI_PROXY_SOURCE_DIR / "config.yaml.tmpl"
            ),
            dst=str(Path(sync_env.home) / ".cli-proxy-api" / "config.yaml"),
            secrets_path=str(
                Path(sync_env.home) / ".config" / "agents" / "secrets.local.json"
            ),
            deployment=deployment,
            gateway_host=gateway_host,
        ),
    ]

    if gateway_host:
        jobs.append(
            FileJob(
                src=str(Path(sync_env.ssot_home) / CLI_PROXY_SOURCE_DIR / "panel.html"),
                dst=str(
                    Path(sync_env.home)
                    / ".cli-proxy-api"
                    / "static"
                    / "management.html"
                ),
            )
        )
    jobs.append(
        CliProxyEndpointTemplatesJob(
            targets=tuple(endpoint_targets),
            deployment=deployment,
        )
    )

    return jobs


def build_sync_plan(sync_env: SyncEnv) -> SyncPlan:
    """Build the complete synchronization plan for all harnesses and tools."""
    harnesses = tuple(
        _build_harness_plan(sync_env, harness) for harness in sync_env.harnesses
    )
    cli_proxy_deployment = read_cliproxy_deployment(
        str(Path(sync_env.ssot_home) / CLI_PROXY_SOURCE_DIR / "deployment.json")
    )
    gateway_host = is_cliproxy_gateway_host(cli_proxy_deployment)

    jobs: list[Job] = []
    jobs.extend(_runtime_jobs(sync_env))
    jobs.extend(_harness_dir_jobs(harnesses))
    jobs.extend(_skills_jobs(sync_env, harnesses))
    jobs.extend(_instruction_jobs(sync_env, harnesses))
    jobs.extend(
        _config_jobs(
            sync_env, harnesses, cli_proxy_deployment, gateway_host=gateway_host
        )
    )

    hooks = tuple(hook for plan in harnesses for hook in plan.hooks)

    return SyncPlan(
        harnesses=harnesses,
        jobs=tuple(jobs),
        hooks=hooks,
        cli_proxy_deployment=cli_proxy_deployment,
        gateway_host=gateway_host,
    )


__all__ = [
    "CLIPROXY_ENDPOINT_TEMPLATE_PATHS",
    "CliProxyConfigJob",
    "CliProxyEndpointTemplatesJob",
    "CliProxyReadinessJob",
    "DirJob",
    "ExtensionDepsHookPlan",
    "FileJob",
    "HarnessPlan",
    "Job",
    "JobKind",
    "PackageBootstrapHookPlan",
    "SecretTemplateJob",
    "SyncHookPlan",
    "SyncPlan",
    "SyncRuntimeInstallJob",
    "build_sync_plan",
    "is_safe_managed_entry_name",
    "top_level_entry_names",
]
