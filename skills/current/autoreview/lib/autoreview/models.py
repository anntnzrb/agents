"""Core data models, schema definitions, and constant configuration for AutoReview."""

from __future__ import annotations

import re
from typing import Any, NamedTuple

ENGINES = ("codex", "claude", "amp", "pi", "kimi")
PRIORITIES = ("P0", "P1", "P2", "P3")
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
CATEGORIES = ("bug", "security", "regression", "test_gap", "maintainability")

SUBPROCESS_TEXT_ENCODING = "utf-8"
SUBPROCESS_TEXT_ERRORS = "surrogateescape"

ENGINE_GIT_CONFIG_OVERRIDES = (
    ("core.fsmonitor", "false"),
    ("core.pager", "cat"),
    ("diff.external", ""),
    ("diff.renames", "false"),
    ("pager.diff", "cat"),
    ("pager.log", "cat"),
    ("pager.show", "cat"),
)

SAFE_GIT_CONFIG_ARGS = (
    *(
        arg
        for key, value in ENGINE_GIT_CONFIG_OVERRIDES
        for arg in ("-c", f"{key}={value}")
    ),
    "-c",
    "diff.suppressBlankEmpty=false",
)

SAFE_DIFF_FLAGS = ("--no-ext-diff", "--no-textconv", "--no-renames", "--no-color")
COMMIT_DIFF_FLAGS = (*SAFE_DIFF_FLAGS, "--root", "--no-commit-id", "-r")

SENSITIVE_PATH_PARTS = {
    ".aws",
    ".azure",
    ".config/gcloud",
    ".docker",
    ".gnupg",
    ".ssh",
    "private",
}

CREDENTIAL_FILE_PATTERN = re.compile(
    r"(^|/)(?:\.netrc|\.git-credentials)$",
    re.IGNORECASE,
)

SENSITIVE_NAME_PATTERNS = [
    CREDENTIAL_FILE_PATTERN,
    re.compile(r"(^|/)\.env($|[._/-])", re.IGNORECASE),
    re.compile(r"(^|/)(id_rsa|id_dsa|id_ecdsa|id_ed25519)(\.pub)?$", re.IGNORECASE),
    re.compile(r"(^|/).*\.(pem|key|pkcs12|pfx|p12|kdbx|keystore)$", re.IGNORECASE),
]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "findings",
        "overall_correctness",
        "overall_explanation",
        "overall_confidence",
    ],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "title",
                    "body",
                    "priority",
                    "confidence",
                    "category",
                    "code_location",
                ],
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 140},
                    "body": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "category": {
                        "type": "string",
                        "enum": [
                            "bug",
                            "security",
                            "regression",
                            "test_gap",
                            "maintainability",
                        ],
                    },
                    "code_location": {
                        "type": "object",
                        "required": ["file_path", "line"],
                        "properties": {
                            "file_path": {"type": "string", "minLength": 1},
                            "line": {"type": "integer", "minimum": 1},
                        },
                    },
                },
            },
        },
        "overall_correctness": {
            "type": "string",
            "enum": ["patch is correct", "patch is incorrect"],
        },
        "overall_explanation": {"type": "string", "minLength": 1, "maxLength": 3000},
        "overall_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}


class CodeLocation(NamedTuple):
    file_path: str
    line: int


class Finding(NamedTuple):
    title: str
    body: str
    priority: str
    confidence: float
    category: str
    code_location: CodeLocation


class ReviewReport(NamedTuple):
    findings: list[dict[str, Any]]
    overall_correctness: str
    overall_explanation: str
    overall_confidence: float
