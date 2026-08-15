---
description: Prefer modern structured async Python with TaskGroup, timeouts, httpx, and explicit cleanup
condition:
  - "\\basyncio\\.create_task\\s*\\(|\\basyncio\\.wait_for\\s*\\(|\\bloop\\.run_until_complete\\s*\\("
  - "\\brequests\\.(?:get|post|put|patch|delete)\\s*\\(|\\btime\\.sleep\\s*\\("
  - "\\basyncio\\.gather\\s*\\(|\\bhttpx\\.AsyncClient\\s*\\("
  - "\\basync\\s+def\\b|\\bawait\\b|\\basyncio\\."
scope:
  - tool:edit(*.py)
  - tool:edit(**/*.py)
  - tool:write(*.py)
  - tool:write(**/*.py)
interruptMode: never
---

Use modern structured async Python when async code is involved.

Core async rules:

- Prefer `asyncio.run(main())` as the top-level entrypoint. Avoid global event loops and `loop.run_until_complete()`.
- Prefer `asyncio.TaskGroup` for related concurrent tasks on Python 3.11+.
- Avoid bare `asyncio.create_task()` unless the task lifetime is deliberately supervised, named/tracked, and cancelled/awaited during shutdown.
- Use `asyncio.gather()` for simple result aggregation when TaskGroup semantics are not needed; use `return_exceptions=True` only for intentional best-effort/partial-failure workflows.
- Prefer `asyncio.timeout()` on Python 3.11+ over `asyncio.wait_for()` for scoped timeouts.
- Never call blocking code directly in async functions. Use async equivalents or `await asyncio.to_thread(blocking_fn, ...)`.
- Never use `time.sleep()` in async code; use `await asyncio.sleep(...)`.

HTTP / I/O:

- In async code, do not use `requests`. Use `httpx.AsyncClient`.
- Reuse one `httpx.AsyncClient` across related requests to get connection pooling; do not create a new client per request in a loop.
- Always use `async with httpx.AsyncClient(...)` or explicit lifecycle management so clients close cleanly.
- Call `response.raise_for_status()` before decoding successful HTTP responses unless the status is intentionally handled.
- Put explicit timeouts on network clients/requests.
- Add retries with backoff only around idempotent or intentionally retryable operations.

Cleanup and cancellation:

- Async generators that own resources need `try/finally` cleanup.
- Async context managers should not suppress exceptions unless that is the explicit contract.
- Background workers need a shutdown path. Cancel and await them; do not abandon tasks.
- Shared mutable state across tasks needs synchronization (`asyncio.Lock`) or message passing (`asyncio.Queue`).

Typing async:

- Type coroutine APIs explicitly.
- Use `AsyncIterator[T]` / `AsyncGenerator[T, None]` for async streams.
- Use typed result containers for partial failures instead of mixing arbitrary exception objects into normal result lists unless that is the documented API.

Testing async:

- Prefer pytest with `pytest-asyncio` and `asyncio_mode = "auto"`.
- Use async fixtures with `async with` for resources.
- Use `AsyncMock` for async dependencies; assert awaited calls with `assert_awaited_once()` / related APIs.
