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
    _ = config.write_text("{}", encoding="utf-8")
    toolchain = tmp_path / "toolchain"
    eslint = toolchain / "node_modules" / "eslint" / "bin" / "eslint.js"
    eslint.parent.mkdir(parents=True)
    _ = eslint.write_text(
        """const fs = require('fs');
const args = process.argv.slice(2);
if (!fs.existsSync(args[args.indexOf('--config') + 1])) process.exit(2);
const files = args.filter(x => x.endsWith('.js'));
const messages = args.includes('prettier/prettier: off') ? [] : [{line:1,column:1,ruleId:'prettier/prettier',message:'format'}];
console.log(JSON.stringify(files.map(filePath => ({filePath,messages}))));
process.exit(messages.length ? 1 : 0);
""",
        encoding="utf-8",
    )
    env = os.environ | {
        "ODOO_ADDONS_PATH": str(addons),
        "ODOO_RUNTIME_PATH": str(runtime),
        "ODOO_OPS_JS_TOOLCHAIN": str(toolchain),
    }

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "lint-js", "demo", *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    clean = run("--changed", "--json")
    assert clean.returncode == 0, clean.stderr
    payload = odooctl._to_str_dict(odooctl._json_loads(clean.stdout))
    assert payload["files_checked"] == 1
    assert payload["total_js_violations"] == 0
    formatted = run("--changed", "--format", "--json")
    assert formatted.returncode == 1, formatted.stderr
    payload = odooctl._to_str_dict(odooctl._json_loads(formatted.stdout))
    assert payload["total_js_violations"] == 1
    violations = payload["js_violations"]
    assert odooctl._is_obj_list(violations)
    violation = odooctl._to_str_dict(violations[0])
    assert violation["path"] == str(new)
    assert violation["ruleId"] == "prettier/prettier"
    invalid = run("--changed", "nonexistent-ref")
    assert invalid.returncode == 2
    config.unlink()
    missing = run()
    assert missing.returncode == 2
