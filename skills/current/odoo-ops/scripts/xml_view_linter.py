#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "lxml>=5.0",
# ]
# ///
"""AST and semantic linter for Odoo 17 XML views and QWeb templates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]


class Severity(StrEnum):
    """Violation severity levels."""

    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class ViewViolation(TypedDict):
    """Structured violation payload."""

    file: str
    line: int
    rule_id: str
    severity: str
    message: str
    snippet: str
    fix_suggestion: str


@dataclass(frozen=True)
class RuleDefinition:
    """Linter rule metadata."""

    rule_id: str
    severity: Severity
    description: str


RULES = {
    "ODOO_XML_001": RuleDefinition(
        "ODOO_XML_001",
        Severity.CRITICAL,
        "Deprecated attrs='' or states='' attribute in Odoo 17 (use direct invisible/readonly/required expressions)",
    ),
    "ODOO_XML_002": RuleDefinition(
        "ODOO_XML_002",
        Severity.CRITICAL,
        "Deprecated invisible='' in <tree> column (use column_invisible='' for list columns in Odoo 17)",
    ),
    "ODOO_XML_003": RuleDefinition(
        "ODOO_XML_003",
        Severity.WARNING,
        "Fragile XPath using @class exact match (use Odoo native hasclass('...') function)",
    ),
    "ODOO_XML_004": RuleDefinition(
        "ODOO_XML_004",
        Severity.WARNING,
        "Fragile positional XPath indexing (e.g. //group[1], //div[2]); use semantic target by @name",
    ),
    "ODOO_XML_005": RuleDefinition(
        "ODOO_XML_005",
        Severity.CRITICAL,
        "Duplicate field declaration in the same view without mutually exclusive invisible conditions",
    ),
    "ODOO_XML_006": RuleDefinition(
        "ODOO_XML_006",
        Severity.WARNING,
        "Inner <group> or <page> missing semantic name='' attribute for extensibility",
    ),
    "ODOO_XML_007": RuleDefinition(
        "ODOO_XML_007",
        Severity.WARNING,
        "Bootstrap alert (class alert-*) missing accessible role='status' or role='alert' attribute",
    ),
    "ODOO_XML_008": RuleDefinition(
        "ODOO_XML_008",
        Severity.WARNING,
        "Literal <xpath> tag inside non-inherited QWeb <template> without inherit_id",
    ),
    "ODOO_XML_009": RuleDefinition(
        "ODOO_XML_009",
        Severity.INFO,
        "Dead commented-out XML UI code block",
    ),
}

POSITIONAL_XPATH_PATTERN = re.compile(r"//?(?:[a-zA-Z0-9_-]+)\[\s*\d+\s*\]")
EXACT_CLASS_XPATH_PATTERN = re.compile(r"@class\s*=\s*['\"][^'\"]+['\"]")
DEAD_COMMENTED_TAG_PATTERN = re.compile(
    r"<!--\s*<(?:field|button|group|page|tree|form|xpath|record)\b[\s\S]*?-->"
)


class OdooXmlViewLinter:
    """Deterministic AST & Semantic Linter for Odoo 17 XML views."""

    def __init__(self, root_path: Path | None = None) -> None:
        """Initialize linter with optional project root path for relative reporting."""
        self.root_path = root_path.resolve() if root_path else Path.cwd().resolve()

    def _relpath(self, path: Path) -> str:
        """Return clean relative path string."""
        try:
            return str(path.resolve().relative_to(self.root_path))
        except ValueError:
            return str(path.resolve())

    def lint_file(self, file_path: Path) -> list[ViewViolation]:
        """Parse and lint a single XML file."""
        path = file_path.resolve()
        if not path.is_file() or path.suffix.lower() != ".xml":
            return []

        try:
            content_bytes = path.read_bytes()
            content_text = content_bytes.decode("utf-8", errors="replace")
        except Exception as err:
            return [
                ViewViolation(
                    file=self._relpath(path),
                    line=1,
                    rule_id="SYNTAX_ERROR",
                    severity=Severity.CRITICAL.value,
                    message=f"Failed to read XML file: {err}",
                    snippet="",
                    fix_suggestion="Ensure file exists and is valid UTF-8 text.",
                )
            ]

        violations: list[ViewViolation] = []

        # 1. Regex-based checks on raw content (e.g. commented-out code blocks)
        self._check_dead_comments(path, content_text, violations)

        # 2. AST-based checks with lxml
        try:
            parser = etree.XMLParser(recover=False, remove_blank_text=False)
            tree = etree.fromstring(content_bytes, parser=parser)
        except etree.XMLSyntaxError as err:
            violations.append(
                ViewViolation(
                    file=self._relpath(path),
                    line=err.lineno if hasattr(err, "lineno") else 1,
                    rule_id="XML_SYNTAX_ERROR",
                    severity=Severity.CRITICAL.value,
                    message=f"XML syntax error: {err.msg if hasattr(err, 'msg') else str(err)}",
                    snippet="",
                    fix_suggestion="Fix malformed XML tags, missing closing tags, or unescaped characters.",
                )
            )
            return violations

        self._check_deprecated_attrs_and_states(path, tree, violations)
        self._check_tree_column_invisible(path, tree, violations)
        self._check_xpath_expressions(path, tree, violations)
        self._check_duplicate_fields(path, tree, violations)
        self._check_unnamed_groups_and_pages(path, tree, violations)
        self._check_accessible_alerts(path, tree, violations)
        self._check_template_xpath_injections(path, tree, violations)

        # Sort violations by line number
        violations.sort(key=lambda v: (v["line"], v["rule_id"]))
        return violations

    def _check_dead_comments(
        self, path: Path, text: str, violations: list[ViewViolation]
    ) -> None:
        """Detect commented-out XML tags."""
        for match in DEAD_COMMENTED_TAG_PATTERN.finditer(text):
            line_num = text[: match.start()].count("\n") + 1
            snippet = match.group(0).strip()
            first_line = snippet.split("\n")[0]
            violations.append(
                ViewViolation(
                    file=self._relpath(path),
                    line=line_num,
                    rule_id="ODOO_XML_009",
                    severity=Severity.INFO.value,
                    message="Commented-out XML UI code detected.",
                    snippet=first_line[:80] + ("..." if len(first_line) > 80 else ""),
                    fix_suggestion="Delete obsolete commented-out XML tags to maintain a clean codebase.",
                )
            )

    def _check_deprecated_attrs_and_states(
        self, path: Path, tree: etree._Element, violations: list[ViewViolation]
    ) -> None:
        """Rule ODOO_XML_001: attrs='' and states='' are deprecated in Odoo 17."""
        for elem in tree.iter():
            if not isinstance(elem.tag, str):
                continue
            line = getattr(elem, "sourceline", 1)
            if "attrs" in elem.attrib:
                val = elem.attrib.get("attrs", "")
                violations.append(
                    ViewViolation(
                        file=self._relpath(path),
                        line=line,
                        rule_id="ODOO_XML_001",
                        severity=Severity.CRITICAL.value,
                        message=f"Deprecated 'attrs' attribute on <{elem.tag}> in Odoo 17.",
                        snippet=f'<{elem.tag} name="{elem.attrib.get("name", "")}" attrs="{val}">',
                        fix_suggestion="Replace attrs='{...}' with direct invisible='...', readonly='...', or required='...' attributes.",
                    )
                )
            if "states" in elem.attrib:
                val = elem.attrib.get("states", "")
                violations.append(
                    ViewViolation(
                        file=self._relpath(path),
                        line=line,
                        rule_id="ODOO_XML_001",
                        severity=Severity.CRITICAL.value,
                        message=f"Deprecated 'states' attribute on <{elem.tag}> in Odoo 17.",
                        snippet=f'<{elem.tag} name="{elem.attrib.get("name", "")}" states="{val}">',
                        fix_suggestion=f"Replace states='{val}' with invisible=\"state not in {val.split(',')}\".",
                    )
                )

    def _check_tree_column_invisible(
        self, path: Path, tree: etree._Element, violations: list[ViewViolation]
    ) -> None:
        """Rule ODOO_XML_002: <tree><field invisible='1'/> must be column_invisible='1'."""
        # Find all field elements directly or inside tree/list containers
        for tree_node in tree.xpath("//tree | //list"):
            for field_node in tree_node.xpath(".//field"):
                line = getattr(field_node, "sourceline", 1)
                inv_val = field_node.attrib.get("invisible")
                # If invisible is defined on a tree field, and column_invisible is not present
                if inv_val is not None and "column_invisible" not in field_node.attrib:
                    field_name = field_node.attrib.get("name", "unnamed")
                    violations.append(
                        ViewViolation(
                            file=self._relpath(path),
                            line=line,
                            rule_id="ODOO_XML_002",
                            severity=Severity.CRITICAL.value,
                            message=(
                                f"Field '{field_name}' inside <tree>/<list> uses 'invisible' "
                                "instead of 'column_invisible'."
                            ),
                            snippet=f'<field name="{field_name}" invisible="{inv_val}"/>',
                            fix_suggestion=f'Change invisible="{inv_val}" to column_invisible="{inv_val}".',
                        )
                    )

    def _check_xpath_expressions(
        self, path: Path, tree: etree._Element, violations: list[ViewViolation]
    ) -> None:
        """Rules ODOO_XML_003 and ODOO_XML_004: XPath fragilities."""
        for xpath_node in tree.xpath("//xpath"):
            line = getattr(xpath_node, "sourceline", 1)
            expr = xpath_node.attrib.get("expr", "")

            # Check exact @class matching
            if EXACT_CLASS_XPATH_PATTERN.search(expr):
                match = EXACT_CLASS_XPATH_PATTERN.search(expr)
                exact_class_str = match.group(0) if match else ""
                violations.append(
                    ViewViolation(
                        file=self._relpath(path),
                        line=line,
                        rule_id="ODOO_XML_003",
                        severity=Severity.WARNING.value,
                        message=f"XPath expression uses brittle exact class matching: '{expr}'.",
                        snippet=f'<xpath expr="{expr}" position="{xpath_node.attrib.get("position", "")}">',
                        fix_suggestion=f"Replace {exact_class_str} with native hasclass('className').",
                    )
                )

            # Check positional index matching
            if POSITIONAL_XPATH_PATTERN.search(expr):
                violations.append(
                    ViewViolation(
                        file=self._relpath(path),
                        line=line,
                        rule_id="ODOO_XML_004",
                        severity=Severity.WARNING.value,
                        message=f"XPath expression uses fragile positional index: '{expr}'.",
                        snippet=f'<xpath expr="{expr}" position="{xpath_node.attrib.get("position", "")}">',
                        fix_suggestion="Target elements semantically by @name (e.g. //field[@name='field_name'] or //group[@name='group_name']).",
                    )
                )

    def _check_duplicate_fields(
        self, path: Path, tree: etree._Element, violations: list[ViewViolation]
    ) -> None:
        """Rule ODOO_XML_005: Duplicate field names in the same view arch."""
        # Find view architectures
        for arch_node in tree.xpath("//field[@name='arch']"):
            seen_fields: dict[str, tuple[int, etree._Element]] = {}
            for field_node in arch_node.xpath(".//form//field | .//tree//field"):
                # Check if this field belongs to an embedded relational sub-form or sub-tree
                ancestors = list(field_node.iterancestors())
                # If there is a <field> ancestor between field_node and arch_node, it is a sub-field of a relational field
                field_ancestors = [
                    a for a in ancestors if a != arch_node and a.tag == "field"
                ]
                if field_ancestors:
                    continue

                field_name = field_node.attrib.get("name")
                if not field_name:
                    continue

                line = getattr(field_node, "sourceline", 1)
                inv = field_node.attrib.get("invisible")

                if field_name in seen_fields:
                    prev_line, prev_node = seen_fields[field_name]
                    prev_inv = prev_node.attrib.get("invisible")
                    groups_val = field_node.attrib.get("groups", "").strip()
                    prev_groups_val = prev_node.attrib.get("groups", "").strip()
                    is_mutually_exclusive_groups = bool(
                        groups_val
                        and prev_groups_val
                        and (
                            groups_val == f"!{prev_groups_val}"
                            or prev_groups_val == f"!{groups_val}"
                        )
                    )

                    # If at least one is unconditional (e.g. invisible="1" or no invisible attribute)
                    # or both have the exact same condition, flag as duplicate collision
                    is_duplicate_collision = not is_mutually_exclusive_groups and (
                        (inv is None and prev_inv is None)
                        or (inv == "1" and prev_inv is None)
                        or (prev_inv == "1" and inv is None)
                        or (inv == prev_inv)
                    )
                    if is_duplicate_collision:
                        violations.append(
                            ViewViolation(
                                file=self._relpath(path),
                                line=line,
                                rule_id="ODOO_XML_005",
                                severity=Severity.CRITICAL.value,
                                message=(
                                    f"Duplicate declaration of field '{field_name}' in the same view "
                                    f"(previously declared on line {prev_line})."
                                ),
                                snippet=f'<field name="{field_name}"/>',
                                fix_suggestion=(
                                    f"Remove redundant invisible field '{field_name}' or ensure both occurrences "
                                    "have mutually exclusive visibility conditions to avoid OWL desynchronization."
                                ),
                            )
                        )
                else:
                    seen_fields[field_name] = (line, field_node)
    def _check_unnamed_groups_and_pages(
        self, path: Path, tree: etree._Element, violations: list[ViewViolation]
    ) -> None:
        """Rule ODOO_XML_006: Groups and notebook pages should have name='' attribute."""
        for page_node in tree.xpath("//page[not(@name)]"):
            line = getattr(page_node, "sourceline", 1)
            page_string = page_node.attrib.get("string", "unnamed")
            violations.append(
                ViewViolation(
                    file=self._relpath(path),
                    line=line,
                    rule_id="ODOO_XML_006",
                    severity=Severity.WARNING.value,
                    message=f"<page string='{page_string}'> is missing a semantic 'name' attribute.",
                    snippet=f'<page string="{page_string}">',
                    fix_suggestion=f'Add a semantic identifier name="{page_string.lower().replace(" ", "_")}_page" to enable clean XPath inheritance.',
                )
            )

        # Check inner groups (excluding 2-column outer layout wrapper groups that only hold sub-groups)
        for group_node in tree.xpath("//group[not(@name)]"):
            line = getattr(group_node, "sourceline", 1)
            # If this group contains only other groups, it is an outer 2-column layout wrapper
            child_tags = [c.tag for c in group_node if isinstance(c.tag, str)]
            if child_tags and all(tag == "group" for tag in child_tags):
                continue

            # If inside an inherited xpath with position="after"/"inside", it should have a name
            # Check if group has fields or string
            has_fields = any(tag == "field" for tag in child_tags)
            group_string = group_node.attrib.get("string")
            if has_fields:
                snippet_str = (
                    f'<group string="{group_string}">' if group_string else "<group>"
                )
                violations.append(
                    ViewViolation(
                        file=self._relpath(path),
                        line=line,
                        rule_id="ODOO_XML_006",
                        severity=Severity.WARNING.value,
                        message="<group> containing fields is missing a semantic 'name' attribute.",
                        snippet=snippet_str,
                        fix_suggestion='Add name="group_..." attribute to allow downstream modules to target this group cleanly.',
                    )
                )

    def _check_accessible_alerts(
        self, path: Path, tree: etree._Element, violations: list[ViewViolation]
    ) -> None:
        """Rule ODOO_XML_007: Alert div missing role='status' or role='alert'."""
        for div_node in tree.xpath("//div[contains(@class, 'alert')]"):
            line = getattr(div_node, "sourceline", 1)
            role = div_node.attrib.get("role")
            if not role or role not in ("status", "alert", "alertdialog"):
                class_str = div_node.attrib.get("class", "alert")
                violations.append(
                    ViewViolation(
                        file=self._relpath(path),
                        line=line,
                        rule_id="ODOO_XML_007",
                        severity=Severity.WARNING.value,
                        message="Bootstrap alert container lacks accessible role attribute (role='status' or role='alert').",
                        snippet=f'<div class="{class_str}">',
                        fix_suggestion='Add role="status" or role="alert" to comply with WAI-ARIA and Odoo 17 view validation.',
                    )
                )

    def _check_template_xpath_injections(
        self, path: Path, tree: etree._Element, violations: list[ViewViolation]
    ) -> None:
        """Rule ODOO_XML_008: Literal <xpath> inside non-inherited <template>."""
        for template_node in tree.xpath("//template[not(@inherit_id)]"):
            for xpath_node in template_node.xpath(".//xpath"):
                line = getattr(xpath_node, "sourceline", 1)
                expr = xpath_node.attrib.get("expr", "")
                violations.append(
                    ViewViolation(
                        file=self._relpath(path),
                        line=line,
                        rule_id="ODOO_XML_008",
                        severity=Severity.WARNING.value,
                        message=(
                            f"Literal <xpath expr='{expr}'> found inside non-inherited <template id='{template_node.attrib.get('id', '')}'>. "
                            "XPaths only function when template has an inherit_id."
                        ),
                        snippet=f'<xpath expr="{expr}" position="{xpath_node.attrib.get("position", "")}">',
                        fix_suggestion="Add inherit_id='...' to the <template> tag or inject CSS/JS via assets bundles instead of raw XPath tags.",
                    )
                )

    def lint_directory(self, dir_path: Path) -> list[ViewViolation]:
        """Lint all XML files within a directory recursively."""
        violations: list[ViewViolation] = []
        path = dir_path.resolve()
        if not path.is_dir():
            return violations

        for xml_file in sorted(path.rglob("*.xml")):
            # Skip hidden folders or test output files if any
            if any(part.startswith(".") for part in xml_file.parts):
                continue
            violations.extend(self.lint_file(xml_file))

        return violations

    def lint_module(self, module_dir: Path) -> list[ViewViolation]:
        """Lint standard XML directories in an Odoo module."""
        path = module_dir.resolve()
        if not path.is_dir():
            return []

        violations: list[ViewViolation] = []
        target_subdirs = ("views", "wizard", "wizards", "report", "reports", "data")
        found_any = False
        for subdir_name in target_subdirs:
            sub = path / subdir_name
            if sub.is_dir():
                found_any = True
                violations.extend(self.lint_directory(sub))

        # If none of the standard subdirs exist, lint the whole module folder
        if not found_any:
            violations.extend(self.lint_directory(path))

        return violations


def format_violations_human(violations: list[ViewViolation]) -> str:
    """Format violations list into a clean human-readable terminal output."""
    if not violations:
        return "[OK] All XML views passed Odoo 17 validation with 0 violations.\n"

    critical_count = sum(
        1 for v in violations if v["severity"] == Severity.CRITICAL.value
    )
    warning_count = sum(
        1 for v in violations if v["severity"] == Severity.WARNING.value
    )
    info_count = sum(1 for v in violations if v["severity"] == Severity.INFO.value)

    lines: list[str] = [
        f"=== Odoo 17 XML View Linter Report ({len(violations)} issues found) ===",
        f"Summary: {critical_count} Critical, {warning_count} Warnings, {info_count} Info\n",
    ]

    # Group by file
    by_file: dict[str, list[ViewViolation]] = {}
    for v in violations:
        by_file.setdefault(v["file"], []).append(v)

    for file_name, file_violations in by_file.items():
        lines.append(f"File: {file_name}")
        for v in file_violations:
            sev_tag = f"[{v['severity']}]"
            lines.append(
                f"  Line {v['line']:4d} {sev_tag:10s} {v['rule_id']}: {v['message']}"
            )
            if v["snippet"]:
                lines.append(f"            Snippet : {v['snippet']}")
            if v["fix_suggestion"]:
                lines.append(f"            Fix     : {v['fix_suggestion']}")
        lines.append("")

    return "\n".join(lines)


def format_violations_json(violations: list[ViewViolation]) -> str:
    """Format violations list into JSON string."""
    critical_count = sum(
        1 for v in violations if v["severity"] == Severity.CRITICAL.value
    )
    warning_count = sum(
        1 for v in violations if v["severity"] == Severity.WARNING.value
    )
    info_count = sum(1 for v in violations if v["severity"] == Severity.INFO.value)

    payload = {
        "success": critical_count == 0,
        "total_violations": len(violations),
        "critical": critical_count,
        "warnings": warning_count,
        "info": info_count,
        "violations": violations,
    }
    return json.dumps(payload, indent=2)
