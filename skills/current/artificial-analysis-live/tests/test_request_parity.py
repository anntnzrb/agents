"""Transport acceptance regression tests."""

import io
import json

import pytest

from artificial_analysis.cli import (
    CliUsageError,
    _fetch_namespace,
    _query_namespace,
    build_parser,
    run_rpc,
)
from artificial_analysis.contracts import as_dict, parse_json
from artificial_analysis.requests import QUERY_OPTIONS, fetch_options


@pytest.mark.parametrize("value", ["bogus", "ascending", 3])
def test_rpc_rejects_invalid_query_sort(value: object) -> None:
    """RPC must reject sort choices rejected by argparse."""
    with pytest.raises(CliUsageError):
        _ = _query_namespace({"sort_by": value})


def test_rpc_rejects_fractional_integer_threshold() -> None:
    """RPC must not truncate a value rejected by the CLI integer parser."""
    with pytest.raises(CliUsageError):
        _ = _fetch_namespace({"min_endpoints": 1.5})


@pytest.mark.parametrize("command", ["fetch", "query"])
def test_request_defaults_and_choices_match_argparse(command: str) -> None:
    """Both adapters consume defaults and choice acceptance from one definition."""
    parser = build_parser()
    options = fetch_options() if command == "fetch" else QUERY_OPTIONS
    decode = _fetch_namespace if command == "fetch" else _query_namespace
    cli = vars(parser.parse_args([command]))
    rpc = vars(decode({}))
    for option in options:
        assert cli[option.name] == rpc[option.name] == option.default
        for choice in option.choices or ():
            argv = [command, "--" + option.name.replace("_", "-"), choice]
            assert (
                vars(parser.parse_args(argv))[option.name]
                == vars(decode({option.name: choice}))[option.name]
            )


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("query", {"sort_by": "bogus"}),
        ("query", {"order": "ascending"}),
        ("fetch", {"min_endpoints": 1.5}),
        ("fetch", {"stale_policy": "bogus"}),
    ],
)
def test_rpc_entrypoint_rejects_cli_invalid_values(
    command: str, args: dict[str, object]
) -> None:
    """The public RPC dispatcher reports usage errors before domain I/O."""
    output = io.StringIO()
    request = {"id": "invalid", "type": command, "args": args}
    assert run_rpc(stdin=io.StringIO(json.dumps(request) + "\n"), stdout=output) == 0
    response = as_dict(parse_json(output.getvalue()))
    assert response["success"] is False
    assert response["error"]
