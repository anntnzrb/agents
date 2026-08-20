from __future__ import annotations

import json
from pathlib import Path

import pytest
import search_expert_chunks
import select_shortcut_icon_color


def test_search_corpus_filters_and_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    chunks = tmp_path / "expert-pack" / "chunks"
    chunks.mkdir(parents=True)
    records = [
        {
            "id": "support",
            "source_group": "support",
            "path": "ask.md",
            "text": "Ask for input action input",
            "char_len": 30,
        },
        {
            "id": "other",
            "source_group": "community",
            "path": "other.md",
            "text": "Ask for input",
            "char_len": 12,
        },
    ]
    (chunks / "shortcuts_expert_chunks.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "search_expert_chunks.py",
            "--query",
            "ask input",
            "--group",
            "support",
            "--corpus-root",
            str(tmp_path),
            "--json",
        ],
    )
    assert search_expert_chunks.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in payload["results"]] == ["support"]


def test_icon_resolver_honors_explicit_overrides() -> None:
    payload = select_shortcut_icon_color.resolve_icon_color(
        "Expense tracker",
        "calculator",
        "gold",
    )
    assert payload["icon"]["glyph_number"] == 59680
    assert payload["color"]["name"] == "Gold"
    assert payload["wf_workflow_icon"] == {
        "WFWorkflowIconGlyphNumber": 59680,
        "WFWorkflowIconStartColor": 4274264319,
    }


def test_search_missing_corpus_and_icon_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "search_expert_chunks.py",
            "--query",
            "missing",
            "--corpus-root",
            str(tmp_path),
        ],
    )
    assert search_expert_chunks.main() == 2
    assert "Could not locate" in capsys.readouterr().err
    payload = select_shortcut_icon_color.resolve_icon_color("", None, "not-a-colour")
    assert payload["icon"]["selection_mode"] == "fallback"
    assert payload["color"]["selection_mode"] == "fallback"
