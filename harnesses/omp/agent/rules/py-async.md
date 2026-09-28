---
description: Prefer structured async Python with anyio, httpx2, and explicit cleanup
condition:
  - "\\basyncio\\.create_task\\s*\\(|\\basyncio\\.wait_for\\s*\\(|\\bloop\\.run_until_complete\\s*\\(|\\basyncio\\.get_event_loop\\s*\\("
  - "\\brequests\\.(?:get|post|put|patch|delete)\\s*\\(|\\baiohttp\\.|\\btime\\.sleep\\s*\\("
  - "\\basyncio\\.gather\\s*\\(|\\bhttpx2?\\.AsyncClient\\s*\\(|\\bhttpx2?\\."
  - "\\basync\\s+def\\b|\\bawait\\b|\\b(?:anyio|asyncio)\\.|\\bpytest_asyncio\\b|@pytest\\.mark\\.(?:anyio|asyncio)\\b"
scope:
  - tool:edit(*.py)
  - tool:edit(**/*.py)
  - tool:write(*.py)
  - tool:write(**/*.py)
interruptMode: never
---

Read `skill://python/cookbook/async.md` for complete async patterns.

Core async rules (`anyio` for new code):

- Use `anyio` for all new async code: `anyio.run(main)` at the top level and `async with anyio.create_task_group() as tg:` for structured concurrency (`tg.start_soon`, `tg.start`, or `tg.create_task` on AnyIO 4.14+).
- Bound waits with `with anyio.fail_after(seconds):` or `with anyio.move_on_after(seconds):`.
- Never call blocking code directly in async functions. Offload unavoidable sync work with `await anyio.to_thread.run_sync(blocking_fn, ...)` and bound concurrency with `anyio.CapacityLimiter`.
- Never use `time.sleep()` in async code; use `await anyio.sleep(...)`.
- Coordinate tasks with `anyio.Lock`, `anyio.Semaphore`, `anyio.Event` (one-shot; replace instead of `.clear()`), and `anyio.create_memory_object_stream[T](max_buffer_size=N)` with `async with` on send and receive streams.

Inherited `asyncio` codebases:

- Use raw `asyncio` APIs only in inherited `asyncio` repositories or when a library hands you an `asyncio` loop.
- In inherited `asyncio` code: use `asyncio.run(main())` (or `asyncio.get_running_loop()` inside coroutines), `asyncio.TaskGroup` (3.11+) instead of `gather` or untracked `create_task()`, `asyncio.timeout()` (3.11+) over `asyncio.wait_for()`, and `await asyncio.to_thread(...)`.
- NEVER use `asyncio.get_event_loop()` outside a running loop, `asyncio.iscoroutinefunction` (use `inspect.iscoroutinefunction`), event loop policies (use `asyncio.run(..., loop_factory=)`), or `loop.run_until_complete()`.

HTTP / I/O:

- Use `httpx2` (`httpx2[http2,brotli,zstd]`) with `httpx2.AsyncClient` for async HTTP and `httpx2.Client` for sync HTTP. NEVER use `requests`, `aiohttp`, or the original `httpx` in new code.
- Reuse one `httpx2.AsyncClient` across related requests for connection pooling; do not create a new client per request in a loop.
- Manage client lifecycle with `async with httpx2.AsyncClient(timeout=...) as client:`.
- Call `response.raise_for_status()` before decoding successful HTTP responses unless status codes are handled explicitly.
- Add retries with backoff only around idempotent or intentionally retryable operations.

Cleanup, cancellation, and typing:

- Guarantee cleanup in async generators with `try/finally`. Shield bounded teardown with `anyio.move_on_after(seconds, shield=True)`.
- Do not suppress exceptions in `__aexit__` unless that is the explicit contract.
- Always re-raise cancellation exceptions (`anyio.get_cancelled_exc_class()`).
- Type coroutine APIs explicitly. Use `AsyncIterator[T]` or `AsyncGenerator[T, None]` from `collections.abc` for async streams.

Testing async:

- Use AnyIO's pytest plugin (`@pytest.mark.anyio`), never `pytest-asyncio`.
- Mock HTTP at the transport layer with `httpx2.MockTransport`. Use `AsyncMock` only for other external async boundaries and assert with `assert_awaited_once()`.
