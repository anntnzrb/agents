# httpx2 — Production Defaults

## Index

Read the section whose heading matches the task; use heading search before loading unrelated detail.

Source: [pydantic/httpx2](https://github.com/pydantic/httpx2), next-generation HTTP client for Python 3 and continuation of HTTPX under Pydantic stewardship.

Every network request **MUST** use `httpx2`. **ALL optimizations below are ON by default**: HTTP/2, brotli+zstd, tuned connection pool, fine-grained timeouts, transport retries, and TCP_NODELAY. This is the baseline; a bare `httpx2.AsyncClient()` is a bug.

## 1. Installation — all extras, always

```toml
# pyproject.toml
dependencies = [
    "httpx2[http2,brotli,zstd]",
]
```

Mandatory core extras: `http2` (HTTP/2 multiplexing via `h2`), `brotli` (Brotli `br` decoding), and `zstd` (Zstandard decoding). `socks` (via `socksio`) is optional, only for SOCKS proxies. Omitting a core extra leaves performance on the table.

## 2. The canonical defaults — ALL ON

These are the correct standard values every httpx2 client must use; use them verbatim.

```python
import socket
import httpx2

# ── These are the STANDARD values. Use them verbatim. ──

LIMITS = httpx2.Limits(
    max_connections=200,  # library default 100 is too conservative
    max_keepalive_connections=40,  # library default 20 wastes reconnects
    keepalive_expiry=30.0,  # library default 5s kills warm connections too fast
)

TIMEOUT = httpx2.Timeout(
    connect=5.0,  # TCP + TLS handshake budget
    read=30.0,  # time to receive a response chunk
    write=10.0,  # time to send a request chunk
    pool=10.0,  # time to acquire a connection from pool
)

SOCKET_OPTIONS: list[tuple[int, int, int]] = [
    (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),  # disable Nagle — no 40ms delay
]
```

Also set `http2=True`, `retries=3`, and `follow_redirects=True`. Retries apply only to `ConnectError`/`ConnectTimeout`; TCP_NODELAY disables Nagle's 40ms coalescing delay. Defaults versus library defaults: HTTP/2 `False→True`; connections `100→200`; keepalive connections `20→40`; expiry `5.0s→30.0s`; read `5.0→30.0`; pool `5.0→10.0`; retries `0→3`; redirects `False→True`. Write remains `10.0`; connect remains `5.0`.

## 3. Factory functions — the ONE correct way to create clients

Copy this into the project and always use `create_client()` / `create_async_client()`.

```python
"""httpx2 client factory. Always use create_client() / create_async_client()."""

from __future__ import annotations

import socket
import typing

import httpx2

_LIMITS = httpx2.Limits(
    max_connections=200,
    max_keepalive_connections=40,
    keepalive_expiry=30.0,
)

_TIMEOUT = httpx2.Timeout(
    connect=5.0,
    read=30.0,
    write=10.0,
    pool=10.0,
)

_SOCKET_OPTIONS: list[tuple[int, int, int]] = [
    (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
]


def create_async_client(
    *,
    base_url: str = "",
    http2: bool = True,
    retries: int = 3,
    limits: httpx2.Limits = _LIMITS,
    timeout: httpx2.Timeout = _TIMEOUT,
    headers: dict[str, str] | None = None,
    event_hooks: dict[str, list[typing.Callable[..., typing.Any]]] | None = None,
    **kwargs: typing.Any,
) -> httpx2.AsyncClient:
    transport = httpx2.AsyncHTTPTransport(
        http2=http2,
        retries=retries,
        limits=limits,
        socket_options=_SOCKET_OPTIONS,
    )
    return httpx2.AsyncClient(
        transport=transport,
        timeout=timeout,
        base_url=base_url,
        headers=headers or {},
        event_hooks=event_hooks or {},
        follow_redirects=True,
        **kwargs,
    )


def create_client(
    *,
    base_url: str = "",
    http2: bool = True,
    retries: int = 3,
    limits: httpx2.Limits = _LIMITS,
    timeout: httpx2.Timeout = _TIMEOUT,
    headers: dict[str, str] | None = None,
    event_hooks: dict[str, list[typing.Callable[..., typing.Any]]] | None = None,
    **kwargs: typing.Any,
) -> httpx2.Client:
    transport = httpx2.HTTPTransport(
        http2=http2,
        retries=retries,
        limits=limits,
        socket_options=_SOCKET_OPTIONS,
    )
    return httpx2.Client(
        transport=transport,
        timeout=timeout,
        base_url=base_url,
        headers=headers or {},
        event_hooks=event_hooks or {},
        follow_redirects=True,
        **kwargs,
    )
```

Usage:

```python
# Async — the common case
async with create_async_client(base_url="https://api.example.com") as client:
    r = await client.get("/users")

# Sync
with create_client() as client:
    r = client.get("https://api.example.com/health")
```

A bare client leaves HTTP/2, retries, TCP_NODELAY, keepalive tuning, and split timeouts off or weaker.

## 4. Special case overrides

Override factory defaults only for a specific reason:

- LLM streaming: `timeout=httpx2.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)` — no read timeout.
- Single-host API with low concurrency: `limits=httpx2.Limits(max_connections=50, max_keepalive_connections=20, keepalive_expiry=60.0)`.
- Ephemeral short-lived requests: `keepalive_expiry=5.0`.
- Unix domain sockets: `httpx2.AsyncHTTPTransport(uds="/path/to/socket", ...)`.
- mTLS/client certs: pass `verify=ssl_ctx` after `ctx.load_cert_chain(certfile=...)`.
- SOCKS proxy: install `httpx2[socks]`; use `proxy="socks5://..."`.

## 5. Event hooks — always wire observability

Every production client must log requests. Use these hooks for async clients and the sync equivalents for `Client`:

```python
import time
import logging

logger = logging.getLogger(__name__)


async def log_request(request: httpx2.Request) -> None:
    request.extensions["request_start"] = time.perf_counter()


async def log_response(response: httpx2.Response) -> None:
    start = response.request.extensions.get("request_start", 0)
    elapsed = time.perf_counter() - start
    logger.info(
        "HTTP %s %s → %d (%.3fs, %s)",
        response.request.method,
        response.request.url,
        response.status_code,
        elapsed,
        response.http_version,
    )


# Sync versions for Client
def log_request_sync(request: httpx2.Request) -> None:
    request.extensions["request_start"] = time.perf_counter()


def log_response_sync(response: httpx2.Response) -> None:
    start = response.request.extensions.get("request_start", 0)
    elapsed = time.perf_counter() - start
    logger.info(
        "HTTP %s %s → %d (%.3fs, %s)",
        response.request.method,
        response.request.url,
        response.status_code,
        elapsed,
        response.http_version,
    )
```

For automatic `raise_for_status()`:

```python
async def raise_on_error(response: httpx2.Response) -> None:
    response.raise_for_status()
```

## 6. Verification script — confirm setup is fully optimized

Run this against the target endpoint to **verify**, not decide, that optimizations are active:

```python
"""Verify httpx2 is fully optimized against a target endpoint."""

from __future__ import annotations

import socket
import time

import anyio
import httpx2


TARGET_URL = "https://api.example.com/health"
ITERATIONS = 30


async def bench(label: str, client: httpx2.AsyncClient, url: str, n: int) -> float:
    for _ in range(3):  # warmup
        await client.get(url)
    start = time.perf_counter()
    for _ in range(n):
        r = await client.get(url)
        assert r.status_code == 200
    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / n) * 1000
    print(f"  {label}: {avg_ms:.1f}ms avg ({n} reqs in {elapsed:.2f}s)")
    return avg_ms


async def main() -> None:
    results: dict[str, float] = {}

    # BAD: bare defaults (this is what we're proving is worse)
    async with httpx2.AsyncClient() as c:
        results["BAD-bare-defaults"] = await bench(
            "BAD-bare-defaults", c, TARGET_URL, ITERATIONS
        )

    # GOOD: full production defaults (this is what we always use)
    limits = httpx2.Limits(
        max_connections=200, max_keepalive_connections=40, keepalive_expiry=30.0
    )
    timeout = httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)
    transport = httpx2.AsyncHTTPTransport(
        http2=True,
        retries=3,
        limits=limits,
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    async with httpx2.AsyncClient(
        transport=transport, timeout=timeout, follow_redirects=True
    ) as c:
        results["GOOD-full-production"] = await bench(
            "GOOD-full-production", c, TARGET_URL, ITERATIONS
        )

    print("\n--- Proof ---")
    baseline = results["BAD-bare-defaults"]
    for label, avg in results.items():
        delta = ((avg - baseline) / baseline) * 100
        print(f"  {label}: {avg:.1f}ms ({delta:+.1f}% vs bare)")


if __name__ == "__main__":
    anyio.run(main)
```

## 7. Quick reference — all knobs

`httpx2.AsyncClient` / `httpx2.Client` effective defaults:

- `http1=True`, `http2=True`; `verify=True`; `cert=None`; `proxy=None`; `mounts=None`.
- `timeout`: `Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)`.
- `limits`: `Limits(max_connections=200, max_keepalive_connections=40, keepalive_expiry=30.0)`.
- `follow_redirects=True`; `max_redirects=20`; event hooks: wire logging.
- `base_url=""` (set for single-API clients); `trust_env=True`; `default_encoding="utf-8"`.

`httpx2.AsyncHTTPTransport` / `httpx2.HTTPTransport` effective defaults:

- `http1=True`, `http2=True`, `retries=3`, production `limits`, `socket_options=[TCP_NODELAY]`.
- `uds=None`, `local_address=None`, `proxy=None`.

`httpx2.Timeout`: library `connect/read/write/pool=5.0/5.0/5.0/5.0`; ours `5.0/30.0/10.0/10.0`.

`httpx2.Limits`: library `100/20/5.0`; ours `200/40/30.0` for `max_connections/max_keepalive_connections/keepalive_expiry`.

Async backend: httpcore2 uses `anyio` by default, supporting asyncio and trio; no extra config is needed on an anyio stack. For trio, install `httpcore2[trio]`.
