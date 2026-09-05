# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for package validation, manifest inspection, and import extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sync.packages.validate import (
    extract_import_specifiers,
    missing_package_roots,
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
    (skills_dir / "main.ts").write_text(
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
        'const x = require("some-pkg");\n',
        encoding="utf-8",
    )

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
