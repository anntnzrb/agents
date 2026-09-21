"""Tests for Mneme CLI entrypoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from scripts.cli import (
    build_parser,
    check_qmd_available,
    handle_search,
    main,
)


def test_parser_search_subcommand_default() -> None:
    parser = build_parser()
    args = parser.parse_args(["search", "Project Alpha"])
    assert args.command == "search"
    assert args.query == "Project Alpha"
    assert args.collection is None
    assert args.limit == 5
    assert args.exact is False
    assert args.no_rerank is False
    assert args.json is False


def test_parser_search_subcommand_exact() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["search", "Project Alpha", "--exact", "-c", "meetings", "-n", "10", "--json"]
    )
    assert args.command == "search"
    assert args.query == "Project Alpha"
    assert args.exact is True
    assert args.collection == "meetings"
    assert args.limit == 10
    assert args.json is True


def test_parser_search_subcommand_no_rerank() -> None:
    parser = build_parser()
    args = parser.parse_args(["search", "budget timeline review", "--no-rerank"])
    assert args.command == "search"
    assert args.query == "budget timeline review"
    assert args.exact is False
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
        exit_code = main()
        assert exit_code == 127
        captured = capsys.readouterr()
        assert "Error: 'qmd' binary not found on PATH" in captured.err


def test_cli_denoise_missing_input(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sys.argv", ["mneme", "denoise", "non_existent_file.md"]):
        exit_code = main()
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Input file not found" in captured.err


def test_cli_synthesize_missing_input(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sys.argv", ["mneme", "synthesize", "non_existent_file.md"]):
        exit_code = main()
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Input file not found" in captured.err


def test_cli_search_dispatch_modes() -> None:
    parser = build_parser()
    with patch("scripts.cli.run_qmd_command", return_value=0) as mock_run:
        # Default hybrid search -> qmd query
        args = parser.parse_args(
            ["search", "test query", "-c", "notes", "-n", "3", "--json"]
        )
        handle_search(args)
        mock_run.assert_called_with(
            ["query", "test query", "-c", "notes", "-n", "3", "--format", "json"]
        )

        # Exact keyword search -> qmd search
        args_exact = parser.parse_args(
            ["search", "test query", "--exact", "-c", "notes", "-n", "3", "--json"]
        )
        handle_search(args_exact)
        mock_run.assert_called_with(
            ["search", "test query", "-c", "notes", "-n", "3", "--format", "json"]
        )

        # Hybrid without reranker -> qmd query --no-rerank
        args_no_rerank = parser.parse_args(["search", "test query", "--no-rerank"])
        handle_search(args_no_rerank)
        mock_run.assert_called_with(["query", "test query", "-n", "5", "--no-rerank"])
