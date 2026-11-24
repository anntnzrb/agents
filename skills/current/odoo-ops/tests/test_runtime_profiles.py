"""Profiles select the container runtime, so two Odoo versions can run side by side."""

import argparse
import configparser
import dataclasses
from collections.abc import Iterator
from pathlib import Path

import odooctl
import pytest
from _narrow import parse_json_dict


@pytest.fixture(autouse=True)
def restore_runtime() -> Iterator[None]:
    """Profile loading mutates the shared RUNTIME; give each test a clean copy."""
    saved = dataclasses.replace(odooctl.RUNTIME)
    yield
    for f in dataclasses.fields(odooctl.RuntimeConfig):
        setattr(odooctl.RUNTIME, f.name, getattr(saved, f.name))


@pytest.fixture
def no_port_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("ODOO_HTTP_PORT", "ODOO_TEST_HTTP_PORT", "POSTGRES_PORT"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.usefixtures("no_port_env")
def test_default_profile_keeps_current_odoo17_stack() -> None:
    odooctl._apply_runtime_profile(odooctl.DEFAULT_PROFILE)
    rt = odooctl.RUNTIME
    assert odooctl.DEFAULT_PROFILE == "erptech17"
    assert rt.odoo_version == 17
    assert (rt.pod, rt.db_container, rt.web_container) == (
        "odoo-pod",
        "odoo-db",
        "odoo-web",
    )
    assert rt.image == "localhost/odoo17-local:17.0-e-20260527"
    assert (rt.http_port, rt.test_http_port, rt.postgres_port) == (8069, 8079, 5432)
    assert rt.test_container_prefix == "odoo-test-"
    assert odooctl._resolve_runtime() == Path("/opt/odoo17")


@pytest.mark.usefixtures("no_port_env")
def test_odoo19_profile_uses_a_separate_stack() -> None:
    odooctl._apply_runtime_profile("erptech19")
    rt = odooctl.RUNTIME
    assert rt.odoo_version == 19
    names17 = {"odoo-pod", "odoo-db", "odoo-web"}
    assert names17.isdisjoint({rt.pod, rt.db_container, rt.web_container})
    assert {rt.http_port, rt.test_http_port, rt.postgres_port}.isdisjoint(
        {8069, 8079, 5432}
    )
    assert not rt.test_container_prefix.startswith("odoo-test-")
    assert odooctl._resolve_runtime() == Path("/opt/odoo19")


def test_port_environment_overrides_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODOO_HTTP_PORT", "9999")
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    odooctl._apply_runtime_profile("erptech19")
    assert odooctl.RUNTIME.http_port == 9999
    assert odooctl.RUNTIME.postgres_port == 5433


def test_unknown_profile_fails_and_lists_profiles() -> None:
    with pytest.raises(odooctl.CliError, match="erptech17") as excinfo:
        odooctl._apply_runtime_profile("erptech91")
    assert "erptech91" in str(excinfo.value)


def test_every_profile_names_an_existing_rules_file() -> None:
    profiles = sorted(odooctl.PROFILE_DIR.glob("*.json"))
    assert profiles
    for pfile in profiles:
        data = odooctl._read_profile(pfile.stem)
        rules = data.get("rules")
        assert isinstance(rules, str), pfile.name
        assert (odooctl.PROFILE_DIR / rules).is_file(), pfile.name
        assert isinstance(data.get("odoo_version"), int), pfile.name


@pytest.mark.usefixtures("no_port_env")
def test_env_reports_profile_version_and_rules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ODOO_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setenv("ODOO_ADDONS_PATH", str(tmp_path))

    def no_pod(pod_name: str | None = None) -> None:
        del pod_name

    def db_down() -> bool:
        return False

    monkeypatch.setattr(odooctl, "_get_pod_status", no_pod)
    monkeypatch.setattr(odooctl, "_is_db_container_running", db_down)
    odooctl._apply_runtime_profile("erptech19")
    args = argparse.Namespace(json=True, profile="erptech19", db="erptech19_base")
    assert odooctl.cmd_env_inspect(args) == 0
    out = parse_json_dict(capsys.readouterr().out)
    assert out["profile"] == "erptech19"
    assert out["odoo_version"] == 19
    assert out["podman_pod"] == "odoo19-pod"
    assert str(out["profile_rules"]).endswith("profiles/erptech.md")


@pytest.mark.usefixtures("no_port_env")
@pytest.mark.parametrize(
    "argv",
    [
        ["--profile", "erptech19", "--json", "env"],
        ["env", "--profile", "erptech19", "--json"],
    ],
)
def test_profile_and_json_flags_work_before_or_after_the_command(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ODOO_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setenv("ODOO_ADDONS_PATH", str(tmp_path))
    monkeypatch.setenv("POSTGRES_DB", "erptech19_base")

    def no_pod(pod_name: str | None = None) -> None:
        del pod_name

    def db_down() -> bool:
        return False

    monkeypatch.setattr(odooctl, "_get_pod_status", no_pod)
    monkeypatch.setattr(odooctl, "_is_db_container_running", db_down)
    assert odooctl.main(argv) == 0
    out = parse_json_dict(capsys.readouterr().out)
    assert out["profile"] == "erptech19"
    assert out["podman_pod"] == "odoo19-pod"


def test_dev_on_a_new_database_installs_every_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh runtime has no database yet; -i must create it instead of failing."""

    def no_database(
        sql: str, *, db: str, readonly: bool = False, tuples_only: bool = False
    ) -> str:
        del sql, readonly, tuples_only
        assert db == "postgres"
        return ""

    def no_module_query(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("must not query ir_module_module of a missing database")

    monkeypatch.setattr(odooctl, "_exec_sql", no_database)
    monkeypatch.setattr(odooctl, "_exec_sql_json", no_module_query)
    assert odooctl._uninstalled_modules(["web", "mail"], "erptech19_base") == [
        "web",
        "mail",
    ]


@pytest.mark.usefixtures("no_port_env")
def test_odoo_inside_the_pod_uses_the_internal_postgres_port(tmp_path: Path) -> None:
    """The host port is only a publish mapping; Odoo reaches Postgres on 5432 in-pod."""
    odooctl._apply_runtime_profile("erptech19")
    assert odooctl.RUNTIME.postgres_port != odooctl.POD_POSTGRES_PORT
    ctx = odooctl.WorkspaceContext(
        root=tmp_path,
        config_path=tmp_path / "odoo.conf",
        config=configparser.ConfigParser(),
        addons_paths=[tmp_path],
        effective_db_name="erptech19_base",
        runtime=tmp_path,
    )
    cmd = odooctl._build_test_cmd(ctx, "c", "erptech19_base", "/web", "web")
    assert cmd[cmd.index("--db_port") + 1] == "5432"
    assert "PORT=5432" in cmd
