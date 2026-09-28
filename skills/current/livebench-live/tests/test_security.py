# Copyright (c) 2026
from livebench.contracts import as_dict
from livebench.diagnostics import redact


def test_auth_material_is_redacted() -> None:
    payload = as_dict(
        redact(
            {
                "Authorization": "Bearer secret-value",
                "Cookie": "session=secret",
                "safe": "model-a",
            }
        )
    )
    assert "secret-value" not in str(payload)
    assert "session=secret" not in str(payload)
    assert payload["safe"] == "model-a"


def test_redaction_does_not_drop_source_urls_or_scores() -> None:
    payload = as_dict(
        redact({"source_url": "https://livebench.ai/table.csv", "score": 72.4})
    )
    source_url = payload["source_url"]
    assert isinstance(source_url, str)
    assert source_url.startswith("https://")
    assert payload["score"] == 72.4
