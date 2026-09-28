# Copyright (c) 2026
from tests._path import SKILL_DIR

from livebench.commands import load_context
from livebench.contracts import as_dict, as_list

FIXTURES = SKILL_DIR / "tests" / "fixtures"


def test_arbitrary_category_and_task_names_flow_without_allow_list() -> None:
    context = load_context(
        release_selector="latest",
        snapshot=FIXTURES / "catalog/new-category.json",
        cache_dir=None,
        allow_stale=False,
        timeout=1,
    )
    categories = as_dict(context.catalog["categories"])
    assert "arbitrary-unicode-category-v2" in categories
    columns = as_dict(context.catalog["columns"])
    score_table = as_list(columns["score_table"])
    assert "task_new_two" in score_table


def test_unknown_model_row_is_retained() -> None:
    context = load_context(
        release_selector="latest",
        snapshot=FIXTURES / "catalog/new-benchmark.json",
        cache_dir=None,
        allow_stale=False,
        timeout=1,
    )
    row = context.rows[0]
    assert row["model"] == "new-model"
    model_id = row["model_id"]
    assert isinstance(model_id, str)
    assert model_id.startswith("livebench:model:")
