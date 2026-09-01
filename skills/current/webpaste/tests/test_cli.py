# Copyright (c) 2026
"""Unit tests for webpaste CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from skills.current.webpaste.scripts.cli import (
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    Err,
    Ok,
    detect_language,
    get_content_type,
    main,
    normalize_language,
    read_input,
)

if TYPE_CHECKING:
    import pytest


def test_result_combinators() -> None:
    """Test map and and_then chaining on Result."""
    ok_res = Ok(10)
    mapped = ok_res.map(lambda x: x * 2)
    match mapped:
        case Ok(v):
            expected_val = 20
            if v != expected_val:
                msg = f"expected {expected_val}, got {v}"
                raise AssertionError(msg)
        case Err(_):
            msg = "unexpected Err"
            raise AssertionError(msg)

    chained = ok_res.and_then(lambda x: Ok(f"num: {x}"))
    match chained:
        case Ok(v):
            if v != "num: 10":
                msg = f"expected 'num: 10', got {v}"
                raise AssertionError(msg)
        case Err(_):
            msg = "unexpected Err"
            raise AssertionError(msg)

    err_res: Err[str] = Err("initial error")
    err_mapped = err_res.map(lambda x: f"transformed {x}")
    match err_mapped:
        case Err(e):
            if e != "initial error":
                msg = f"expected 'initial error', got {e}"
                raise AssertionError(msg)
        case Ok(_):
            msg = "unexpected Ok on Err map"
            raise AssertionError(msg)


def test_normalize_language() -> None:
    """Test alias resolution to canonical Monaco language IDs."""
    if normalize_language("py") != "python":
        msg = "py must resolve to python"
        raise AssertionError(msg)
    if normalize_language("TS") != "typescript":
        msg = "TS must resolve to typescript"
        raise AssertionError(msg)
    if normalize_language("C++") != "cpp":
        msg = "C++ must resolve to cpp"
        raise AssertionError(msg)
    if normalize_language("unknown") != "unknown":
        msg = "unknown must pass through"
        raise AssertionError(msg)


def test_detect_language_explicit() -> None:
    """Test language detection when explicit parameter is given."""
    if detect_language(Path("foo.py"), b"", "rust") != "rust":
        msg = "explicit language must take precedence"
        raise AssertionError(msg)
    if detect_language(None, b"", "JSON") != "json":
        msg = "explicit language must be lowercased"
        raise AssertionError(msg)
    if detect_language(None, b"", "py") != "python":
        msg = "explicit alias must normalize"
        raise AssertionError(msg)


def test_detect_language_by_extension() -> None:
    """Test language detection based on file extension and special filenames."""
    if detect_language(Path("foo.py"), b"", None) != "python":
        msg = "expected python"
        raise AssertionError(msg)
    if detect_language(Path("foo.ts"), b"", None) != "typescript":
        msg = "expected typescript"
        raise AssertionError(msg)
    if detect_language(Path("Dockerfile"), b"", None) != "dockerfile":
        msg = "expected dockerfile"
        raise AssertionError(msg)
    if detect_language(Path(".env"), b"", None) != "shell":
        msg = "expected shell"
        raise AssertionError(msg)
    if detect_language(Path("patch.diff"), b"", None) != "diff":
        msg = "expected diff"
        raise AssertionError(msg)
    if detect_language(Path("unknown.xyz"), b"", None) != "plain":
        msg = "expected fallback to plain"
        raise AssertionError(msg)
    if detect_language(None, b"", None) != "plain":
        msg = "expected plain for stdin with no extension or shebang"
        raise AssertionError(msg)


def test_detect_language_shebang() -> None:
    """Test language detection from shebang line on stdin content."""
    py_shebang = b"#!/usr/bin/env python3\nprint('hi')\n"
    if detect_language(None, py_shebang, None) != "python":
        msg = "expected python from shebang"
        raise AssertionError(msg)

    sh_shebang = b"#!/bin/bash\necho hi\n"
    if detect_language(None, sh_shebang, None) != "shell":
        msg = "expected shell from shebang"
        raise AssertionError(msg)

    node_shebang = b"#!/usr/bin/env node\nconsole.log(1);\n"
    if detect_language(None, node_shebang, None) != "javascript":
        msg = "expected javascript from shebang"
        raise AssertionError(msg)


def test_get_content_type() -> None:
    """Test mapping from language string to MIME Content-Type header."""
    if get_content_type("json") != "application/json":
        msg = "json must map to application/json"
        raise AssertionError(msg)
    if get_content_type("python") != "text/python":
        msg = "python must map to text/python"
        raise AssertionError(msg)
    if get_content_type("py") != "text/python":
        msg = "py alias must map to text/python"
        raise AssertionError(msg)
    if get_content_type("plain") != "text/plain":
        msg = "plain must map to text/plain"
        raise AssertionError(msg)


def test_read_input_result(tmp_path: Path) -> None:
    """Test read_input with file and stdin inputs."""
    sample = tmp_path / "hello.rs"
    sample.write_text("fn main() {}")

    res_ok = read_input(str(sample), is_atty=True)
    match res_ok:
        case Ok((content, path)):
            if content != b"fn main() {}" or path != sample:
                msg = "unexpected read_input Ok payload"
                raise AssertionError(msg)
        case Err(_):
            msg = "expected Ok result"
            raise AssertionError(msg)

    res_err = read_input("nonexistent.txt", is_atty=True)
    match res_err:
        case Err(err):
            if err.exit_code != EXIT_USAGE_ERROR:
                msg = f"expected exit code 2, got {err.exit_code}"
                raise AssertionError(msg)
        case Ok(_):
            msg = "expected Err result for missing file"
            raise AssertionError(msg)


def test_upload_success_mock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test successful file upload with mocked server response."""
    sample_file = tmp_path / "test.py"
    sample_file.write_text("print('hello world')\n")

    def mock_post(_self: httpx.Client, url: str, **_kwargs: object) -> httpx.Response:
        if "/post" not in url:
            msg = "unexpected url"
            raise AssertionError(msg)
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"key": "mock123"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    ret = main([str(sample_file)])
    if ret != EXIT_SUCCESS:
        msg = f"expected exit code 0, got {ret}"
        raise AssertionError(msg)
    captured = capsys.readouterr()
    if captured.out.strip() != "https://pastes.dev/mock123":
        msg = f"unexpected output: {captured.out}"
        raise AssertionError(msg)


def test_upload_stdin_mock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test uploading content from piped stdin."""
    stdin_data = io.BytesIO(b"fn piped() {}\n")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(stdin_data))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    def mock_post(_self: httpx.Client, url: str, **_kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"key": "stdin789"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    ret = main(["-l", "rust", "-"])
    if ret != EXIT_SUCCESS:
        msg = f"expected exit code 0, got {ret}"
        raise AssertionError(msg)
    captured = capsys.readouterr()
    if captured.out.strip() != "https://pastes.dev/stdin789":
        msg = f"unexpected output: {captured.out}"
        raise AssertionError(msg)


def test_upload_raw_url_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test --raw-url outputs direct bytebin raw link."""
    sample_file = tmp_path / "test.txt"
    sample_file.write_text("raw text")

    def mock_post(_self: httpx.Client, url: str, **_kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"key": "raw999"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    ret = main(["--raw-url", str(sample_file)])
    if ret != EXIT_SUCCESS:
        msg = f"expected exit code 0, got {ret}"
        raise AssertionError(msg)
    captured = capsys.readouterr()
    if captured.out.strip() != "https://api.pastes.dev/raw999":
        msg = f"unexpected output: {captured.out}"
        raise AssertionError(msg)


def test_upload_json_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test JSON formatted output on successful upload."""
    sample_file = tmp_path / "test.json"
    sample_file.write_text('{"a": 1}')

    def mock_post(_self: httpx.Client, url: str, **_kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"key": "json456"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    ret = main(["--json", str(sample_file)])
    if ret != EXIT_SUCCESS:
        msg = f"expected exit code 0, got {ret}"
        raise AssertionError(msg)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    if data["key"] != "json456" or data["url"] != "https://pastes.dev/json456":
        msg = f"unexpected json data: {data}"
        raise AssertionError(msg)
    if data["raw_url"] != "https://api.pastes.dev/json456":
        msg = f"unexpected raw_url: {data['raw_url']}"
        raise AssertionError(msg)


def test_get_paste_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test fetching an existing paste by key."""

    def mock_get(_self: httpx.Client, url: str, **_kwargs: object) -> httpx.Response:
        if "/testkey" not in url:
            msg = "unexpected url"
            raise AssertionError(msg)
        request = httpx.Request("GET", url)
        return httpx.Response(200, text="fetched content", request=request)

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    ret = main(["--get", "https://pastes.dev/testkey"])
    if ret != EXIT_SUCCESS:
        msg = f"expected exit code 0, got {ret}"
        raise AssertionError(msg)
    captured = capsys.readouterr()
    if captured.out.strip() != "fetched content":
        msg = f"unexpected output: {captured.out}"
        raise AssertionError(msg)


def test_file_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """Test error handling when passed file does not exist."""
    ret = main(["non_existent_file.txt"])
    if ret != EXIT_USAGE_ERROR:
        msg = f"expected exit code 2, got {ret}"
        raise AssertionError(msg)
    captured = capsys.readouterr()
    if "file not found" not in captured.err:
        msg = f"expected 'file not found' in stderr, got {captured.err}"
        raise AssertionError(msg)


def test_no_input_guided_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test guidance error when invoked interactively with no file or stdin."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    ret = main([])
    if ret != EXIT_USAGE_ERROR:
        msg = f"expected exit code 2, got {ret}"
        raise AssertionError(msg)
    captured = capsys.readouterr()
    if "--help" not in captured.err or "no input provided" not in captured.err:
        msg = f"expected --help guidance in stderr, got {captured.err}"
        raise AssertionError(msg)
