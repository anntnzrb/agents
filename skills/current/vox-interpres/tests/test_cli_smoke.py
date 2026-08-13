from vox_interpres.cli import main


def test_cli_root_help_smoke() -> None:
    assert main(["--help"]) == 0


def test_cli_subcommand_help_smoke() -> None:
    assert main(["analyze", "--help"]) == 0
    assert main(["ask", "--help"]) == 0
    assert main(["chat", "--help"]) == 0
