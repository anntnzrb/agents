"""JavaScript linting through the public CLI and isolated external toolchain."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import odooctl
import pytest

CLI = Path(__file__).resolve().parent.parent / "scripts" / "cli.py"


def test_file_selection_and_command(tmp_path: Path) -> None:
    module = tmp_path / "addon"
    source = module / "static" / "src" / "nested" / "main.js"
    source.parent.mkdir(parents=True)
    _ = source.write_text("", encoding="utf-8")
    library = module / "static" / "lib" / "vendor.js"
    library.parent.mkdir(parents=True)
    _ = library.write_text("", encoding="utf-8")
    assert odooctl._js_files([module], None) == [source]
    assert odooctl._js_files([module], {library}) == []
    command = odooctl._js_lint_command(
        tmp_path, tmp_path / "config.json", [source], format_check=False
    )
    assert "prettier/prettier: off" in command
    assert str(source) in command
    assert "prettier/prettier: off" not in odooctl._js_lint_command(
        tmp_path, tmp_path / "config.json", [source], format_check=True
    )


@pytest.mark.skipif(
    not shutil.which("node") or not shutil.which("npm") or not shutil.which("git"),
    reason="requires local executables",
)
def test_cli_changed_format_and_config(tmp_path: Path) -> None:
    addons = tmp_path / "addons"
    source = addons / "demo" / "static" / "src"
    source.mkdir(parents=True)
    tracked = source / "tracked.js"
    _ = tracked.write_text("const a = 1;\n", encoding="utf-8")
    _ = subprocess.run(["git", "init", "-q", str(addons)], check=True)
    _ = subprocess.run(["git", "-C", str(addons), "add", "."], check=True)
    _ = subprocess.run(
        [
            "git",
            "-C",
            str(addons),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )
    new = source / "new.js"
    _ = new.write_text("const b = 2;\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    config = (
        runtime
        / "source"
        / "odoo-test"
        / "odoo"
        / "addons"
        / "web"
        / "tooling"
        / "_eslintrc.json"
    )
    config.parent.mkdir(parents=True)
    _ = config.write_text(
        '{"env":{"browser":true},"globals":{"odoo":"readonly"},'
        + '"extends":["eslint:recommended"],"rules":{"eqeqeq":"off",'
        + '"no-debugger":"error"}}',
        encoding="utf-8",
    )
    toolchain = tmp_path / "toolchain"
    eslint = toolchain / "node_modules" / "eslint" / "bin" / "eslint.js"
    eslint.parent.mkdir(parents=True)
    _ = eslint.write_text(
        """const fs = require('fs');
const args = process.argv.slice(2);
const config = JSON.parse(fs.readFileSync(args[args.indexOf('--config') + 1], 'utf8'));
fs.writeFileSync(process.env.CAPTURE_CONFIG, JSON.stringify(config));
const files = args.filter(x => x.endsWith('.js'));
const severity = Number(process.env.FAKE_SEVERITY || (args.includes('prettier/prettier: off') ? 0 : 2));
const messages = severity ? [{line:1,column:1,severity,ruleId:'prettier/prettier',message:'format'}] : [];
console.log(JSON.stringify(files.map(filePath => ({filePath,messages}))));
process.exit(severity === 2 ? 1 : 0);
""",
        encoding="utf-8",
    )
    env = os.environ | {
        "ODOO_ADDONS_PATH": str(addons),
        "ODOO_RUNTIME_PATH": str(runtime),
        "ODOO_OPS_JS_TOOLCHAIN": str(toolchain),
        "CAPTURE_CONFIG": str(tmp_path / "captured.json"),
    }

    def run(*args: str, severity: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "lint-js", "demo", *args],
            env=env | {"FAKE_SEVERITY": str(severity)} if severity else env,
            capture_output=True,
            text=True,
            check=False,
        )

    clean = run("--changed", "--json")
    assert clean.returncode == 0, clean.stderr
    payload = odooctl._to_str_dict(odooctl._json_loads(clean.stdout))
    assert payload["files_checked"] == 1
    assert payload["total_js_violations"] == 0
    effective = odooctl._to_str_dict(
        odooctl._json_loads((tmp_path / "captured.json").read_text(encoding="utf-8"))
    )
    assert effective["env"] == {"browser": True}
    assert effective["globals"] == {"odoo": "readonly"}
    assert effective["extends"] == ["eslint:recommended"]
    rules = odooctl._to_str_dict(effective["rules"])
    assert rules["eqeqeq"] == ["error", "always", {"null": "ignore"}]
    assert rules["no-debugger"] == "error"
    official = run("--changed", "--odoo-only", "--json")
    assert official.returncode == 0, official.stderr
    official_config = odooctl._to_str_dict(
        odooctl._json_loads((tmp_path / "captured.json").read_text(encoding="utf-8"))
    )
    assert official_config["rules"] == {"eqeqeq": "off", "no-debugger": "error"}
    warning = run("--changed", "--json", severity=1)
    assert warning.returncode == 0, warning.stderr
    warning_payload = odooctl._to_str_dict(odooctl._json_loads(warning.stdout))
    assert warning_payload["success"] is True
    assert warning_payload["total_js_violations"] == 1
    assert warning_payload["total_js_errors"] == 0
    assert warning_payload["total_js_warnings"] == 1
    warning_messages = warning_payload["js_violations"]
    assert odooctl._is_obj_list(warning_messages)
    assert odooctl._to_str_dict(warning_messages[0])["severity"] == 1
    human_warning = run("--changed", severity=1)
    assert " warning prettier/prettier " in human_warning.stdout
    assert "RESULT files=1 errors=0 warnings=1" in human_warning.stdout
    formatted = run("--changed", "--format", "--json")
    assert formatted.returncode == 1, formatted.stderr
    payload = odooctl._to_str_dict(odooctl._json_loads(formatted.stdout))
    assert payload["total_js_violations"] == 1
    assert payload["success"] is False
    assert payload["total_js_errors"] == 1
    assert payload["total_js_warnings"] == 0
    violations = payload["js_violations"]
    assert odooctl._is_obj_list(violations)
    violation = odooctl._to_str_dict(violations[0])
    assert violation["path"] == str(new)
    assert violation["ruleId"] == "prettier/prettier"
    assert violation["severity"] == 2
    human_error = run("--changed", severity=2)
    assert human_error.returncode == 1
    assert " error prettier/prettier " in human_error.stdout
    assert "RESULT files=1 errors=1 warnings=0" in human_error.stdout
    invalid = run("--changed", "nonexistent-ref")
    assert invalid.returncode == 2
    config.unlink()
    missing = run()
    assert missing.returncode == 2
