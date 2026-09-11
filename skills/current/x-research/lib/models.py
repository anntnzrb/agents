"""Shared constants, error types, and JSON payload aliases for x-research."""

from typing import Any, Literal

SCHEMA_VERSION = 1
PROVIDER_NAME = "fxtwitter"
DEFAULT_BASE_URL = "https://api.fxtwitter.com"
DEFAULT_TIMEOUT = 10

type CommandName = Literal["fetch", "user-posts", "search", "conversation"]
type FeedChoice = Literal["latest", "top", "media"]
type RankingChoice = Literal["likes", "recency"]
type CompleteReason = Literal[
    "bounded_page", "provider_exhausted", "provider_incomplete"
]


class _Undefined:
    """Sentinel mirroring TypeScript ``undefined`` distinct from ``None``/``null``."""

    def __repr__(self) -> str:
        return "undefined"


UNDEFINED = _Undefined()
"""Singleton used wherever the TypeScript source reads ``undefined``."""


class CliError(Exception):
    """Usage or validation failure; maps to exit code 2."""

    def __init__(self, *, code: str, message: str, details: dict[str, Any]) -> None:
        """Store the structured ``code``, ``message``, and ``details`` fields."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class ProviderError(Exception):
    """Provider, network, HTTP, or payload failure; maps to exit code 1."""

    def __init__(self, *, code: str, message: str, details: dict[str, Any]) -> None:
        """Store the structured ``code``, ``message``, and ``details`` fields."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class ContractError(Exception):
    """Normalized contract failure; maps to exit code 1."""

    def __init__(self, *, code: str, message: str, details: dict[str, Any]) -> None:
        """Store the structured ``code``, ``message``, and ``details`` fields."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# Normalized output shapes. The TypeScript sources declare these as Effect
# Schema structs used only at compile time; at runtime every value is a plain
# JSON-compatible object built field-by-field by lib/contracts.py. They are
# aliased to ``dict[str, Any]`` here for the same reason.
type PostAuthor = dict[str, Any]
type ProfileData = dict[str, Any]
type PostMetrics = dict[str, Any]
type MediaItem = dict[str, Any]
type PostData = dict[str, Any]
type ProvenanceData = dict[str, Any]
type FetchData = dict[str, Any]
type UserPostsData = dict[str, Any]
type SearchData = dict[str, Any]
type ConversationData = dict[str, Any]
type CommandData = dict[str, Any]
type SuccessEnvelope = dict[str, Any]
type FailureErrorObject = dict[str, Any]
type FailureEnvelope = dict[str, Any]
type ResponseEnvelope = dict[str, Any]
