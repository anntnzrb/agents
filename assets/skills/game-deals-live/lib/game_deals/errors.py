"""Error types with stable CLI exit semantics."""

from __future__ import annotations


class GameDealsError(Exception):
    """Base error safe to show to a caller."""

    exit_code = 1


class ConfigError(GameDealsError):
    """Invalid or missing user configuration."""

    exit_code = 2


class ProviderError(GameDealsError):
    """Remote provider or transport failure."""

    exit_code = 1

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retry_after = retry_after
