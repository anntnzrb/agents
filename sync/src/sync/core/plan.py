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
    DEFAULT_PACKAGE_CACHE_SUBDIR,
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
    endpoint_template: bool = False
    deployment: CliProxyDeployment | None = None
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
    "opencode": ("opencode.jsonc",),
    "omp": ("models.yml",),
    "pi": ("extensions/cliproxy/index.ts",),
}


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
) -> list[SyncHookPlan]:
    hook_plans: list[SyncHookPlan] = []
    for hook in harness.hooks:
        match hook:
            case PackageBootstrapHook():
                hook_plans.append(
                    PackageBootstrapHookPlan(
                        harness=harness,
                        manifest_path=str(
                            Path(source_root) / (hook.manifest_file or "")
                        ),
                        runtime_settings_path=str(
                            Path(root) / (hook.settings_file or "")
                        ),
                        cache_root=str(
                            Path(sync_env.home)
                            / (hook.cache_subdir or DEFAULT_PACKAGE_CACHE_SUBDIR)
                        ),
                        timeout_ms=sync_env.install_timeout_ms,
                    )
                )
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
    cleanup_entry_names = tuple(
        sorted(set(current_entry_names) | set(harness.compat_managed_entries))
    )
    hooks: list[SyncHookPlan] = _build_hook_plans(sync_env, harness, root, source_root)
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


def _cli_proxy_template_paths(source_root: str, harness_id: str) -> tuple[str, ...]:
    candidates = CLIPROXY_ENDPOINT_TEMPLATE_PATHS.get(harness_id, ())
    found: list[str] = []
    for rel_path in candidates:
        source_path = Path(source_root) / rel_path
        if (
            source_path.is_file()
            and CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER
            in source_path.read_text(encoding="utf-8")
        ):
            found.append(rel_path)
    return tuple(found)


def _config_jobs(
    sync_env: SyncEnv,
    harnesses: Sequence[HarnessPlan],
    deployment: CliProxyDeployment,
    template_paths_by_id: dict[str, tuple[str, ...]],
    *,
    gateway_host: bool,
) -> list[Job]:
    endpoint_targets: list[CliProxyEndpointTarget] = [
        CliProxyEndpointTarget(
            src=str(Path(plan.source_root) / rel_path),
            dst=str(Path(plan.root) / rel_path),
            preserve_top_levels=(
                ("hooks.state", "projects")
                if plan.harness.id == "codex" and rel_path == "config.toml"
                else ()
            ),
        )
        for plan in harnesses
        for rel_path in template_paths_by_id.get(plan.harness.id, ())
    ]

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
            endpoint_template=True,
            deployment=deployment,
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
    template_paths_by_id = {
        plan.harness.id: _cli_proxy_template_paths(plan.source_root, plan.harness.id)
        for plan in harnesses
    }

    jobs: list[Job] = [
        SyncRuntimeInstallJob(
            source_root=str(Path(sync_env.ssot_home) / "sync"),
            releases_root=str(Path(sync_env.runtime_home) / "sync-releases"),
            current_link=str(Path(sync_env.runtime_home) / "sync-current"),
            timeout_ms=sync_env.install_timeout_ms,
        ),
        *(
            DirJob(
                src=plan.source_root,
                dst=plan.root,
                scope="Children",
                preserve_paths=template_paths_by_id.get(plan.harness.id, ()),
            )
            for plan in harnesses
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
            gateway_host=gateway_host,
        ),
    ]

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
    "top_level_entry_names",
]
