"""Regression and safety tests for Odoo safe_eval server action templates."""

import json
import unittest
from collections.abc import Callable
from pathlib import Path

import pytest
from _narrow import is_obj_dict, is_obj_list, is_obj_seq, parse_json

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class UserError(Exception):
    """Fake Odoo UserError conveying JSON payloads in safe_eval."""

    def __init__(self, message: str) -> None:
        """Initialize with serialized payload and parse JSON for inspection."""
        super().__init__(message)
        self.message: str = message
        self.payload: dict[str, object] = {}
        try:
            decoded = parse_json(message)
            if is_obj_dict(decoded):
                self.payload = {str(k): v for k, v in decoded.items()}
        except json.JSONDecodeError, UnicodeDecodeError:
            self.payload = {}


class FakeRecord:
    """Fake Odoo single record instance."""

    def __init__(
        self,
        record_id: int,
        name: str = "",
        active: bool = True,
        stage_id: int = 1,
    ) -> None:
        """Initialize record with ID, name, active status, and stage."""
        self.id: int = record_id
        self.name: str = name
        self.active: bool = active
        self.stage_id: int = stage_id

    def read(self, fields: list[str], load: bool = False) -> list[dict[str, object]]:
        """Read dictionary of requested field values."""
        _ = (fields, load)
        return [
            {
                "id": self.id,
                "name": self.name,
                "active": self.active,
                "stage_id": self.stage_id,
            }
        ]


class FakeRecordSet:
    """Fake Odoo recordset supporting browse/search/filter operations."""

    def __init__(self, records: list[FakeRecord]) -> None:
        """Initialize recordset from a sequence of records."""
        self._records: list[FakeRecord] = list(records)

    @property
    def ids(self) -> list[int]:
        """Return list of record IDs in the recordset."""
        return [r.id for r in self._records]

    def exists(self) -> FakeRecordSet:
        """Return self to simulate active database presence."""
        return self

    def __len__(self) -> int:
        """Return number of records in the recordset."""
        return len(self._records)

    def __getitem__(self, item: int | slice) -> FakeRecord | FakeRecordSet:
        """Index or slice the recordset."""
        res = self._records[item]
        if isinstance(res, list):
            return FakeRecordSet(res)
        return res

    def filtered(self, predicate: Callable[[FakeRecord], bool]) -> FakeRecordSet:
        """Filter recordset with a callable predicate."""
        return FakeRecordSet([r for r in self._records if predicate(r)])

    def mapped(self, field_name: str) -> list[object]:
        """Extract a single field across all records."""
        return [getattr(r, field_name) for r in self._records]

    def read(self, fields: list[str], load: bool = False) -> list[dict[str, object]]:
        """Read field dictionaries for each record."""
        _ = (fields, load)
        return [
            {
                "id": r.id,
                "name": r.name,
                "active": r.active,
                "stage_id": r.stage_id,
            }
            for r in self._records
        ]

    def write(self, vals: dict[str, object]) -> bool:
        """Mutate records in place."""
        for r in self._records:
            if "name" in vals:
                r.name = str(vals["name"])
        return True


class FakeModel:
    """Fake Odoo model supporting domain evaluation and read_group."""

    def __init__(self, records: list[FakeRecord] | None = None) -> None:
        """Initialize fake model with sample records."""
        self._records: list[FakeRecord] = records or []
        self._fields: dict[str, object] = {
            "id": type("Field", (), {"store": True})(),
            "name": type("Field", (), {"store": True})(),
            "active": type("Field", (), {"store": True})(),
            "stage_id": type("Field", (), {"store": True})(),
        }

    def search_count(self, domain: list[object]) -> int:
        """Count records matching a domain."""
        return len(self.search(domain))

    def search(
        self, domain: list[object], order: str = "id asc", limit: int | None = None
    ) -> FakeRecordSet:
        """Filter records matching domain clauses."""
        _ = order
        matched: list[FakeRecord] = list(self._records)
        for clause in domain:
            if is_obj_seq(clause) and len(clause) == 3:
                field = str(clause[0])
                op = str(clause[1])
                val = clause[2]
                if op == "=":
                    matched = [r for r in matched if getattr(r, field, None) == val]
                elif op == "!=":
                    matched = [r for r in matched if getattr(r, field, None) != val]
                elif op == "in":
                    matched = [
                        r
                        for r in matched
                        if isinstance(val, (list, tuple, set))
                        and getattr(r, field, None) in val
                    ]
                elif op == "not in":
                    matched = [
                        r
                        for r in matched
                        if isinstance(val, (list, tuple, set))
                        and getattr(r, field, None) not in val
                    ]
        if limit is not None:
            matched = matched[:limit]
        return FakeRecordSet(matched)

    def browse(self, ids: list[int] | None = None) -> FakeRecordSet:
        """Retrieve records by exact IDs."""
        if not ids:
            return FakeRecordSet([])
        matched = [r for r in self._records if r.id in ids]
        return FakeRecordSet(matched)

    def read_group(
        self,
        domain: list[object],
        fields: list[str],
        groupby: list[str],
        lazy: bool = False,
    ) -> list[dict[str, object]]:
        """Perform simulated aggregation over matching records."""
        _ = (fields, lazy)
        group_field = groupby[0] if groupby else "id"
        filtered_records = self.search(domain)
        if not filtered_records:
            return []
        counts: dict[object, int] = {}
        for r in filtered_records:
            val: object = getattr(r, group_field, False)
            counts[val] = counts.get(val, 0) + 1
        return [
            {
                group_field: (key, f"Stage {key}") if isinstance(key, int) else key,
                f"{group_field}_count": cnt,
                "__count": cnt,
            }
            for key, cnt in sorted(counts.items(), key=lambda x: str(x[0]))
        ]


class FakeCursor:
    """Fake database cursor recording statements and returning stubbed rows."""

    def __init__(self) -> None:
        """Initialize recorded statements and stubbed return buffers."""
        self.executed_statements: list[tuple[str, object]] = []
        self.rowcount: int = 0
        self._dictfetchone_data: dict[str, object] = {}
        self._dictfetchall_data: list[dict[str, object]] = []

    def execute(self, sql: str, params: object = None) -> None:
        """Record SQL execution call and parameters."""
        self.executed_statements.append((sql, params))

    def dictfetchone(self) -> dict[str, object]:
        """Return next stubbed dict row."""
        return self._dictfetchone_data

    def dictfetchall(self) -> list[dict[str, object]]:
        """Return stubbed dict rows."""
        return self._dictfetchall_data


class FakeEnv:
    """Fake Odoo Environment providing model registry and cursor."""

    def __init__(self, context: dict[str, object] | None = None) -> None:
        """Initialize environment with context, cursor, and default crm.lead model."""
        self.context: dict[str, object] = context or {}
        self.cr: FakeCursor = FakeCursor()
        self._models: dict[str, FakeModel] = {
            "crm.lead": FakeModel(
                [
                    FakeRecord(1, "Lead 1"),
                    FakeRecord(2, "Lead 2"),
                    FakeRecord(3, "Lead 3"),
                ]
            )
        }

    def __getitem__(self, model_name: str) -> FakeModel:
        """Access model by technical name."""
        if model_name not in self._models:
            self._models[model_name] = FakeModel()
        return self._models[model_name]

    def invalidate_all(self) -> None:
        """No-op cache invalidation stub."""


def render_template(filename: str, replacements: dict[str, str]) -> str:
    """Render a server action template file by substituting bracket placeholders."""
    template_path = TEMPLATES_DIR / filename
    content = template_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        content = content.replace(f"{{{{ {key} }}}}", value)
    return content


def _exec_template(code: str, env: FakeEnv) -> dict[str, object]:
    """Execute rendered server action template in trusted test harness."""
    local_scope: dict[str, object] = {"env": env, "UserError": UserError}
    exec(code, local_scope)  # noqa: S102 - safe execution of locally rendered test fixture
    return local_scope


class TestServerActionTemplatesSafety(unittest.TestCase):
    """Behavioral and contract safety tests for all server action templates."""

    def test_write_attestation_refusal_by_default_orm(self) -> None:
        """Verify unapproved ORM execution fails closed with write_not_approved."""
        code_orm = render_template(
            "server_action_execute_orm_small.py.tmpl",
            {
                "model_name": "crm.lead",
                "domain_literal": "[('active', '=', True)]",
                "extra_predicates": "",
                "expected_to_update": "2",
                "max_records": "10",
                "target_ids_literal": "[1, 2]",
                "excluded_ids_literal": "[]",
                "vals_literal": "{'name': 'Updated'}",
            },
        )
        env = FakeEnv()
        with pytest.raises(UserError, match="write_not_approved") as ctx:
            _ = _exec_template(code_orm, env)
        payload = ctx.value.payload
        assert payload.get("error") == "write_not_approved"
        assert payload.get("write_executed") is False

    def test_write_attestation_refusal_by_default_sql(self) -> None:
        """Verify unapproved SQL execution fails closed with write_not_approved."""
        code_sql = render_template(
            "server_action_execute_sql_set_based.py.tmpl",
            {
                "model_name": "crm.lead",
                "domain_literal": "[('active', '=', True)]",
                "expected_to_update": "2",
                "approved_dry_run_count": "2",
                "target_ids_literal": "[1, 2]",
                "excluded_ids_literal": "[]",
                "slug": "test_lead",
                "table_name": "crm_lead",
                "nullable_field": "target.stage_id",
                "comparison_value": "1",
                "m2m_table": "crm_lead_tag_rel",
                "left_id": "lead_id",
                "right_id": "tag_id",
                "m2m_target_ids_literal": "[10]",
                "additional_sql_predicates": "TRUE",
                "sql_set_clause": "name = 'Updated'",
                "update_params_literal": "",
                "final_invariant_failure_sql": "target.name != 'Updated'",
                "postcheck_params_literal": "",
                "compact_delta_by_stage_user_program_period": "none",
            },
        )
        env = FakeEnv()
        with pytest.raises(UserError, match="write_not_approved") as ctx:
            _ = _exec_template(code_sql, env)
        payload = ctx.value.payload
        assert payload.get("error") == "write_not_approved"
        assert payload.get("write_executed") is False

    def test_write_attestation_rejects_truthy_non_boolean(self) -> None:
        """Verify WRITE_APPROVED='True' string or 1 integer is rejected."""
        base_code = render_template(
            "server_action_execute_orm_small.py.tmpl",
            {
                "model_name": "crm.lead",
                "domain_literal": "[('active', '=', True)]",
                "extra_predicates": "",
                "expected_to_update": "2",
                "max_records": "10",
                "target_ids_literal": "[1, 2]",
                "excluded_ids_literal": "[]",
                "vals_literal": "{'name': 'Updated'}",
            },
        )
        for truthy_val in ("'True'", "'yes'", "1", "{'approved': True}"):
            with self.subTest(truthy_val=truthy_val):
                tampered = base_code.replace(
                    "WRITE_APPROVED = False", f"WRITE_APPROVED = {truthy_val}"
                )
                env = FakeEnv()
                with pytest.raises(UserError, match="write_not_approved") as ctx:
                    _ = _exec_template(tampered, env)
                assert ctx.value.payload.get("error") == "write_not_approved"

    def test_target_ids_strict_validation(self) -> None:
        """Verify invalid, empty, boolean, negative, duplicate, or mismatch target IDs fail."""
        invalid_cases: list[tuple[str, str]] = [
            ("[]", "invalid_target_ids"),
            ("[True, False]", "invalid_target_ids"),
            ("[-1, 2]", "invalid_target_ids"),
            ("[1, 1]", "duplicate_target_ids"),
            ("[1]", "target_ids_count_mismatch"),
        ]
        for target_literal, expected_err in invalid_cases:
            with self.subTest(target_literal=target_literal):
                code = render_template(
                    "server_action_execute_orm_small.py.tmpl",
                    {
                        "model_name": "crm.lead",
                        "domain_literal": "[('active', '=', True)]",
                        "extra_predicates": "",
                        "expected_to_update": "2",
                        "max_records": "10",
                        "target_ids_literal": target_literal,
                        "excluded_ids_literal": "[]",
                        "vals_literal": "{'name': 'Updated'}",
                    },
                ).replace("WRITE_APPROVED = False", "WRITE_APPROVED = True")
                env = FakeEnv()
                with pytest.raises(UserError, match=expected_err) as ctx:
                    _ = _exec_template(code, env)
                assert ctx.value.payload.get("error") == expected_err

    def test_target_and_excluded_ids_overlap_fails(self) -> None:
        """Verify overlap between TARGET_IDS and EXCLUDED_IDS is blocked."""
        code = render_template(
            "server_action_execute_orm_small.py.tmpl",
            {
                "model_name": "crm.lead",
                "domain_literal": "[('active', '=', True)]",
                "extra_predicates": "",
                "expected_to_update": "2",
                "max_records": "10",
                "target_ids_literal": "[1, 2]",
                "excluded_ids_literal": "[2, 3]",
                "vals_literal": "{'name': 'Updated'}",
            },
        ).replace("WRITE_APPROVED = False", "WRITE_APPROVED = True")
        env = FakeEnv()
        with pytest.raises(UserError, match="target_and_excluded_ids_overlap") as ctx:
            _ = _exec_template(code, env)
        assert ctx.value.payload.get("error") == "target_and_excluded_ids_overlap"

    def test_orm_target_swap_rejection_prevents_mutation(self) -> None:
        """Verify that when candidate IDs in database differ from TARGET_IDS, write is aborted."""
        code = render_template(
            "server_action_execute_orm_small.py.tmpl",
            {
                "model_name": "crm.lead",
                "domain_literal": "[('active', '=', True)]",
                "extra_predicates": "",
                "expected_to_update": "2",
                "max_records": "10",
                "target_ids_literal": "[1, 999]",  # target 999 not in database [1, 2, 3]
                "excluded_ids_literal": "[]",
                "vals_literal": "{'name': 'MUTATED'}",
            },
        ).replace("WRITE_APPROVED = False", "WRITE_APPROVED = True")
        env = FakeEnv()
        with pytest.raises(
            UserError, match=r"candidate_count_changed_before_write|target_ids_mismatch"
        ) as ctx:
            _ = _exec_template(code, env)
        payload = ctx.value.payload
        assert payload.get("write_executed") is False
        records = env["crm.lead"]._records
        assert all(r.name != "MUTATED" for r in records)

    def test_sql_execution_success_behavior(self) -> None:
        """Verify approved SQL execution produces client action notification."""
        code_sql = render_template(
            "server_action_execute_sql_set_based.py.tmpl",
            {
                "model_name": "crm.lead",
                "domain_literal": "[('active', '=', True)]",
                "expected_to_update": "2",
                "approved_dry_run_count": "2",
                "target_ids_literal": "[1, 2]",
                "excluded_ids_literal": "[]",
                "slug": "lead_bulk",
                "table_name": "crm_lead",
                "nullable_field": "target.stage_id",
                "comparison_value": "1",
                "m2m_table": "crm_lead_tag_rel",
                "left_id": "lead_id",
                "right_id": "tag_id",
                "m2m_target_ids_literal": "[10]",
                "additional_sql_predicates": "TRUE",
                "sql_set_clause": "name = 'Updated'",
                "update_params_literal": "",
                "final_invariant_failure_sql": "target.name != 'Updated'",
                "postcheck_params_literal": "",
                "compact_delta_by_stage_user_program_period": "none",
            },
        ).replace("WRITE_APPROVED = False", "WRITE_APPROVED = True")
        env = FakeEnv()
        env._models["crm.lead"] = FakeModel(
            [FakeRecord(1, "Lead 1"), FakeRecord(2, "Lead 2")]
        )
        env.cr._dictfetchone_data = {
            "total": 2,
            "distinct_total": 2,
            "wrong_remaining": 0,
        }
        env.cr.rowcount = 2
        scope = _exec_template(code_sql, env)
        action_obj = scope.get("action")
        assert is_obj_dict(action_obj)
        action = action_obj
        assert action.get("type") == "ir.actions.client"
        params_obj = action.get("params")
        assert is_obj_dict(params_obj)
        params = params_obj
        assert params.get("type") == "success"

    def test_final_audit_expected_distribution_schema_and_mismatch(self) -> None:
        """Verify EXPECTED_DISTRIBUTION validates schema and full bucket mapping."""
        # 1. Invalid schema rejection (e.g. list instead of dict)
        code_invalid_schema = render_template(
            "server_action_final_audit.py.tmpl",
            {
                "model_name": "crm.lead",
                "expected_total": "3",
                "expected_distribution_literal": "['not_a_dict']",
                "independent_domain_literal": "[('active', '=', True)]",
                "wrong_remaining_domain_literal": "[('active', '=', False)]",
                "live_domain_literal": "[('active', '=', True)]",
                "approved_live_total": "3",
                "leftover_tables_literal": "[]",
                "group_fields_literal": "'stage_id'",
            },
        )
        env = FakeEnv()
        with pytest.raises(
            UserError, match="expected_distribution_invalid_schema"
        ) as ctx:
            _ = _exec_template(code_invalid_schema, env)
        assert ctx.value.payload.get("status") == "failed"

        # 2. Bucket count mismatch
        code_audit = render_template(
            "server_action_final_audit.py.tmpl",
            {
                "model_name": "crm.lead",
                "expected_total": "3",
                "expected_distribution_literal": "{'stage_id': {1: 99}}",
                "independent_domain_literal": "[('active', '=', True)]",
                "wrong_remaining_domain_literal": "[('active', '=', False)]",
                "live_domain_literal": "[('active', '=', True)]",
                "approved_live_total": "3",
                "leftover_tables_literal": "[]",
                "group_fields_literal": "'stage_id'",
            },
        )
        env = FakeEnv()
        with pytest.raises(UserError, match="distribution_mapping_mismatch") as ctx:
            _ = _exec_template(code_audit, env)
        payload = ctx.value.payload
        assert payload.get("status") == "failed"
        failures_obj = payload.get("failures", [])
        assert is_obj_list(failures_obj)
        failures = failures_obj

        def _is_mismatch(item: object) -> bool:
            if is_obj_dict(item):
                return item.get("check") == "distribution_mapping_mismatch"
            return False

        assert any(_is_mismatch(f) for f in failures)

    def test_json_encoder_dict_keys_and_control_chars(self) -> None:
        """Round-trip integer keys and control characters in an audit failure."""
        text = 'audit\x00test\x1f\n\r\t\b\f\\"quotes"'
        code = render_template(
            "server_action_final_audit.py.tmpl",
            {
                "model_name": "crm.lead",
                "expected_total": "3",
                "expected_distribution_literal": repr({"stage_id": {1: text}}),
                "independent_domain_literal": "[('active', '=', True)]",
                "wrong_remaining_domain_literal": "[('active', '=', False)]",
                "live_domain_literal": "[('active', '=', True)]",
                "approved_live_total": "3",
                "leftover_tables_literal": "[]",
                "group_fields_literal": "'stage_id'",
            },
        )
        with pytest.raises(UserError, match="distribution_mapping_mismatch") as ctx:
            _ = _exec_template(code, FakeEnv())
        raw_failures = ctx.value.payload["failures"]
        assert is_obj_list(raw_failures)
        assert len(raw_failures) > 0
        failure = raw_failures[0]
        assert is_obj_dict(failure)
        assert failure["actual"] == {"1": 3}


if __name__ == "__main__":
    _ = unittest.main()
