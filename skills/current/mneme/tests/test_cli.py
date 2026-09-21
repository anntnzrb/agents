"""Tests for Mneme CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.cli import (
    build_parser,
    check_qmd_available,
    clean_text_lossless,
    handle_denoise,
    handle_get,
    handle_search,
    handle_synthesize,
    main,
)


def test_parser_search_subcommand_default() -> None:
    parser = build_parser()
    args = parser.parse_args(["search", "budget planning"])
    assert args.command == "search"
    assert args.query == "budget planning"
    assert args.collection is None
    assert args.limit == 5
    assert args.exact is False
    assert args.no_rerank is False
    assert args.json is False


def test_parser_search_subcommand_exact() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["search", "Project Alpha", "-c", "meetings", "-n", "10", "--exact", "--json"]
    )
    assert args.command == "search"
    assert args.query == "Project Alpha"
    assert args.collection == "meetings"
    assert args.limit == 10
    assert args.exact is True
    assert args.json is True


def test_parser_search_subcommand_no_rerank() -> None:
    parser = build_parser()
    args = parser.parse_args(["search", "timeline", "--no-rerank"])
    assert args.command == "search"
    assert args.query == "timeline"
    assert args.no_rerank is True


def test_parser_get_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["get", "#abc123:10:20"])
    assert args.command == "get"
    assert args.target == "#abc123:10:20"


def test_check_qmd_available() -> None:
    with patch("shutil.which", return_value="/usr/local/bin/qmd"):
        assert check_qmd_available() is True
    with patch("shutil.which", return_value=None):
        assert check_qmd_available() is False


def test_cli_search_missing_qmd(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch("shutil.which", return_value=None),
        patch("sys.argv", ["mneme", "search", "test"]),
    ):
        ret = main()
    assert ret == 127
    captured = capsys.readouterr()
    assert "Error: 'qmd' binary not found on PATH" in captured.err


def test_cli_denoise_missing_input(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sys.argv", ["mneme", "denoise", "non_existent_file.md"]):
        ret = main()
    assert ret == 2
    captured = capsys.readouterr()
    assert "Input file not found" in captured.err


def test_cli_synthesize_missing_input(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sys.argv", ["mneme", "synthesize", "non_existent_file.md"]):
        ret = main()
    assert ret == 2
    captured = capsys.readouterr()
    assert "Input file not found" in captured.err


def test_cli_search_dispatch_modes_with_positional_separator() -> None:
    parser = build_parser()
    with patch("scripts.cli.run_qmd_command", return_value=0) as mock_run:
        args = parser.parse_args(["search", "test query"])
        ret = handle_search(args)
        assert ret == 0
        mock_run.assert_called_with(["query", "-n", "5", "--", "test query"])

    with patch("scripts.cli.run_qmd_command", return_value=0) as mock_run:
        args = parser.parse_args(
            ["search", "-c", "notes", "--exact", "--json", "--", "--help"]
        )
        ret = handle_search(args)
        assert ret == 0
        mock_run.assert_called_with(
            ["search", "-c", "notes", "-n", "5", "--format", "json", "--", "--help"]
        )

    with patch("scripts.cli.run_qmd_command", return_value=0) as mock_run:
        args = parser.parse_args(["search", "test query", "--no-rerank"])
        ret = handle_search(args)
        assert ret == 0
        mock_run.assert_called_with(
            ["query", "-n", "5", "--no-rerank", "--", "test query"]
        )


def test_cli_get_dispatch_with_positional_separator() -> None:
    parser = build_parser()
    with patch("scripts.cli.run_qmd_command", return_value=0) as mock_run:
        args = parser.parse_args(["get", "#abc123:10:20"])
        ret = handle_get(args)
        assert ret == 0
        mock_run.assert_called_with(["get", "--", "#abc123:10:20"])


def test_clean_text_lossless_stutter_and_fillers() -> None:
    raw = (
        "Alice: um, we we need to to deploy the $2,000 threshold by 2026-09-30.\n"
        "Bob: yeah, o sea, tipo, we agreed on the B2B pipeline objections."
    )
    cleaned = clean_text_lossless(raw)
    assert "$2,000 threshold" in cleaned
    assert "2026-09-30" in cleaned
    assert "B2B pipeline objections" in cleaned
    assert "we we need to to" not in cleaned
    assert "we need to deploy" in cleaned


def test_clean_text_lossless_turn_order_and_speaker_annotations() -> None:
    raw = (
        "Mónica Díaz: Acá B2C no interactúa en estos negocios.\n"
        "Juan Antonio Gonzalez Orbe (You):  Sí, comentarios.\n"
        "Mónica Díaz:  Al lado de comentarios.\n"
        "Vanessa Lizbeth Ormeño Candelario: En B2C tenemos problemas."
    )
    cleaned = clean_text_lossless(raw)
    assert "**Mónica Díaz:**\nAcá B2C no interactúa en estos negocios." in cleaned
    assert "**Juan Antonio Gonzalez Orbe:**\nSí, comentarios." in cleaned
    assert "**Mónica Díaz:**\nAl lado de comentarios." in cleaned
    assert (
        "**Vanessa Lizbeth Ormeño Candelario:**\nEn B2C tenemos problemas." in cleaned
    )
    # Verify turn sequence
    pos_monica1 = cleaned.find("**Mónica Díaz:**")
    pos_juan = cleaned.find("**Juan Antonio Gonzalez Orbe:**")
    pos_monica2 = cleaned.find("**Mónica Díaz:**\nAl lado de comentarios.")
    pos_vanessa = cleaned.find("**Vanessa Lizbeth Ormeño Candelario:**")
    assert 0 <= pos_monica1 < pos_juan < pos_monica2 < pos_vanessa


def test_handle_denoise_file_output(tmp_path: Path) -> None:
    raw_file = tmp_path / "raw.md"
    raw_file.write_text(
        "Speaker 1: um, we have agreed to close the deal at 50,000 USD.\n",
        encoding="utf-8",
    )
    out_file = tmp_path / "clean.md"

    parser = build_parser()
    args = parser.parse_args(["denoise", str(raw_file), "-o", str(out_file)])
    ret = handle_denoise(args)
    assert ret == 0
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "50,000 USD" in content
    assert "**Speaker 1:**" in content


def test_handle_synthesize_file_output(tmp_path: Path) -> None:
    clean_file = tmp_path / "clean.md"
    clean_file.write_text(
        "**Alice:** We agreed to enforce the new validation rule.\n"
        "**Bob:** I will coordinate the deployment with GTCI tomorrow at 2 PM.\n",
        encoding="utf-8",
    )
    summary_file = tmp_path / "summary.md"
    tasks_file = tmp_path / "tasks.json"

    parser = build_parser()
    args = parser.parse_args(
        [
            "synthesize",
            str(clean_file),
            "--summary",
            str(summary_file),
            "--tasks",
            str(tasks_file),
        ]
    )
    ret = handle_synthesize(args)
    assert ret == 0
    assert summary_file.exists()
    assert tasks_file.exists()

    summary_text = summary_file.read_text(encoding="utf-8")
    assert "Executive Summary" in summary_text
    assert "Key Decisions Agreed" in summary_text

    tasks_data = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert "tasks" in tasks_data
    assert len(tasks_data["tasks"]) > 0
    task0 = tasks_data["tasks"][0]
    assert "id" in task0
    assert "title" in task0
    assert "completion_criteria" in task0
