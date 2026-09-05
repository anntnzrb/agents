# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for package validation, manifest inspection, and import extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sync.packages.validate import (
    extract_import_specifiers,
    missing_package_roots,
    package_has_build_script,
    package_is_healthy,
)

if TYPE_CHECKING:
    from pathlib import Path

_FIXTURE_SOURCE = """// import "fake-line";
// require("fake-line-req");
// import("fake-line-dyn");
/*
 * import "fake-block";
 * const r = require("fake-block-req");
 * import("fake-block-dyn");
 */
const doubleQuoteStr =
  "import \\"fake-str\\" require(\\"fake-str-req\\") import(\\"fake-str-dyn\\")";
const singleQuoteStr =
  'import "fake-str-single" require("fake-str-single-req") ' +
  'import("fake-str-single-dyn")';
const templateLiteral = `
  import "fake-tpl-multiline";
  const x = require("fake-tpl-req");
  import("fake-tpl-dyn");
`;
const interpolatedTpl = `outer ${
  "import \\'fake-in-str\\'"
} ${(() => require("real-inside-tpl-expr"))()}`;

import chalk from "chalk";
import { Foo } from "@scope/pkg/bar";
import type { Baz } from "typepkg";
export { foo } from "somepkg";
export * from "wildcardpkg";
const x = require("required");
const spacedReq = require(  "@scoped/spaced-req"  );
const y = import("dynamic");
const dynScoped = import("@scoped/dynamic");
import ".";
import "./local-file";
import "../parent-file";
import "node:fs";
import "node:path/posix";
import "bun:sqlite";
import "data:base64,abc";
"""


def test_extract_import_specifiers_extracts_real_imports_and_ignores_comments() -> None:
    """extract_import_specifiers extracts real imports and ignores comments."""
    specifiers = extract_import_specifiers(_FIXTURE_SOURCE)

    # Real imports, exports, requires, and dynamic imports
    assert "chalk" in specifiers
    assert "@scope/pkg/bar" in specifiers
    assert "somepkg" in specifiers
    assert "wildcardpkg" in specifiers
    assert "required" in specifiers
    assert "@scoped/spaced-req" in specifiers
    assert "dynamic" in specifiers
    assert "@scoped/dynamic" in specifiers
    assert "real-inside-tpl-expr" in specifiers

    # Relative, builtins, and data URIs are extracted at this stage
    assert "." in specifiers
    assert "./local-file" in specifiers
    assert "../parent-file" in specifiers
    assert "node:fs" in specifiers
    assert "node:path/posix" in specifiers
    assert "bun:sqlite" in specifiers
    assert "data:base64,abc" in specifiers

    # Comments must be ignored
    assert "fake-line" not in specifiers
    assert "fake-line-req" not in specifiers
    assert "fake-line-dyn" not in specifiers
    assert "fake-block" not in specifiers
    assert "fake-block-req" not in specifiers
    assert "fake-block-dyn" not in specifiers

    # String and template literals must be ignored
    assert "fake-str" not in specifiers
    assert "fake-str-req" not in specifiers
    assert "fake-str-dyn" not in specifiers
    assert "fake-str-single" not in specifiers
    assert "fake-str-single-req" not in specifiers
    assert "fake-str-single-dyn" not in specifiers
    assert "fake-tpl-multiline" not in specifiers
    assert "fake-tpl-req" not in specifiers
    assert "fake-tpl-dyn" not in specifiers
    assert "fake-in-str" not in specifiers

    # Type-only imports are erased
    assert "typepkg" not in specifiers


def test_missing_package_roots_reports_only_real_package_roots(
    tmp_path: Path,
) -> None:
    """missing_package_roots reports only uninstalled package roots."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    main_source = (
        'import chalk from "chalk/subpath";\n'
        'import { helper } from "@scoped/pkg/deep/path";\n'
        'import fs from "node:fs";\n'
        'import path from "node:path/posix";\n'
        'import { Database } from "bun:sqlite";\n'
        'import "bun";\n'
        'import "./local";\n'
        'import "../parent";\n'
        'import ".";\n'
        'import "data:text/javascript,console.log(1)";\n'
        'const x = require("some-pkg");\n'
    )
    _ = (skills_dir / "main.ts").write_text(main_source, encoding="utf-8")

    assert missing_package_roots(str(tmp_path)) == [
        "@scoped/pkg",
        "chalk",
        "some-pkg",
    ]

    (tmp_path / "node_modules" / "@scoped" / "pkg").mkdir(parents=True, exist_ok=True)
    (tmp_path / "node_modules" / "chalk").mkdir(parents=True, exist_ok=True)
    (tmp_path / "node_modules" / "some-pkg").mkdir(parents=True, exist_ok=True)

    assert missing_package_roots(str(tmp_path)) == []
    assert package_is_healthy(str(tmp_path)) is True


def test_extract_import_specifiers_ignores_property_accesses() -> None:
    """extract_import_specifiers ignores properties and handles invalid syntax."""
    code = (
        'const a = obj.require("ignored-prop-pkg");\n'
        'const b = myObj.nested.require("ignored-nested-pkg");\n'
        'const c = require("valid-req-pkg");\n'
    )
    specifiers = extract_import_specifiers(code)
    assert "valid-req-pkg" in specifiers
    assert "ignored-prop-pkg" not in specifiers
    assert "ignored-nested-pkg" not in specifiers

    assert extract_import_specifiers("const broken = {{{;") == []


def test_extract_import_specifiers_ignores_regex_literals() -> None:
    """extract_import_specifiers ignores require/import inside regex literals."""
    code = (
        'const a = /require\\("phantom-require"\\)/g;\n'
        'const b = /import\\("phantom-import"\\)/i;\n'
        "const c = /[/]/;\n"
        'const d = /\\/require\\("phantom-escaped"\\)/;\n'
        'const e = !/require\\("phantom-negated"\\)/.test(s);\n'
        'const f = [ /require\\("phantom-array"\\)/ ];\n'
        'const g = { pattern: /require\\("phantom-obj"\\)/ };\n'
        'const h = cond ? /require\\("phantom-ternary1"\\)/ : '
        '/require\\("phantom-ternary2"\\)/;\n'
        'const numDiv = 5 / require("real-after-div");\n'
        'const real = require("real-package");\n'
    )
    specifiers = extract_import_specifiers(code)
    assert specifiers == ["real-after-div", "real-package"]
    assert "phantom-require" not in specifiers
    assert "phantom-import" not in specifiers
    assert "phantom-escaped" not in specifiers
    assert "phantom-negated" not in specifiers
    assert "phantom-array" not in specifiers
    assert "phantom-obj" not in specifiers
    assert "phantom-ternary1" not in specifiers
    assert "phantom-ternary2" not in specifiers


def test_package_is_healthy_propagates_corrupt_package_json(
    tmp_path: Path,
) -> None:
    """package_is_healthy propagates parse error with path diagnostics."""
    pkg_json = tmp_path / "package.json"
    _ = pkg_json.write_text("{corrupt json", encoding="utf-8")
    with pytest.raises(ValueError, match=f"parse {pkg_json}"):
        _ = package_is_healthy(str(tmp_path))


def test_package_has_build_script_propagates_corrupt_package_json(
    tmp_path: Path,
) -> None:
    """package_has_build_script propagates parse error with path diagnostics."""
    pkg_json = tmp_path / "package.json"
    _ = pkg_json.write_text("{corrupt json", encoding="utf-8")
    with pytest.raises(ValueError, match=f"parse {pkg_json}"):
        _ = package_has_build_script(str(tmp_path))


def test_missing_package_roots_propagates_unreadable_source_file(
    tmp_path: Path,
) -> None:
    """missing_package_roots propagates read error with path diagnostics."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    bad_file = skills_dir / "invalid.ts"
    _ = bad_file.write_bytes(b"\xff\xfe\x00\x00")
    with pytest.raises(ValueError, match=f"read {bad_file}"):
        _ = missing_package_roots(str(tmp_path))


def test_package_is_healthy_propagates_unreadable_source_file(
    tmp_path: Path,
) -> None:
    """package_is_healthy propagates read error with path diagnostics."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    bad_file = skills_dir / "invalid.ts"
    _ = bad_file.write_bytes(b"\xff\xfe\x00\x00")
    with pytest.raises(ValueError, match=f"read {bad_file}"):
        _ = package_is_healthy(str(tmp_path))
