"""Offline wire-level coverage for uploads, verification, and binary fetches."""

import gzip
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, TypeIs

import httpx2
import pytest

from cli import Err, Ok, execute_fetch, main, sniff_content

if TYPE_CHECKING:
    from collections.abc import Callable


type Serve = Callable[[Callable[[httpx2.Request], httpx2.Response]], None]


def is_dict(value: object) -> TypeIs[dict[str, object]]:
    """Narrow a JSON object for test assertions."""
    return isinstance(value, dict)


def load_result(text: str) -> dict[str, object]:
    """Narrow JSON output once at the test boundary."""
    decode: Callable[..., object] = json.loads
    result = decode(text)
    assert is_dict(result)
    return result


@pytest.fixture
def serve(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Callable[[httpx2.Request], httpx2.Response]], None]:
    """Replace only the network transport, keeping multipart encoding real."""
    client_class = httpx2.Client

    def install(handler: Callable[[httpx2.Request], httpx2.Response]) -> None:
        def client(**_kwargs: object) -> httpx2.Client:
            return client_class(
                transport=httpx2.MockTransport(handler),
                timeout=15,
                follow_redirects=True,
            )

        monkeypatch.setattr(httpx2, "Client", client)

    return install


@pytest.mark.parametrize("provider", ["catbox", "litterbox"])
def test_binary_multipart_and_verification(
    provider: str, serve: Serve, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Upload a screenshot with a Unicode filename and verify exact download bytes."""
    content = b"\x89PNG\r\n\x1a\n\x00\xfftest"
    path = tmp_path / "Screenshot 10.00\u202fPM.png"
    _ = path.write_bytes(content)
    host = "files.catbox.moe" if provider == "catbox" else "litter.catbox.moe"
    url = f"https://{host}/shot.png"
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == "POST":
            body = request.read()
            assert request.headers["content-type"].startswith("multipart/form-data;")
            assert b'name="reqtype"\r\n\r\nfileupload' in body
            assert b'name="fileToUpload"; filename="shot.png"' in body
            assert b"Content-Type: image/png" in body
            assert content in body
            assert b"userhash" not in body
            assert "content-encoding" not in request.headers
            if provider == "litterbox":
                assert b'name="time"\r\n\r\n72h' in body
                assert (
                    str(request.url)
                    == "https://litterbox.catbox.moe/resources/internals/api.php"
                )
            else:
                assert str(request.url) == "https://catbox.moe/user/api.php"
            return httpx2.Response(200, text=url)
        assert str(request.url) == url
        return httpx2.Response(
            200, content=content, headers={"content-type": "image/png"}
        )

    serve(handler)
    args = [str(path), "--filename", "shot.png", "--json"]
    if provider == "litterbox":
        args += ["--provider", provider]
    assert main(args) == 0
    data = load_result(capsys.readouterr().out)
    assert data["provider"] == provider
    assert data["url"] == data["raw_url"] == url
    assert data["sha256"] == hashlib.sha256(content).hexdigest()
    assert data["verified"] is True
    assert data["content_type"] == "image/png"
    assert data["charset"] is None
    assert data["bytes"] == len(content)
    assert data["retention"] == ("72h" if provider == "litterbox" else "2y-inactive")
    assert len(requests) == 2


@pytest.mark.parametrize(
    ("body", "status"), [(b"", 200), (b"wrong", 200), (b"missing", 404)]
)
def test_blank_upload_fails(
    body: bytes,
    status: int,
    serve: Serve,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reject empty, mismatched, and missing content despite successful upload."""
    path = tmp_path / "report.md"
    _ = path.write_bytes(b"report")

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            assert gzip.decompress(request.read()) == b"report"
            return httpx2.Response(200, json={"key": "report"})
        return httpx2.Response(status, content=body)

    serve(handler)
    assert main([str(path)]) == 1
    output = capsys.readouterr()
    assert "blank upload" in output.err
    assert not output.out


def test_ascii_check_before_pastes_upload(
    serve: Serve, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """List every unsafe codepoint without publishing or rewriting the report."""
    path = tmp_path / "report.md"
    text = "café · \u00d7 \u2013 →"
    _ = path.write_text(text, encoding="utf-8")

    def handler(request: httpx2.Request) -> httpx2.Response:
        pytest.fail(f"unexpected network call: {request.url}")

    serve(handler)
    assert main(["--provider", "pastes", str(path), "--ascii-check"]) == 2
    output = capsys.readouterr()
    for codepoint in ("U+00E9", "U+00B7", "U+00D7", "U+2013", "U+2192"):
        assert codepoint in output.err
    assert "Â·" in output.err
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize(("charset", "exit_code"), [("; charset=UTF-8", 0), ("", 1)])
def test_text_override_charset(
    charset: str,
    exit_code: int,
    serve: Serve,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Respect the served charset when checking text on Catbox."""
    path = tmp_path / "report.md"
    content = "café".encode()
    _ = path.write_bytes(content)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(200, text="https://files.catbox.moe/report.md")
        return httpx2.Response(
            200, content=content, headers={"content-type": f"text/markdown{charset}"}
        )

    serve(handler)
    assert (
        main([str(path), "--provider", "catbox", "--ascii-check", "--json"])
        == exit_code
    )
    output = capsys.readouterr()
    if exit_code == 0:
        assert load_result(output.out)["charset"] == "utf-8"
    else:
        assert "U+00E9" in output.err


def test_no_verify_and_custom_base(
    serve: Serve, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Preserve custom pastes APIs and explicitly report unverified metadata."""
    path = tmp_path / "report.txt"
    _ = path.write_bytes(b"text")

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://localhost:8080/data/post"
        assert request.read() == b"text"
        return httpx2.Response(200, json={"key": "key"})

    serve(handler)
    assert (
        main(
            [
                str(path),
                "--base-url",
                "http://localhost:8080/data/",
                "--no-gzip",
                "--no-verify",
                "--json",
            ]
        )
        == 0
    )
    data = load_result(capsys.readouterr().out)
    assert data["verified"] is False
    assert data["content_type"] is None
    assert data["charset"] is None
    assert data["retention"] == "90d"
    assert data["raw_url"] == "http://localhost:8080/data/key"


@pytest.mark.parametrize(
    ("value", "url"),
    [
        ("key", "https://api.pastes.dev/key"),
        ("https://pastes.dev/key", "https://api.pastes.dev/key"),
        ("https://files.catbox.moe/key.png", "https://files.catbox.moe/key.png"),
        ("https://litter.catbox.moe/key.png", "https://litter.catbox.moe/key.png"),
    ],
)
def test_fetch_exact_bytes_and_hash(value: str, url: str, serve: Serve) -> None:
    """Fetch binary or text bytes without newline insertion or decoding."""
    content = b"\x00\xffdata"

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == url
        return httpx2.Response(200, content=content)

    serve(handler)
    result = execute_fetch(
        "https://api.pastes.dev/",
        value,
        "test",
        15,
        hashlib.sha256(content).hexdigest(),
    )
    assert isinstance(result, Ok)
    assert result.value == content
    bad = execute_fetch("https://api.pastes.dev/", value, "test", 15, "0" * 64)
    assert isinstance(bad, Err)
    assert bad.error.exit_code == 1


def test_binary_fetch_stdout(
    serve: Serve, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    """Exercise the CLI binary stdout path, not just the fetch helper."""

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"\x00\xff")

    serve(handler)
    assert main(["--get", "https://files.catbox.moe/file.png"]) == 0
    assert capsysbinary.readouterr().out == b"\x00\xff"


@pytest.mark.parametrize(
    ("status", "body"), [(500, b"error"), (200, b"not json"), (200, b"{}")]
)
def test_upload_response_errors(
    status: int,
    body: bytes,
    serve: Serve,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Return runtime errors for HTTP failure or malformed provider responses."""
    path = tmp_path / "report.txt"
    _ = path.write_bytes(b"text")

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, content=body)

    serve(handler)
    assert main([str(path)]) == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize(
    ("content", "path", "is_text", "mime"),
    [
        (b"hello", "report.xyz", True, "text/plain"),
        (b'{"a":1}', "trace.jsonl", True, "text/plain"),
        (b"\x00capture", "capture.tsp", False, "application/octet-stream"),
        (b"\x89PNG\r\n\x1a\n", "wrong.txt", False, "image/png"),
        (b"ascii", "movie.mov", False, "video/quicktime"),
    ],
)
def test_content_classification(
    content: bytes, path: str, *, is_text: bool, mime: str
) -> None:
    """Choose providers by both contents and MIME hints."""
    assert sniff_content(content, Path(path)) == (is_text, mime)


def test_timeout_is_runtime_error(
    serve: Serve, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report a hung upload without retries or a success URL."""
    path = tmp_path / "report.md"
    _ = path.write_bytes(b"text")

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.extensions["timeout"] == {
            "connect": 15,
            "read": 15,
            "write": 15,
            "pool": 15,
        }
        raise httpx2.ReadTimeout("hung upload", request=request)

    serve(handler)
    assert main([str(path)]) == 1
    assert "Network error" in capsys.readouterr().err


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/file",
        "file:///etc/passwd",
        "https://files.catbox.moe.evil/file",
    ],
)
def test_reject_unsupported_fetch_urls(url: str, serve: Serve) -> None:
    """Reject unsupported URLs before issuing a request."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        pytest.fail(f"unexpected request: {request.url}")

    serve(handler)
    result = execute_fetch("https://api.pastes.dev/", url, "test", 15)
    assert isinstance(result, Err)
    assert result.error.exit_code == 2


def test_default_unicode_filename(
    serve: Serve, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Encode a basename containing spaces and macOS narrow no-break space."""
    path = tmp_path / "Screenshot 10\u202fPM.png"
    content = b"\x89PNG\r\n\x1a\n\x00"
    _ = path.write_bytes(content)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            assert f'filename="{path.name}"'.encode() in request.read()
            return httpx2.Response(200, text="https://files.catbox.moe/shot.png")
        return httpx2.Response(200, content=content)

    serve(handler)
    assert main([str(path)]) == 0
    assert capsys.readouterr().out.strip() == "https://files.catbox.moe/shot.png"
