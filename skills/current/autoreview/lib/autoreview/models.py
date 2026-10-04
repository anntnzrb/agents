"""Core data models, schema definitions, and constant configuration for AutoReview."""

import re

PRIORITIES = ("P0", "P1", "P2", "P3")
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
CATEGORIES = ("bug", "security", "regression", "test_gap", "maintainability")

SUBPROCESS_TEXT_ENCODING = "utf-8"
SUBPROCESS_TEXT_ERRORS = "surrogateescape"

GIT_CONFIG_OVERRIDES = (
    ("core.fsmonitor", "false"),
    ("core.pager", "cat"),
    ("diff.external", ""),
    ("diff.renames", "false"),
    ("pager.diff", "cat"),
    ("pager.log", "cat"),
    ("pager.show", "cat"),
)

SAFE_GIT_CONFIG_ARGS = (
    *(arg for key, value in GIT_CONFIG_OVERRIDES for arg in ("-c", f"{key}={value}")),
    "-c",
    "diff.suppressBlankEmpty=false",
)

SAFE_DIFF_FLAGS = ("--no-ext-diff", "--no-textconv", "--no-renames", "--no-color")

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
