# Async Programming with AnyIO

Modern async Python uses AnyIO for structured concurrency, cancellation scopes, and bounded resource execution.

## Contents

- [Structured Concurrency with Task Groups](#structured-concurrency-with-task-groups)
- [Cancellation and Timeouts](#cancellation-and-timeouts)
- [Shielding and Graceful Shutdown](#shielding-and-graceful-shutdown)
- [Bounded Concurrency with CapacityLimiter](#bounded-concurrency-with-capacitylimiter)
- [Streams and Backpressure](#streams-and-backpressure)
- [Running Blocking Work in Worker Threads](#running-blocking-work-in-worker-threads)
- [Resource Ownership and Async Context Managers](#resource-ownership-and-async-context-managers)
- [HTTP Client Lifecycle with httpx2](#http-client-lifecycle-with-httpx2)
- [Inherited asyncio Codebases](#inherited-asyncio-codebases)

---

## Structured Concurrency with Task Groups

Task groups bind concurrent tasks to a single lexical scope. A task group guarantees that all spawned tasks complete before the context block exits. If any child task raises an unhandled exception, AnyIO cancels all remaining siblings and raises an `ExceptionGroup`.

### Spawning Concurrent Tasks with `start_soon`

`tg.start_soon()` accepts a coroutine function and its arguments. It does not accept an already-called coroutine object.

```python
import anyio

async def fetch_item(item_id: int) -> str:
    await anyio.sleep(0.01)
    return f"item-{item_id}"

async def main() -> None:
    results: dict[int, str] = {}

    async def worker(item_id: int) -> None:
        results[item_id] = await fetch_item(item_id)

    async with anyio.create_task_group() as tg:
        for item_id in range(3):
            tg.start_soon(worker, item_id)

    assert results == {0: "item-0", 1: "item-1", 2: "item-2"}

anyio.run(main)
```

Collect return values by populating a dictionary, list, or memory object stream. Task groups deliberately do not return detached future objects.

### Initializing Tasks with `start`

Use `tg.start()` when a spawned task must initialize resources (such as binding a socket or loading state) before the calling task continues. The child task receives a `task_status` parameter and calls `task_status.started(value)` to signal readiness.

```python
import anyio
from anyio.abc import TaskStatus

async def server_worker(*, task_status: TaskStatus[int] = anyio.TASK_STATUS_IGNORED) -> None:
    await anyio.sleep(0.01)
    assigned_port = 8080
    task_status.started(assigned_port)
    await anyio.sleep(0.02)

async def main() -> None:
    async with anyio.create_task_group() as tg:
        port = await tg.start(server_worker)
        assert port == 8080

anyio.run(main)
```

---

## Cancellation and Timeouts

AnyIO implements level cancellation. When a `CancelScope` is cancelled, every async checkpoint (such as `anyio.sleep()` or stream I/O) within that scope raises a cancellation exception. Catching cancellation requires re-raising it; never swallow cancellation.

### Raising on Timeout: `fail_after`

`anyio.fail_after()` creates a cancel scope that raises `TimeoutError` when the deadline expires:

```python
import anyio

async def slow_work() -> None:
    await anyio.sleep(1.0)

async def main() -> None:
    timed_out = False
    try:
        with anyio.fail_after(0.02):
            await slow_work()
    except TimeoutError:
        timed_out = True
    assert timed_out

anyio.run(main)
```

### Exiting Silently on Timeout: `move_on_after`

`anyio.move_on_after()` cancels the enclosed block on deadline expiry but exits without raising an exception. Inspect `scope.cancelled_caught` to verify whether execution timed out:

```python
import anyio

async def slow_work() -> None:
    await anyio.sleep(1.0)

async def main() -> None:
    with anyio.move_on_after(0.02) as scope:
        await slow_work()

    assert scope.cancelled_caught

anyio.run(main)
```

---

## Shielding and Graceful Shutdown

When an outer scope is cancelled, entering cleanup code that awaits async operations will immediately raise cancellation. Use `CancelScope(shield=True)` to protect async cleanup. Always combine shielding with `move_on_after` so cleanup cannot hang indefinitely:

```python
import anyio

async def resilient_worker() -> None:
    try:
        await anyio.sleep(10.0)
    except anyio.get_cancelled_exc_class():
        with anyio.move_on_after(0.5, shield=True):
            await anyio.sleep(0.01)
        raise

async def main() -> None:
    async with anyio.create_task_group() as tg:
        tg.start_soon(resilient_worker)
        await anyio.sleep(0.02)
        tg.cancel_scope.cancel()

anyio.run(main)
```

---

## Bounded Concurrency with CapacityLimiter

Limit concurrent access to constrained resources (databases, third-party APIs, disk I/O) with `anyio.CapacityLimiter`. Unlike basic semaphores, `CapacityLimiter` tracks borrower identity and prevents token leaks or deadlocks from re-entrant acquisition:

```python
import anyio

async def limited_worker(limiter: anyio.CapacityLimiter, results: list[int], item: int) -> None:
    async with limiter:
        await anyio.sleep(0.01)
        results.append(item)

async def main() -> None:
    limiter = anyio.CapacityLimiter(2)
    results: list[int] = []

    async with anyio.create_task_group() as tg:
        for i in range(4):
            tg.start_soon(limited_worker, limiter, results, i)

    assert len(results) == 4

anyio.run(main)
```

---

## Streams and Backpressure

Memory object streams replace `asyncio.Queue` with typed, cloneable, backpressured channels. `create_memory_object_stream[T](max_buffer_size)` returns a connected pair of `(MemoryObjectSendStream, MemoryObjectReceiveStream)`:

```python
import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

async def producer(send_stream: MemoryObjectSendStream[int]) -> None:
    async with send_stream:
        for item in range(5):
            await send_stream.send(item)

async def consumer(receive_stream: MemoryObjectReceiveStream[int], output: list[int]) -> None:
    async with receive_stream:
        async for item in receive_stream:
            output.append(item)

async def main() -> None:
    send_stream, receive_stream = anyio.create_memory_object_stream[int](max_buffer_size=2)
    output: list[int] = []

    async with anyio.create_task_group() as tg:
        tg.start_soon(producer, send_stream)
        tg.start_soon(consumer, receive_stream, output)

    assert output == [0, 1, 2, 3, 4]

anyio.run(main)
```

Key guarantees:
- Setting `max_buffer_size=0` makes `send()` block until a consumer is waiting to receive.
- Closing all clones of the send stream terminates the consumer's `async for` loop cleanly.
- Clones allow multiple concurrent producers and consumers without external locks.

---

## Running Blocking Work in Worker Threads

Never invoke synchronous file I/O, heavy CPU routines, or blocking network clients directly on the async event loop. Offload them using `anyio.to_thread.run_sync()`:

```python
import time
import anyio

def cpu_intensive_hash(raw: str) -> str:
    time.sleep(0.01)
    return f"digest-{raw}"

def worker_thread_action() -> str:
    anyio.from_thread.run(anyio.sleep, 0.01)
    return "completed"

async def main() -> None:
    digest = await anyio.to_thread.run_sync(cpu_intensive_hash, "payload")
    assert digest == "digest-payload"

    result = await anyio.to_thread.run_sync(worker_thread_action)
    assert result == "completed"

anyio.run(main)
```

Use `anyio.from_thread.run()` inside a worker thread to execute an async coroutine back on the original event loop.

---

## Resource Ownership and Async Context Managers

Async resources must be acquired and released using `async with`. Implement either a class with `__aenter__` and `__aexit__` or a generator decorated with `@contextlib.asynccontextmanager`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import anyio

class ManagedPool:
    def __init__(self) -> None:
        self.active = False

    async def __aenter__(self) -> ManagedPool:
        await anyio.sleep(0.01)
        self.active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        with anyio.move_on_after(0.5, shield=True):
            await anyio.sleep(0.01)
            self.active = False

@asynccontextmanager
async def database_lease(name: str) -> AsyncIterator[str]:
    await anyio.sleep(0.01)
    try:
        yield f"connection:{name}"
    finally:
        with anyio.move_on_after(0.5, shield=True):
            await anyio.sleep(0.01)

async def main() -> None:
    async with ManagedPool() as pool:
        assert pool.active
    assert not pool.active

    async with database_lease("users") as lease:
        assert lease == "connection:users"

anyio.run(main)
```

---

## HTTP Client Lifecycle with httpx2

Use `httpx2.AsyncClient` for all async HTTP communication. Create a single client per application or operation lifecycle to reuse connection pools and HTTP/2 multiplexing. For client configuration, connection limits, and socket options, see `references/advanced/httpx2-optimization.md`.

```python
import anyio
import httpx2

async def fetch_path(client: httpx2.AsyncClient, path: str) -> str:
    response = await client.get(path)
    response.raise_for_status()
    payload: dict[str, str] = response.json()
    return payload["path"]

async def main() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"path": request.url.path})

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(transport=transport, base_url="https://api.example.com") as client:
        paths = ["/items/1", "/items/2"]
        results: dict[str, str] = {}

        async def worker(path: str) -> None:
            results[path] = await fetch_path(client, path)

        async with anyio.create_task_group() as tg:
            for path in paths:
                tg.start_soon(worker, path)

        assert results == {"/items/1": "/items/1", "/items/2": "/items/2"}

anyio.run(main)
```

---

## Inherited asyncio Codebases

When maintaining existing asyncio codebases or integrating with libraries that manage an asyncio loop directly:

### Modern asyncio Patterns

Run concurrent work in `asyncio.TaskGroup` and bound execution with timeouts:

```python
import asyncio

async def fetch(val: int) -> int:
    await asyncio.sleep(0.01)
    return val * 2

async def main() -> None:
    loop = asyncio.get_running_loop()
    assert loop.is_running()

    async with asyncio.timeout(1.0):
        async with asyncio.TaskGroup() as tg:
            t1 = tg.create_task(fetch(1))
            t2 = tg.create_task(fetch(2))

    assert t1.result() == 2
    assert t2.result() == 4

asyncio.run(main())
```

- Access the loop with `asyncio.get_running_loop()` inside running coroutines.
- Pass custom loop factories via `asyncio.run(main(), loop_factory=custom_factory)`.

### Prohibitions in asyncio Code

| Never | Instead | Reason |
| --- | --- | --- |
| `asyncio.get_event_loop()` | `asyncio.get_running_loop()` | Deprecated without running loop; removed in Python 3.16. |
| Event loop policies | `asyncio.run(..., loop_factory=...)` | Policy mechanism is deprecated. |
| Bare `asyncio.create_task()` without tracking | `asyncio.TaskGroup` | Unreferenced tasks are garbage-collected mid-execution. |
| `asyncio.gather()` in new code | `asyncio.TaskGroup` | Does not cancel running tasks on sibling failure. |
| `asyncio.wait_for()` | `asyncio.timeout()` | Cancels tasks via edge cancellation, risking task leaks. |
| Blocking calls (`time.sleep`) on the loop | `asyncio.to_thread()` | Freezes the event loop for all concurrent tasks. |
