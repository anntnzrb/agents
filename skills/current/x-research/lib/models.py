"""Shared constants, error types, and JSON payload aliases for x-research."""

from typing import Literal, TypedDict, override

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

    @override
    def __repr__(self) -> str:
        return "undefined"


UNDEFINED = _Undefined()
"""Singleton used wherever the TypeScript source reads ``undefined``."""


class CliError(Exception):
    """Usage or validation failure; maps to exit code 2."""

    code: str
    message: str
    details: dict[str, object]

    def __init__(self, *, code: str, message: str, details: dict[str, object]) -> None:
        """Store the structured ``code``, ``message``, and ``details`` fields."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class ProviderError(Exception):
    """Provider, network, HTTP, or payload failure; maps to exit code 1."""

    code: str
    message: str
    details: dict[str, object]

    def __init__(self, *, code: str, message: str, details: dict[str, object]) -> None:
        """Store the structured ``code``, ``message``, and ``details`` fields."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class ContractError(Exception):
    """Normalized contract failure; maps to exit code 1."""

    code: str
    message: str
    details: dict[str, object]

    def __init__(self, *, code: str, message: str, details: dict[str, object]) -> None:
        """Store the structured ``code``, ``message``, and ``details`` fields."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# Normalized output shapes.
class PostAuthor(TypedDict, total=False):
    id: str
    handle: str
    name: str
    url: str
    verified: bool


type ProfileData = PostAuthor


class PostMetrics(TypedDict, total=False):
    replies: int | float
    reposts: int | float
    likes: int | float
    quotes: int | float
    bookmarks: int | float
    views: int | float


class MediaFormat(TypedDict, total=False):
    container: str
    codec: str
    url: str
    bitrate: int | float
    size: int | float
    height: int | float
    width: int | float
    webp: str
    jpeg: str


class MediaItem(TypedDict, total=False):
    type: str
    url: str
    format: str
    thumbnail_url: str
    transcode_url: str
    altText: str
    width: int | float
    height: int | float
    duration: int | float
    filesize: int | float
    formats: list[MediaFormat]
    state: str
    title: str


class MediaDict(TypedDict, total=False):
    all: list[MediaItem]
    photos: list[MediaItem]
    videos: list[MediaItem]
    external: MediaItem
    mosaic: MediaItem
    broadcast: MediaItem


class PostData(TypedDict, total=False):
    id: str
    url: str
    text: str
    created_at: str
    author: PostAuthor
    metrics: PostMetrics
    lang: str
    media: MediaDict
    quote_id: str
    reply_to_id: str


class StatusPayloadData(TypedDict):
    post: PostData


class PagePayloadData(TypedDict, total=False):
    posts: list[PostData]
    requested_count: int
    returned_count: int
    complete: bool
    complete_reason: str
    profile: PostAuthor
    cursor: str
    has_more: bool


class ConversationPayloadData(TypedDict, total=False):
    target: PostData
    thread: list[PostData]
    replies: list[PostData]
    returned_count: int
    complete: bool
    complete_reason: str
    cursor: str
    has_more: bool


class ProvenanceData(TypedDict, total=False):
    provider: str
    official: bool
    auth_mode: str
    source_url: str
    endpoint: str
    fetched_at: str
    provider_status: int | None


class FetchData(TypedDict, total=False):
    post: PostData
    requested_id: str
    requested_url: str
    provider: str
    official: bool
    auth_mode: str
    source_url: str
    endpoint: str
    fetched_at: str
    provider_status: int | None


class UserPostsData(TypedDict, total=False):
    handle: str
    posts: list[PostData]
    requested_count: int
    returned_count: int
    complete: bool
    complete_reason: str
    profile: PostAuthor
    cursor: str
    has_more: bool
    provider: str
    official: bool
    auth_mode: str
    source_url: str
    endpoint: str
    fetched_at: str
    provider_status: int | None


class SearchData(TypedDict, total=False):
    query: str
    feed: str
    posts: list[PostData]
    requested_count: int
    returned_count: int
    complete: bool
    complete_reason: str
    profile: PostAuthor
    cursor: str
    has_more: bool
    provider: str
    official: bool
    auth_mode: str
    source_url: str
    endpoint: str
    fetched_at: str
    provider_status: int | None


class ConversationData(TypedDict, total=False):
    requested_id: str
    ranking_mode: str
    target: PostData
    thread: list[PostData]
    replies: list[PostData]
    returned_count: int
    complete: bool
    complete_reason: str
    cursor: str
    has_more: bool
    provider: str
    official: bool
    auth_mode: str
    source_url: str
    endpoint: str
    fetched_at: str
    provider_status: int | None


type CommandData = FetchData | UserPostsData | SearchData | ConversationData


class FailureErrorObject(TypedDict):
    code: str
    message: str
    details: dict[str, object]


class SuccessEnvelope(TypedDict):
    ok: Literal[True]
    schema_version: int
    command: str
    data: CommandData | dict[str, object]


class FailureEnvelope(TypedDict):
    ok: Literal[False]
    schema_version: int
    command: str
    error: FailureErrorObject


type ResponseEnvelope = SuccessEnvelope | FailureEnvelope
