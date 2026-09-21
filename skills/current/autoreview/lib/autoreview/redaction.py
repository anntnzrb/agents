"""Path filtering, credential redaction, and sensitive pattern masking."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from autoreview.models import SENSITIVE_NAME_PATTERNS, SENSITIVE_PATH_PARTS


def is_sensitive_path(rel_path: str) -> bool:
    """Determine if a file path points to sensitive credentials or configurations."""
    normalized = rel_path.replace("\\", "/")
    posix_path = PurePosixPath(normalized)

    # Check path segments against sensitive directories
    for part in posix_path.parts:
        if part in SENSITIVE_PATH_PARTS:
            return True

    # Check file patterns against regex
    return any(pattern.search(normalized) for pattern in SENSITIVE_NAME_PATTERNS)


def redact_sensitive_text(text: str) -> str:
    """Mask obvious API keys, private key blocks, and bearer tokens in text payloads."""
    # Redact PEM private key blocks
    text = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY BLOCK]",
        text,
    )

    # Redact standard AWS / GitHub / Generic secret assignments
    text = re.sub(
        r"(?i)\b(aws_secret_access_key|api_key|token|secret|password|auth_token)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.\/]{16,}['\"]?",
        r"\1 = [REDACTED]",
        text,
    )

    return text


def filter_diff_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    """Split changed paths into reviewable files and redacted sensitive files."""
    kept: list[str] = []
    redacted: list[str] = []
    for path in paths:
        if is_sensitive_path(path):
            redacted.append(path)
        else:
            kept.append(path)
    return kept, redacted
