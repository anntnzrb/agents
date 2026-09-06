"""Unit tests for Odoo 17 XML View Linter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import odooctl
import pytest
from xml_view_linter import (
    OdooXmlViewLinter,
    format_violations_human,
    format_violations_json,
)


class TestXmlViewLinterRules:
    """Test AST rules against isolated synthetic XML snippets."""

    @pytest.fixture
    def linter(self, tmp_path: Path) -> OdooXmlViewLinter:
        """Create linter instance rooted at tmp_path."""
        return OdooXmlViewLinter(root_path=tmp_path)

    def test_deprecated_attrs_and_states(
        self, linter: OdooXmlViewLinter, tmp_path: Path
    ) -> None:
        """Verify rule ODOO_XML_001 catches attrs and states."""
        xml_file = tmp_path / "legacy.xml"
        xml_file.write_text(
            """<odoo>
                <record id="test_view" model="ir.ui.view">
                    <field name="arch" type="xml">
                        <form>
                            <field name="partner_id" attrs="{'invisible': [('is_company', '=', True)]}"/>
                            <field name="state" states="draft,open"/>
                        </form>
                    </field>
                </record>
            </odoo>""",
            encoding="utf-8",
        )
        violations = linter.lint_file(xml_file)
        rule_ids = [v["rule_id"] for v in violations]
        assert "ODOO_XML_001" in rule_ids
        assert len([r for r in rule_ids if r == "ODOO_XML_001"]) == 2

    def test_tree_column_invisible(
        self, linter: OdooXmlViewLinter, tmp_path: Path
    ) -> None:
        """Verify rule ODOO_XML_002 catches invisible on tree columns."""
        xml_file = tmp_path / "tree.xml"
        xml_file.write_text(
            """<odoo>
                <record id="test_tree" model="ir.ui.view">
                    <field name="arch" type="xml">
                        <tree string="Records">
                            <field name="name"/>
                            <field name="code" invisible="1"/>
                        </tree>
                    </field>
                </record>
            </odoo>""",
            encoding="utf-8",
        )
        violations = linter.lint_file(xml_file)
        assert any(v["rule_id"] == "ODOO_XML_002" for v in violations)
        assert any("column_invisible" in v["fix_suggestion"] for v in violations)

    def test_xpath_class_and_positional(
        self, linter: OdooXmlViewLinter, tmp_path: Path
    ) -> None:
        """Verify rules ODOO_XML_003 and ODOO_XML_004 catch xpath fragilities."""
        xml_file = tmp_path / "xpath.xml"
        xml_file.write_text(
            """<odoo>
                <record id="test_inherit" model="ir.ui.view">
                    <field name="inherit_id" ref="base.view_partner_form"/>
                    <field name="arch" type="xml">
                        <xpath expr="//div[@class='oe_title']" position="inside">
                            <field name="custom_title"/>
                        </xpath>
                        <xpath expr="//sheet/group[1]" position="inside">
                            <field name="custom_group"/>
                        </xpath>
                    </field>
                </record>
            </odoo>""",
            encoding="utf-8",
        )
        violations = linter.lint_file(xml_file)
        rule_ids = [v["rule_id"] for v in violations]
        assert "ODOO_XML_003" in rule_ids
        assert "ODOO_XML_004" in rule_ids

    def test_duplicate_fields_in_same_view(
        self, linter: OdooXmlViewLinter, tmp_path: Path
    ) -> None:
        """Verify rule ODOO_XML_005 catches duplicate field declarations."""
        xml_file = tmp_path / "dup.xml"
        xml_file.write_text(
            """<odoo>
                <record id="test_dup" model="ir.ui.view">
                    <field name="arch" type="xml">
                        <form>
                            <field name="active" invisible="1"/>
                            <sheet>
                                <group>
                                    <field name="active" widget="boolean_toggle"/>
                                </group>
                            </sheet>
                        </form>
                    </field>
                </record>
            </odoo>""",
            encoding="utf-8",
        )
        violations = linter.lint_file(xml_file)
        assert any(v["rule_id"] == "ODOO_XML_005" for v in violations)

    def test_unnamed_group_and_page(
        self, linter: OdooXmlViewLinter, tmp_path: Path
    ) -> None:
        """Verify rule ODOO_XML_006 catches un-named groups and pages."""
        xml_file = tmp_path / "unnamed.xml"
        xml_file.write_text(
            """<odoo>
                <record id="test_form" model="ir.ui.view">
                    <field name="arch" type="xml">
                        <form>
                            <sheet>
                                <notebook>
                                    <page string="General Info">
                                        <group>
                                            <field name="name"/>
                                        </group>
                                    </page>
                                </notebook>
                            </sheet>
                        </form>
                    </field>
                </record>
            </odoo>""",
            encoding="utf-8",
        )
        violations = linter.lint_file(xml_file)
        assert any(v["rule_id"] == "ODOO_XML_006" for v in violations)

    def test_accessible_alert_and_dead_comments(
        self, linter: OdooXmlViewLinter, tmp_path: Path
    ) -> None:
        """Verify rules ODOO_XML_007 and ODOO_XML_009."""
        xml_file = tmp_path / "misc.xml"
        xml_file.write_text(
            """<odoo>
                <record id="test_misc" model="ir.ui.view">
                    <field name="arch" type="xml">
                        <form>
                            <!-- <button name="action_old" type="object" string="Old"/> -->
                            <div class="alert alert-warning">Notice</div>
                        </form>
                    </field>
                </record>
            </odoo>""",
            encoding="utf-8",
        )
        violations = linter.lint_file(xml_file)
        rule_ids = [v["rule_id"] for v in violations]
        assert "ODOO_XML_007" in rule_ids
        assert "ODOO_XML_009" in rule_ids

    def test_clean_modern_view_passes_with_zero_violations(
        self, linter: OdooXmlViewLinter, tmp_path: Path
    ) -> None:
        """Verify modern Odoo 17 compliant XML produces 0 violations."""
        xml_file = tmp_path / "clean.xml"
        xml_file.write_text(
            """<odoo>
                <record id="test_clean_form" model="ir.ui.view">
                    <field name="name">test.model.form</field>
                    <field name="model">test.model</field>
                    <field name="arch" type="xml">
                        <form string="Test Model">
                            <sheet>
                                <div class="alert alert-info" role="status">Valid alert</div>
                                <group name="main_group">
                                    <group name="left_col">
                                        <field name="name" required="1"/>
                                        <field name="is_active" widget="boolean_toggle"/>
                                    </group>
                                    <group name="right_col">
                                        <field name="date" readonly="is_active"/>
                                    </group>
                                </group>
                                <notebook>
                                    <page name="notes_page" string="Notes">
                                        <field name="notes"/>
                                    </page>
                                </notebook>
                            </sheet>
                        </form>
                    </field>
                </record>
            </odoo>""",
            encoding="utf-8",
        )
        violations = linter.lint_file(xml_file)
        assert len(violations) == 0
        human_text = format_violations_human(violations)
        assert "[OK]" in human_text
        json_dict = json.loads(format_violations_json(violations))
        assert json_dict["success"] is True
        assert json_dict["total_violations"] == 0


class TestLintViewsCli:
    """Test CLI dispatch of lint-views subcommand in odooctl."""

    def test_cmd_lint_views_json_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Verify cmd_lint_views outputs structured JSON."""
        # Create a mock addon directory
        addon_dir = tmp_path / "mock_addon"
        views_dir = addon_dir / "views"
        views_dir.mkdir(parents=True)
        xml_file = views_dir / "clean_view.xml"
        xml_file.write_text(
            """<odoo>
                <record id="clean_view" model="ir.ui.view">
                    <field name="arch" type="xml">
                        <tree string="Clean">
                            <field name="name"/>
                        </tree>
                    </field>
                </record>
            </odoo>""",
            encoding="utf-8",
        )

        mock_ctx = odooctl.WorkspaceContext(
            root=tmp_path,
            config_path=tmp_path / "odoo.conf",
            config=None,  # pyright: ignore[reportArgumentType]
            addons_paths=[tmp_path],
            effective_db_name="test_db",
            runtime=tmp_path,
        )
        monkeypatch.setattr(odooctl, "_resolve_workspace", lambda: mock_ctx)
        monkeypatch.setattr(odooctl, "_resolve_addons", lambda: tmp_path)

        args = argparse.Namespace(
            target="mock_addon",
            profile="etech",
            strict=False,
            json=True,
            all=False,
        )

        exit_code = odooctl.cmd_lint_views(args)
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["total_violations"] == 0
