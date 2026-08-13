# Copyright (c) 2026
from __future__ import annotations

from _path import SKILL_DIR
from livebench.commands import load_context

FIXTURES = SKILL_DIR / "tests" / "fixtures"


def test_arbitrary_category_and_task_names_flow_without_allow_list() -> None:
    context = load_context(
        release_selector="latest",
        snapshot=FIXTURES / "catalog/new-category.json",
        cache_dir=None,
        allow_stale=False,
        timeout=1,
    )
    assert "arbitrary-unicode-category-v2" in context.catalog["categories"]
    assert "task_new_two" in context.catalog["columns"]["score_table"]


def test_unknown_model_row_is_retained() -> None:
    context = load_context(
        release_selector="latest",
        snapshot=FIXTURES / "catalog/new-benchmark.json",
        cache_dir=None,
        allow_stale=False,
        timeout=1,
    )
    assert context.rows[0]["model"] == "new-model"
    assert context.rows[0]["model_id"].startswith("livebench:model:")
