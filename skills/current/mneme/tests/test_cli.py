"""Tests for Mneme CLI entrypoint."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.cli import (
    MnemeArgs,
    build_parser,
    check_qmd_available,
    clean_text_lossless,
    handle_denoise,
    handle_get,
    handle_search,
    main,
)

CLI = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_parser_search_subcommand_default() -> None:
    parser = build_parser()
    args = parser.parse_args(["search", "budget planning"], namespace=MnemeArgs())
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
        ["search", "Project Alpha", "-c", "meetings", "-n", "10", "--exact", "--json"],
        namespace=MnemeArgs(),
    )
    assert args.command == "search"
    assert args.query == "Project Alpha"
    assert args.collection == "meetings"
    assert args.limit == 10
    assert args.exact is True
    assert args.json is True


def test_parser_search_subcommand_no_rerank() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["search", "timeline", "--no-rerank"], namespace=MnemeArgs()
    )
    assert args.command == "search"
    assert args.query == "timeline"
    assert args.no_rerank is True


def test_parser_get_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["get", "#abc123:10:20"], namespace=MnemeArgs())
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


def test_cli_verify_missing_input(tmp_path: Path) -> None:
    raw = tmp_path / "raw.txt"
    _ = raw.write_text("A: 1\n", encoding="utf-8")
    result = run_cli("verify", str(raw), str(tmp_path / "missing.md"))
    assert result.returncode == 2
    assert "Input file not found" in result.stderr


def test_cli_search_dispatch_modes_with_positional_separator() -> None:
    parser = build_parser()
    with patch("scripts.cli.run_qmd_command", return_value=0) as mock_run:
        args = parser.parse_args(["search", "test query"], namespace=MnemeArgs())
        ret = handle_search(args)
        assert ret == 0
        mock_run.assert_called_with(["query", "-n", "5", "--", "test query"])

    with patch("scripts.cli.run_qmd_command", return_value=0) as mock_run:
        args = parser.parse_args(
            ["search", "-c", "notes", "--exact", "--json", "--", "--help"],
            namespace=MnemeArgs(),
        )
        ret = handle_search(args)
        assert ret == 0
        mock_run.assert_called_with(
            ["search", "-c", "notes", "-n", "5", "--format", "json", "--", "--help"]
        )

    with patch("scripts.cli.run_qmd_command", return_value=0) as mock_run:
        args = parser.parse_args(
            ["search", "test query", "--no-rerank"], namespace=MnemeArgs()
        )
        ret = handle_search(args)
        assert ret == 0
        mock_run.assert_called_with(
            ["query", "-n", "5", "--no-rerank", "--", "test query"]
        )


def test_cli_get_dispatch_with_positional_separator() -> None:
    parser = build_parser()
    with patch("scripts.cli.run_qmd_command", return_value=0) as mock_run:
        args = parser.parse_args(["get", "#abc123:10:20"], namespace=MnemeArgs())
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
    _ = raw_file.write_text(
        "Speaker 1: um, we have agreed to close the deal at 50,000 USD.\n",
        encoding="utf-8",
    )
    out_file = tmp_path / "clean.md"

    parser = build_parser()
    args = parser.parse_args(
        ["denoise", str(raw_file), "-o", str(out_file)], namespace=MnemeArgs()
    )
    ret = handle_denoise(args)
    assert ret == 0
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "50,000 USD" in content
    assert "**Speaker 1:**" in content


def test_clean_text_lossless_false_starts_and_spanish_fillers() -> None:
    raw = (
        "Vanessa: Así que ya, ya le voy a escri- escribir.\n"
        "Juan: Ah, ya. Eh, lo tengo 100% claro, ma-ma-manual.\n"
        "Vanessa: Mm-hmm."
    )
    cleaned = clean_text_lossless(raw)
    assert "le voy a escribir" in cleaned
    assert "escri-" not in cleaned
    assert "**Juan:**\nya." in cleaned
    assert "lo tengo 100% claro, manual." in cleaned
    assert "Eh" not in cleaned
    assert "Mm-hmm." in cleaned
    assert "\n," not in cleaned


def test_clean_text_lossless_keeps_repeated_numbers() -> None:
    cleaned = clean_text_lossless("Juan: Sería 10, 10 ventas y 5 5 cupos.")
    assert "10, 10 ventas" in cleaned
    assert "5 5 cupos" in cleaned


def test_cli_verify_passes_on_preserved_numbers(tmp_path: Path) -> None:
    raw = tmp_path / "raw.txt"
    clean = tmp_path / "clean.md"
    _ = raw.write_text(
        "Speaker 4: Eh, son 130,000 leads y 18 etiquetas.\n", encoding="utf-8"
    )
    _ = clean.write_text(
        "**Lenin Freire:**\nSon 130,000 leads y 18 etiquetas.\n", encoding="utf-8"
    )
    result = run_cli("verify", str(raw), str(clean))
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_cli_verify_reports_dropped_numbers(tmp_path: Path) -> None:
    raw = tmp_path / "raw.txt"
    clean = tmp_path / "clean.md"
    _ = raw.write_text(
        "Juan: Son 130,000 leads.\nJuan: Meta 2,000 dólares.\n", encoding="utf-8"
    )
    _ = clean.write_text(
        "**Juan:**\nSon muchos leads. Meta 2,000 dólares.\n", encoding="utf-8"
    )
    result = run_cli("verify", str(raw), str(clean))
    assert result.returncode == 1
    assert "130,000: 1" in result.stdout
    assert "2,000" not in result.stdout
