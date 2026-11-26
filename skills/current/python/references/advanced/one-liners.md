# One-liner Scripts (PEP 723 + uv)



## Section index


# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx2[http2,brotli,zstd]",
#     "rich",
# ]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run with uv (no venv, no pip install needed):
#      uv run --script my_script.py
# ──────────────────

import httpx2
from rich import print as rprint


def main() -> None:
    with httpx2.Client(http2=True, follow_redirects=True) as client:
        resp = client.get("https://api.github.com")
        resp.raise_for_status()
        rprint(resp.json())


if __name__ == "__main__":
    main()
```

### Mandatory order

Every PEP 723 script MUST contain:

1. `# /// script` … `# ///`, containing `requires-python = ">=3.14"` and `dependencies` when the script imports third-party packages
2. The usage comment block: uv installation plus script execution; use the exact template below
3. `if __name__ == "__main__": main()` entry-point guard

Do not rely on a shebang, executable bit, or direct `./script.py` invocation. The portable run path is `uv run --script`.

### Required usage comment block

```python
# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run with uv (no venv, no pip install needed):
#      uv run --script <SCRIPT_NAME>.py [ARGS]
# ──────────────────
```

Replace `<SCRIPT_NAME>` with the actual filename; add CLI-argument descriptions when applicable. Place this block immediately after `# ///` and before imports. It is the runnable documentation for every recipient, CI job, and future maintainer.

## New-script template

Copy the metadata and usage-comment pattern; declare only dependencies the script imports. Run portably with `uv run --script <script.py> [args]`.

## Common dependency sets

| Use case | Dependencies |
|---|---|
| API client | `"httpx2[http2,brotli,zstd]"` |
| Data processing | `"polars"`, `"duckdb"` |
| CLI tool | `"typer"`, `"rich"` |
| Web scraping | `"httpx2[http2,brotli,zstd]"`, `"selectolax"` |
| File watcher | `"watchfiles"` |
| JSON pretty | `"rich"` |
| AI / LLM | `"pydantic-ai"`, `"httpx2[http2,brotli,zstd]"` |

## Examples

### Fetch + print JSON

```python
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx2[http2,brotli,zstd]",
#     "rich",
# ]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run: uv run --script fetch_json.py https://api.github.com/repos/pydantic/httpx2
# ──────────────────

import sys

import httpx2
from rich import print as rprint


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://api.github.com"
    with httpx2.Client(http2=True, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        rprint(resp.json())


if __name__ == "__main__":
    main()
```

### CSV → Parquet

```python
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "polars",
#     "typer",
#     "rich",
# ]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run: uv run --script csv2parquet.py input.csv output.parquet
# ──────────────────

from pathlib import Path

import polars as pl
import typer
from rich import print as rprint


def main(input_path: Path, output_path: Path | None = None) -> None:
    """Convert CSV to Parquet."""
    out = output_path or input_path.with_suffix(".parquet")
    df = pl.read_csv(input_path)
    df.write_parquet(out)
    rprint(f"[green]✓[/green] {input_path} → {out} ({len(df)} rows)")


if __name__ == "__main__":
    typer.run(main)
```

### Quick benchmark

```python
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx2[http2,brotli,zstd]",
#     "rich",
#     "anyio",
# ]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run: uv run --script bench.py https://api.example.com/health 50
# ──────────────────

import socket
import sys
import time

import anyio
import httpx2
from rich import print as rprint


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://api.github.com"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20

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
    ) as client:
        # warmup
        for _ in range(3):
            await client.get(url)

        start = time.perf_counter()
        for _ in range(n):
            r = await client.get(url)
            assert r.status_code == 200
        elapsed = time.perf_counter() - start

    avg_ms = (elapsed / n) * 1000
    rprint(
        f"[bold]{url}[/bold]: {avg_ms:.1f}ms avg over {n} requests ({elapsed:.2f}s total, {r.http_version})"
    )


if __name__ == "__main__":
    anyio.run(main)
```

## Anti-patterns

| Don’t | Do |
|---|---|
| `pip install httpx2 && python script.py` | `uv run --script script.py` |
| `requirements.txt` beside script | PEP 723 inline metadata when dependencies exist |
| `chmod +x script.py && ./script.py` | `uv run --script script.py` |
| `python -m venv .venv && ...` | `uv run --script` handles the environment |
| Script without usage comment | Always include the “How to run” block |
| `import asyncio; asyncio.run(main())` | `import anyio; anyio.run(main)` |
| Bare `httpx2.AsyncClient()` | Full production defaults (see `httpx2-optimization.md`) |

## Sources

- PEP 723: Inline script metadata: <https://peps.python.org/pep-0723/>
- uv `run --script` docs: <https://docs.astral.sh/uv/guides/scripts/>
- Original article: <https://www.cottongeeks.com/articles/2025-06-24-fun-with-uv-and-pep-723>
- Simon Willison on one-shot Python tools: <https://simonwillison.net/2024/Dec/19/one-shot-python-tools/>
