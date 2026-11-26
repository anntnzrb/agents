# PydanticAI Reference (v1.x, 2026)



## Section index


# Sync
result = agent.run_sync("What is the capital of Italy?")
print(result.output)

# Async
result = await agent.run("What is the capital of France?")
print(result.output)

# Streaming
async with agent.run_stream("What is the capital of the UK?") as response:
    async for text in response.stream_text():
        print(text, end="")
    # After streaming finishes:
    print(response.output)
```

`run_sync()` is a convenience wrapper over `loop.run_until_complete(self.run(...))`. Do not use it inside an active async context.

---

## 6. Dependencies

Use a `@dataclass` container, pass the **type** to `deps_type`, and pass an **instance** to `deps` at run time.

```python
from dataclasses import dataclass
import httpx2
from pydantic_ai import Agent, RunContext


@dataclass(frozen=True, slots=True)
class Deps:
    api_key: str
    http_client: httpx2.AsyncClient

agent = Agent(
    "openai:gpt-5.5",
    deps_type=Deps,
)


@agent.tool
async def fetch_data(ctx: RunContext[Deps], endpoint: str) -> str:
    r = await ctx.deps.http_client.get(
        endpoint,
        headers={"Authorization": f"Bearer {ctx.deps.api_key}"},
    )
    r.raise_for_status()
    return r.text


async def main() -> None:
    async with httpx2.AsyncClient() as client:
        deps = Deps(api_key="sk-...", http_client=client)
        result = await agent.run("Get /users", deps=deps)
        print(result.output)
```

---

## 7. Error Types & Retrying from a Tool

```python
from pydantic_ai import Agent, ModelRetry, UnexpectedModelBehavior, capture_run_messages

agent = Agent("openai:gpt-5.5", retries=3)


@agent.tool_plain
def calc_volume(size: int) -> int:
    if size == 42:
        return size**3
    raise ModelRetry("Please try again with size 42.")


with capture_run_messages() as messages:
    try:
        result = agent.run_sync("Get the volume of a box with size 6.")
    except UnexpectedModelBehavior as e:
        print("Error:", e)  # "Tool 'calc_volume' exceeded max retries count of 3"
        print("Cause:", e.__cause__)  # ModelRetry('Please try again...')
        print("Messages:", messages)
```

- **`ModelRetry`**: raise from a tool, output validator, or capability hook to ask the model to retry
- **`UnexpectedModelBehavior`**: raised when the retry limit is exceeded or the model API returns an unrecoverable error
- **`capture_run_messages()`**: context manager that records all messages exchanged during a run for debugging

---

## 8. Logfire Integration

One-line setup if the `logfire` extra is installed (included in the default `pydantic-ai` package):

```python
import logfire

logfire.configure()  # reads token from .logfire directory
logfire.instrument_pydantic_ai()  # auto-traces all agent runs
```

Alternatively, set `instrument=True` on the agent:

```python
agent = Agent("openai:gpt-5.5", instrument=True)
```

---

## 9. Minimal Complete Snippets

### (a) Basic agent with structured output

```python
from pydantic import BaseModel
from pydantic_ai import Agent


class City(BaseModel):
    name: str
    country: str


agent = Agent("openai:gpt-5.5", output_type=City)
result = agent.run_sync("Tell me about Paris")
print(result.output)  # City(name='Paris', country='France')
```

### (b) Agent with tools and dependencies

```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext


@dataclass(frozen=True, slots=True)
class Deps:
    api_key: str


agent = Agent("openai:gpt-5.5", deps_type=Deps)


@agent.tool
async def get_secret(ctx: RunContext[Deps], code: str) -> str:
    if code == "1234":
        return f"secret-for-{ctx.deps.api_key}"
    return "wrong code"


result = agent.run_sync("My code is 1234", deps=Deps(api_key="sk-abc"))
print(result.output)
```

### (c) Async streaming

```python
import anyio
from pydantic_ai import Agent

agent = Agent("openai:gpt-5.5")


async def main() -> None:
    async with agent.run_stream("Write a haiku about Python") as response:
        async for text in response.stream_text():
            print(text, end="")
        print("\n---")
        print("Final:", response.output)


anyio.run(main)
```

## Version Notes

- **V1** reached API stability in September 2025. Breaking changes are reserved for V2 (earliest April 2026)
- **v1.88.0** renamed `result_type` → `output_type` and `result_tool_name` / `result_tool_description` were removed. Use `output_type`
- The canonical accessor for run results is `result.output` (not `result.data`)
