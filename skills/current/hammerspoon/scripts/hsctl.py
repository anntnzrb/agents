#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Hammerspoon skill CLI engine — runtime, docs, source, Lua tooling.

Examples:
    uv run --script <skill-dir>/scripts/cli.py status --json
    uv run --script <skill-dir>/scripts/cli.py docs module hs.ipc --json
    uv run --script <skill-dir>/scripts/cli.py lint ~/.config/hammerspoon --json

"""

from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── cache ──────────────────────────────────────────────────────────────


def _cache_root() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "agent-skills" / "hammerspoon"
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "agent-skills" / "hammerspoon"
    return home / ".cache" / "agent-skills" / "hammerspoon"


def _cache_path_for_url(url: str, suffix: str = ".html") -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    return _cache_root() / f"{key}{suffix}"


def _cache_meta_for_url(url: str) -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    return _cache_root() / f"{key}.meta.json"


def _write_cache_meta(url: str, etag: str | None, last_modified: str | None) -> None:
    meta = {"url": url, "fetched_at": time.time()}
    if etag:
        meta["etag"] = etag
    if last_modified:
        meta["last_modified"] = last_modified
    path = _cache_meta_for_url(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta), encoding="utf-8")


def _read_cache_meta(url: str) -> dict | None:
    path = _cache_meta_for_url(url)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _is_cache_stale(url: str, ttl: int = 86400) -> bool:
    meta = _read_cache_meta(url)
    if meta is None:
        return True
    return (time.time() - meta.get("fetched_at", 0)) > ttl


# ── HTTP helpers ────────────────────────────────────────────────────────


def fetch_url(
    url: str,
    headers: dict | None = None,
    timeout: int = 30,
    force: bool = False,
    if_needed: bool = False,
) -> tuple[str, bool]:
    """Fetch URL, using cache when possible.
    Returns (content, from_cache_bool).
    """
    req_headers = dict(headers) if headers else {}
    meta = _read_cache_meta(url)
    cache_path = _cache_path_for_url(url)
    stale = _is_cache_stale(url)

    if not force and cache_path.exists() and not stale:
        return cache_path.read_text(encoding="utf-8", errors="replace"), True
    if if_needed and cache_path.exists() and stale:
        return cache_path.read_text(encoding="utf-8", errors="replace"), True

    if meta and meta.get("etag"):
        req_headers["If-None-Match"] = meta["etag"]
    if meta and meta.get("last_modified"):
        req_headers["If-Modified-Since"] = meta["last_modified"]

    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            etag = resp.headers.get("ETag")
            last_mod = resp.headers.get("Last-Modified")
            body = resp.read().decode("utf-8", errors="replace")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(body, encoding="utf-8")
            _write_cache_meta(url, etag, last_mod)
            return body, False
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and cache_path.exists():
            _write_cache_meta(url, meta.get("etag"), meta.get("last_modified"))
            return cache_path.read_text(encoding="utf-8", errors="replace"), True
        # Fallback to stale cache on HTTP errors
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="replace"), True
        raise
    except urllib.error.URLError as exc:
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="replace"), True
        raise RuntimeError(f"Network error fetching {url}: {exc.reason}") from exc


# ── output helpers ──────────────────────────────────────────────────────


def _emit_json(data: dict, exit_ok: bool = True) -> int:
    data.setdefault("ok", exit_ok)
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    if exit_ok:
        return 0
    error = data.get("error")
    if isinstance(error, str) and error.startswith(
        (
            "hs CLI not found",
            "luacheck not found",
            "stylua not found",
            "busted not found",
        ),
    ):
        return 127
    return 1


def _discover_tool(name: str, *extra_paths: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    for p in extra_paths:
        candidate = Path(p) / name
        if candidate.is_file():
            return str(candidate)
    return None


# ── runtime commands ────────────────────────────────────────────────────


def _hs_binary() -> str | None:
    """Find the hs CLI binary (Homebrew or hs.ipc.cliInstall)."""
    return _discover_tool("hs", "/usr/local/bin", "/opt/homebrew/bin")


def _run_hs(lua: str, timeout: int = 5) -> tuple[int, str, str]:
    """Run a Lua snippet through the hs CLI. Returns (rc, stdout, stderr)."""
    hs_bin = _hs_binary()
    if hs_bin is None:
        return (
            127,
            "",
            (
                "hs CLI not found. Install with:\n"
                "  hs.ipc.cliInstall()  (from Hammerspoon Console)\n"
                "and ensure require('hs.ipc') is in your init.lua"
            ),
        )
    try:
        proc = subprocess.run(
            [hs_bin, "-c", lua],
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return (
            2,
            "",
            (
                "hs timed out — is Hammerspoon running?\n"
                "Ensure Hammerspoon.app is launched and require('hs.ipc') is in your init.lua"
            ),
        )


def _run_hs_json(expr: str, timeout: int = 5) -> tuple[bool, object, str]:
    """Run Lua via hs, encoding result as JSON."""
    escaped = expr.replace("\\", "\\\\").replace("\x00", "\\0")
    wrapper = (
        "local ok, val = pcall(function() return " + escaped + " end)\n"
        "local encoded = hs.json.encode(ok and val or {error=tostring(val)})\n"
        "print(encoded)\n"
    )
    rc, stdout, stderr = _run_hs(wrapper, timeout)
    if rc != 0:
        return False, None, stderr or "hs exited with non-zero status"
    out = stdout.strip()
    if not out:
        return False, None, "hs produced no output"
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        return False, None, f"hs returned invalid JSON: {exc}\nOutput: {out[:500]}"
    return True, data, ""


def cmd_status(args: argparse.Namespace) -> int:
    result: dict = {"ok": True, "hs_binary": None, "hs_works": False, "version": None}
    hs_bin = _hs_binary()
    if hs_bin:
        result["hs_binary"] = hs_bin
    else:
        result["ok"] = False
        result["error"] = (
            "hs CLI not found. In your init.lua, add require('hs.ipc'), "
            "reload Hammerspoon, then run hs.ipc.cliInstall() from the Console."
        )
        if args.json:
            return _emit_json(result, exit_ok=False)
        print(result["error"])
        return 127

    ok, data, err = _run_hs_json(
        "hs.json.encode({version=hs.processInfo['version'] or 'unknown', "
        "configDir=tostring(hs.configDir)})",
    )
    if ok and isinstance(data, dict):
        result["hs_works"] = True
        result["version"] = data.get("version")
        result["config_dir"] = data.get("configDir")
        result.setdefault("ok", True)
    else:
        result["ok"] = False
        result["error"] = err or "hs IPC call failed"
        result["hint"] = "Is require('hs.ipc') in your init.lua?"

    if args.json:
        return _emit_json(result, exit_ok=result.get("ok", False))
    print(f"hs binary:    {result.get('hs_binary') or 'NOT FOUND'}")
    print(f"hs works:     {result.get('hs_works')}")
    if result.get("version"):
        print(f"version:      {result['version']}")
    if result.get("config_dir"):
        print(f"config dir:   {result['config_dir']}")
    if result.get("error"):
        print(f"\n{result['error']}")
    return 0 if result.get("ok") else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    result: dict = {"ok": True, "checks": []}

    hs_bin = _hs_binary()
    result["checks"].append(
        {
            "name": "hs binary",
            "ok": hs_bin is not None,
            "detail": hs_bin or "not found on PATH",
            "fix": (
                "Run hs.ipc.cliInstall() from Hammerspoon Console; "
                "ensure require('hs.ipc') in init.lua"
            )
            if not hs_bin
            else None,
        },
    )
    if not hs_bin:
        result["ok"] = False

    ok, data, err = _run_hs_json(
        "hs.json.encode({version=hs.processInfo['version'] or 'unknown', "
        "configDir=tostring(hs.configDir), "
        "accessibility=hs.canCheckAccessibility and hs.checkAccessibility()})",
    )
    if ok and isinstance(data, dict):
        result["checks"].append(
            {
                "name": "hs IPC",
                "ok": True,
                "detail": f"version={data.get('version')}, configDir={data.get('configDir')}",
            },
        )
    else:
        result["ok"] = False
        result["checks"].append(
            {
                "name": "hs IPC",
                "ok": False,
                "detail": err or "eval failed",
                "fix": "Ensure require('hs.ipc') is in your init.lua",
            },
        )

    result["checks"].append(
        {
            "name": "accessibility",
            "ok": True,
            "detail": "Cannot verify from CLI; grant in System Settings > Privacy > Accessibility",
        },
    )

    if args.json:
        code = _emit_json(result, exit_ok=result["ok"])
        return 127 if hs_bin is None else code
    for c in result["checks"]:
        status = "PASS" if c["ok"] else "FAIL"
        print(f"[{status}] {c['name']}: {c['detail']}")
        if c.get("fix"):
            print(f"       fix: {c['fix']}")
    if hs_bin is None:
        return 127
    return 0 if result["ok"] else 1


def cmd_eval(args: argparse.Namespace) -> int:
    if args.lua == "-":
        lua = sys.stdin.read().strip()
        if not lua:
            print("ERROR: no Lua expression on stdin", file=sys.stderr)
            return 1
    else:
        lua = args.lua

    if args.json:
        ok, data, err = _run_hs_json(lua)
        if not ok:
            return _emit_json({"ok": False, "error": err}, exit_ok=False)
        print(json.dumps({"ok": True, "result": data}, indent=2, ensure_ascii=False))
        return 0

    rc, stdout, stderr = _run_hs(lua)
    if rc != 0:
        print(stderr or stdout or "hs failed", file=sys.stderr)
        return rc
    sys.stdout.write(stdout)
    return 0


def cmd_eval_file(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    lua = path.read_text(encoding="utf-8")

    if args.json:
        ok, data, err = _run_hs_json(f"dofile({json.dumps(str(path))})")
        if not ok:
            return _emit_json({"ok": False, "error": err}, exit_ok=False)
        print(json.dumps({"ok": True, "result": data}, indent=2, ensure_ascii=False))
        return 0

    rc, stdout, stderr = _run_hs(lua)
    if rc != 0:
        print(stderr or stdout or "hs failed", file=sys.stderr)
        return rc
    sys.stdout.write(stdout)
    return 0


def cmd_reload(args: argparse.Namespace) -> int:
    if args.json:
        ok, data, err = _run_hs_json("hs.json.encode({reloaded=true})")
        if not ok:
            return _emit_json({"ok": False, "error": err}, exit_ok=False)
        return _emit_json({"ok": True, "result": data})
    rc, stdout, stderr = _run_hs("hs.reload()")
    if rc != 0:
        print(stderr or "reload failed", file=sys.stderr)
        return rc
    print("config reloaded")
    return 0


def _inspect_hs(label: str, expr: str, args: argparse.Namespace) -> int:
    ok, data, err = _run_hs_json(expr)
    if not ok:
        return _emit_json({"ok": False, "command": label, "error": err}, exit_ok=False)
    if args.json:
        return _emit_json({"ok": True, "command": label, "result": data})
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def cmd_windows(args: argparse.Namespace) -> int:
    return _inspect_hs(
        "windows",
        (
            "hs.json.encode(function()"
            " local r={}; for _,w in ipairs(hs.window.allWindows()) do"
            " r[#r+1]={id=w:id(),title=tostring(w:title()),"
            " app=w:application() and w:application():name() or '?',"
            " screen=w:screen() and w:screen():name() or '?',"
            " frame={x=w:frame().x,y=w:frame().y,w=w:frame().w,h=w:frame().h}}"
            " end; return r end())"
        ),
        args,
    )


def cmd_apps(args: argparse.Namespace) -> int:
    return _inspect_hs(
        "apps",
        (
            "hs.json.encode(function()"
            " local r={}; for _,a in ipairs(hs.application.runningApplications()) do"
            " r[#r+1]={name=tostring(a:name()),bundleID=tostring(a:bundleID()),"
            " pid=a:pid(),frontmost=a:isFrontmost() or false}"
            " end; return r end())"
        ),
        args,
    )


def cmd_screens(args: argparse.Namespace) -> int:
    return _inspect_hs(
        "screens",
        (
            "hs.json.encode(function()"
            " local r={}; for _,s in ipairs(hs.screen.allScreens()) do"
            " r[#r+1]={name=tostring(s:name()),id=s:id(),"
            " frame={x=s:frame().x,y=s:frame().y,w=s:frame().w,h=s:frame().h}}"
            " end; return r end())"
        ),
        args,
    )


def cmd_hotkeys(args: argparse.Namespace) -> int:
    return _inspect_hs(
        "hotkeys",
        (
            "hs.json.encode(function()"
            " local r={}; local hks=hs.hotkey.getHotkeys(); for _,hk in ipairs(hks) do"
            " local mods={}; local mks=hk.mods; if mks.cmd then mods[#mods+1]='cmd' end;"
            " if mks.alt then mods[#mods+1]='alt' end;"
            " if mks.ctrl then mods[#mods+1]='ctrl' end;"
            " if mks.shift then mods[#mods+1]='shift' end;"
            " r[#r+1]={mods=mods,key=tostring(hk.key),"
            " message=tostring(hk.msg)}"
            " end; return r end())"
        ),
        args,
    )


def cmd_spoons_loaded(args: argparse.Namespace) -> int:
    return _inspect_hs(
        "spoons",
        ("hs.json.encode(function() local r=hs.spoons.list(); return r end())"),
        args,
    )


def cmd_config(args: argparse.Namespace) -> int:
    ok, data, err = _run_hs_json("hs.json.encode(tostring(hs.configDir))")
    if not ok:
        if args.json:
            return _emit_json({"ok": False, "error": err}, exit_ok=False)
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    result = {"ok": True, "config_dir": data}
    if args.json:
        return _emit_json(result)
    print(data)
    return 0


# ── docs commands ───────────────────────────────────────────────────────

DOCS_BASE = "https://www.hammerspoon.org/docs/"
DOCS_INDEX = f"{DOCS_BASE}index.html"


class _DocsHTMLParser(html.parser.HTMLParser):
    """Parse Hammerspoon docs index to extract module list."""

    def __init__(self) -> None:
        super().__init__()
        self.modules: list[dict] = []
        self._in_a: bool = False
        self._current_href: str = ""
        self._current_text: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attrs_d = dict(attrs)
            self._in_a = True
            self._current_href = attrs_d.get("href", "")
            self._current_text = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_a:
            self._in_a = False
            if self._current_href and self._current_text:
                self.modules.append(
                    {
                        "href": self._current_href,
                        "name": self._current_text.strip(),
                    },
                )

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._current_text += data


def _fetch_docs_index(force: bool = False, if_needed: bool = False) -> str:
    return fetch_url(DOCS_INDEX, force=force, if_needed=if_needed)[0]


def _parse_docs_index(html: str) -> list[dict]:
    parser = _DocsHTMLParser()
    parser.feed(html)
    return [m for m in parser.modules if m["name"].startswith("hs.")]


def _fetch_module_doc(name: str) -> str:
    url = f"{DOCS_BASE}{name}.html"
    return fetch_url(url)[0]


def _search_in_text(text: str, query: str) -> list[dict]:
    results: list[dict] = []
    lower = text.lower()
    q = query.lower()
    idx = 0
    while True:
        idx = lower.find(q, idx)
        if idx == -1:
            break
        start = max(0, idx - 80)
        end = min(len(text), idx + len(q) + 120)
        excerpt = text[start:end].strip()
        results.append({"position": idx, "excerpt": excerpt})
        idx += len(q)
    return results


def cmd_docs_search(args: argparse.Namespace) -> int:
    query = args.query
    html = _fetch_docs_index()
    modules = _parse_docs_index(html)
    results: list[dict] = []

    # Search module names first
    for m in modules:
        if query.lower() in m["name"].lower():
            results.append(
                {
                    "kind": "module",
                    "name": m["name"],
                    "url": f"{DOCS_BASE}{m['href']}",
                    "excerpt": m["name"],
                },
            )

    # Then search doc bodies for matching modules (limit: first 8 matches)
    count = 0
    for m in modules:
        if count >= 8:
            break
        if query.lower() in m["name"].lower():
            continue  # already added above
        try:
            doc = _fetch_module_doc(m["name"])
        except Exception:
            continue
        hits = _search_in_text(doc, query)
        if hits:
            count += 1
            results.append(
                {
                    "kind": "api",
                    "module": m["name"],
                    "url": f"{DOCS_BASE}{m['name']}.html",
                    "matches": hits[:3],
                },
            )

    if args.json:
        return _emit_json({"ok": True, "query": query, "results": results})

    for r in results:
        if r["kind"] == "module":
            print(f"MODULE: {r['name']}")
            print(f"  URL: {r['url']}")
        else:
            print(f"MODULE: {r['module']}")
            print(f"  URL: {r['url']}")
            for m in r.get("matches", [])[:2]:
                print(f"  EXCERPT: {m['excerpt'].replace(chr(10), ' ')}")
        print()
    return 0


def _parse_module_signatures(html: str) -> list[dict]:
    """Extract API signatures from a module doc page."""
    results: list[dict] = []
    # Match Hammerspoon doc signature blocks
    pattern = re.compile(
        r'<a[^>]*name="([^"]*)"[^>]*></a>\s*'
        r"<h4>(hs\.\S+)</h4>\s*(?:<div[^>]*>\s*)?"
        r'<div[^>]*class="[^"]*signature[^"]*"[^>]*>\s*'
        r"<code>(.*?)</code>",
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(html):
        results.append(
            {
                "anchor": m.group(1),
                "symbol": m.group(2),
                "signature": re.sub(r"\s+", " ", m.group(3).strip()),
            },
        )

    return results


def cmd_docs_module(args: argparse.Namespace) -> int:
    name = args.module
    html = _fetch_module_doc(name)
    sigs = _parse_module_signatures(html)

    if args.json:
        return _emit_json(
            {
                "ok": True,
                "module": name,
                "url": f"{DOCS_BASE}{name}.html",
                "signatures": sigs,
            },
        )

    print(f"MODULE: {name}")
    print(f"URL: {DOCS_BASE}{name}.html")
    print()
    for s in sigs:
        print(f"  {s['symbol']}")
        print(f"    {s['signature']}")
    return 0


def cmd_docs_api(args: argparse.Namespace) -> int:
    symbol = args.symbol
    # Determine module from symbol (e.g., hs.window.moveToUnit → hs.window)
    parts = symbol.split(".")
    if len(parts) >= 2:
        module = ".".join(parts[:2])
    else:
        module = parts[0]
    html = _fetch_module_doc(module)
    sigs = _parse_module_signatures(html)
    matches = [s for s in sigs if symbol in s.get("symbol", "")]

    if args.json:
        return _emit_json(
            {
                "ok": True,
                "symbol": symbol,
                "module": module,
                "url": f"{DOCS_BASE}{module}.html",
                "results": matches,
            },
        )

    print(f"MODULE: {module}")
    print(f"URL: {DOCS_BASE}{module}.html")
    for m in matches:
        print(f"\nSYMBOL: {m.get('symbol')}")
        print(f"SIGNATURE: {m.get('signature')}")
    if not matches:
        print(f"\nNo exact match for '{symbol}' — try docs module {module}")
    return 0


def cmd_docs_refresh(args: argparse.Namespace) -> int:
    force = not args.if_needed
    try:
        _, cached = fetch_url(DOCS_INDEX, force=force, if_needed=args.if_needed)
    except Exception as exc:
        if args.json:
            return _emit_json({"ok": False, "error": str(exc)}, exit_ok=False)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    status = "fresh (cached)" if cached else "refreshed"
    if args.json:
        return _emit_json({"ok": True, "status": status, "url": DOCS_INDEX})
    print(f"docs index: {status}")
    return 0


# ── source commands ─────────────────────────────────────────────────────

SOURCE_URLS = {
    "hammerspoon": "https://raw.githubusercontent.com/Hammerspoon/hammerspoon/master/extensions/ipc/ipc.lua",
}

SPOONS_LIST_URL = "https://raw.githubusercontent.com/Hammerspoon/Spoons/master/Spoons/"


def _fetch_github_raw(url: str) -> str:
    return fetch_url(
        url,
        headers={"Accept": "application/vnd.github.v3.raw"},
        timeout=20,
    )[0]


def _gh_ls_remote_sha(repo: str) -> str | None:
    """Get HEAD SHA of a GitHub repo via git ls-remote."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        proc = subprocess.run(
            [git, "ls-remote", f"https://github.com/{repo}", "HEAD"],
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.split()[0]
    except Exception:
        pass
    return None


def cmd_source_search(args: argparse.Namespace) -> int:
    pattern = args.pattern
    results: list[dict] = []

    for name, url in SOURCE_URLS.items():
        try:
            text = _fetch_github_raw(url)
        except Exception as exc:
            results.append({"source": name, "error": str(exc)})
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.lower() in line.lower():
                results.append(
                    {
                        "source": name,
                        "url": url,
                        "line": i,
                        "text": line.strip()[:200],
                    },
                )

    if args.json:
        return _emit_json({"ok": True, "query": pattern, "results": results})

    for r in results:
        if "error" in r:
            print(f"SOURCE: {r['source']}  ERROR: {r['error']}")
        else:
            print(f"SOURCE: {r['source']}")
            print(f"  LINE {r['line']}: {r['text']}")
            print(f"  URL: {r['url']}#L{r['line']}")
    return 0


def cmd_source_fetch(args: argparse.Namespace) -> int:
    sha = _gh_ls_remote_sha("Hammerspoon/hammerspoon")
    cached = not args.if_needed or _is_cache_stale(DOCS_INDEX)
    status = "cached" if cached else "refreshed"

    result = {
        "ok": True,
        "repos": {
            "Hammerspoon/hammerspoon": {"head_sha": sha},
        },
        "cache_root": str(_cache_root()),
        "status": status,
    }
    if args.json:
        return _emit_json(result)
    for repo, info in result["repos"].items():
        print(f"  {repo}: {info.get('head_sha', 'N/A')}")
    return 0


def cmd_spoons_search(args: argparse.Namespace) -> int:
    query = args.query
    try:
        listing = _fetch_github_raw(
            "https://api.github.com/repos/Hammerspoon/Spoons/contents/Source",
        )
        entries = json.loads(listing) if listing.strip() else []
    except Exception as exc:
        if args.json:
            return _emit_json({"ok": False, "error": str(exc)}, exit_ok=False)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    results = [
        {"name": e["name"], "path": e["path"], "url": e["html_url"]}
        for e in entries
        if isinstance(e, dict) and query.lower() in e.get("name", "").lower()
    ]

    if args.json:
        return _emit_json({"ok": True, "query": query, "results": results})

    for r in results:
        print(f"SPOON: {r['name']}")
        print(f"  URL: {r['url']}")
    return 0


def cmd_spoons_source(args: argparse.Namespace) -> int:
    name = args.name
    url = (
        f"https://raw.githubusercontent.com/Hammerspoon/Spoons/master/Source/"
        f"{name}.spoon/init.lua"
    )
    try:
        text = _fetch_github_raw(url)
    except Exception as exc:
        if args.json:
            return _emit_json(
                {"ok": False, "error": str(exc), "url": url},
                exit_ok=False,
            )
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    size = len(text)
    lines = text.count("\n")

    if args.json:
        return _emit_json(
            {
                "ok": True,
                "name": name,
                "url": url,
                "size_bytes": size,
                "lines": lines,
                "preview": text[:2000],
            },
        )

    print(f"SPOON: {name}")
    print(f"URL: {url}")
    print(f"Lines: {lines}, Bytes: {size}")
    print(f"\n--- BEGIN PREVIEW ---\n{text[:2000]}")
    if size > 2000:
        print(f"\n... ({size - 2000} more bytes)")
    return 0


# ── Lua quality commands ────────────────────────────────────────────────


def cmd_lint(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    luacheck = _discover_tool("luacheck")
    if luacheck is None:
        msg = "luacheck not found. Install: brew install luacheck  or  nix shell nixpkgs#lua54Packages.luacheck"
        if args.json:
            return _emit_json({"ok": False, "error": msg}, exit_ok=False)
        print(msg, file=sys.stderr)
        return 127

    rc = subprocess.run(
        [luacheck, str(path), "--globals", "hs", "spoon", "--formatter", "plain"],
        check=False,
        shell=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if args.json:
        issues = [line.strip() for line in rc.stdout.splitlines() if line.strip()]
        return _emit_json(
            {
                "ok": rc.returncode == 0,
                "exit_code": rc.returncode,
                "tool": luacheck,
                "path": str(path),
                "issues": issues,
            },
            exit_ok=rc.returncode == 0,
        )
    sys.stdout.write(rc.stdout)
    if rc.stderr:
        sys.stderr.write(rc.stderr)
    return rc.returncode


def cmd_fmt(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    stylua = _discover_tool("stylua")
    if stylua is None:
        msg = "stylua not found. Install: brew install stylua  or  nix shell nixpkgs#stylua"
        if args.json:
            return _emit_json({"ok": False, "error": msg}, exit_ok=False)
        print(msg, file=sys.stderr)
        return 127

    if args.check:
        rc = subprocess.run(
            [stylua, "--check", str(path)],
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        ok = rc.returncode == 0
        if args.json:
            return _emit_json(
                {
                    "ok": ok,
                    "check": "passed" if ok else "issues found",
                    "tool": stylua,
                    "path": str(path),
                    "output": rc.stdout.strip() or rc.stderr.strip(),
                },
                exit_ok=rc.returncode == 0,
            )
        if not ok:
            print(rc.stdout or rc.stderr or "formatting issues")
        else:
            print("formatting ok")
        return rc.returncode

    # --write
    rc = subprocess.run(
        [stylua, str(path)],
        check=False,
        shell=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if args.json:
        return _emit_json(
            {
                "ok": rc.returncode == 0,
                "tool": stylua,
                "path": str(path),
                "output": rc.stdout.strip() or "formatted",
            },
            exit_ok=rc.returncode == 0,
        )
    print(rc.stdout.strip() or "formatted")
    return rc.returncode


def cmd_test(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    busted = _discover_tool("busted")
    if busted is None:
        msg = "busted not found. Install: brew install busted  or  nix shell nixpkgs#lua54Packages.busted"
        if args.json:
            return _emit_json({"ok": False, "error": msg}, exit_ok=False)
        print(msg, file=sys.stderr)
        return 127

    rc = subprocess.run(
        [busted, str(path)],
        check=False,
        shell=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = rc.stdout + rc.stderr
    if args.json:
        return _emit_json(
            {
                "ok": rc.returncode == 0,
                "tool": busted,
                "path": str(path),
                "exit_code": rc.returncode,
                "output": output,
            },
            exit_ok=rc.returncode == 0,
        )
    sys.stdout.write(output)
    return rc.returncode


def cmd_annotations_status(args: argparse.Namespace) -> int:
    # Check common paths for EmmyLua annotations
    config_dir = None
    ok, data, _ = _run_hs_json("tostring(hs.configDir)")
    if ok and isinstance(data, str):
        config_dir = data

    paths_to_check: list[Path] = []
    if config_dir:
        paths_to_check.append(Path(config_dir) / "annotations")
    paths_to_check.append(Path.home() / ".hammerspoon" / "annotations")

    found: list[str] = []
    for p in paths_to_check:
        if p.is_dir():
            files = list(p.glob("*.lua"))
            if files:
                found.append(f"{p} ({len(files)} files)")

    result = {
        "ok": True,
        "found": bool(found),
        "paths": found,
        "checked": [str(p) for p in paths_to_check],
        "hint": "Install EmmyLua.spoon from https://github.com/Hammerspoon/Spoons to generate annotations",
    }

    if args.json:
        return _emit_json(result)
    if found:
        print("annotations found:")
        for f in found:
            print(f"  {f}")
    else:
        print("no annotations found")
        print(f"checked: {', '.join(str(p) for p in paths_to_check)}")
        print(result["hint"])
    return 0


def cmd_lsp_config(args: argparse.Namespace) -> int:
    config = {
        "$schema": "https://raw.githubusercontent.com/LuaLS/vscode-lua/master/setting/schema.json",
        "runtime.version": "Lua 5.4",
        "diagnostics.globals": ["hs", "spoon"],
    }

    # Check if annotations exist to suggest library path
    config_dir = None
    ok, data, _ = _run_hs_json("tostring(hs.configDir)")
    if ok and isinstance(data, str):
        config_dir = data
        annot = Path(config_dir) / "annotations"
        if annot.is_dir():
            config["workspace.library"] = [str(annot)]

    if args.json:
        return _emit_json({"ok": True, "luarc": config})

    print("Suggested .luarc.json:")
    print(json.dumps(config, indent=2, ensure_ascii=False))
    return 0


# ── argument parser ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hammerspoon skill CLI engine",
        prog="hsctl",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- runtime --
    s = sub.add_parser("status", help="Hammerspoon runtime health check")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("doctor", help="status + Accessibility/MJConfigFile checks")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("eval", help="evaluate Lua via hs CLI")
    s.add_argument("lua", help="Lua expression, or '-' for stdin")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_eval)

    s = sub.add_parser("eval-file", help="evaluate a Lua file via hs CLI")
    s.add_argument("path", help="path to Lua file")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_eval_file)

    s = sub.add_parser("reload", help="trigger hs.reload()")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_reload)

    s = sub.add_parser("windows", help="list all windows")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_windows)

    s = sub.add_parser("apps", help="list running applications")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_apps)

    s = sub.add_parser("screens", help="list displays")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_screens)

    s = sub.add_parser("hotkeys", help="list registered hotkeys")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_hotkeys)

    s = sub.add_parser("spoons", help="list loaded Spoons")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_spoons_loaded)

    s = sub.add_parser("config", help="show config directory")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_config)

    # -- docs --
    s = sub.add_parser("docs", help="documentation commands")
    docs_sub = s.add_subparsers(dest="docs_command", required=True)

    sd = docs_sub.add_parser("search", help="search docs index and module bodies")
    sd.add_argument("query")
    sd.add_argument("--json", action="store_true")
    sd.set_defaults(func=cmd_docs_search)

    sd = docs_sub.add_parser("module", help="show module doc page signatures")
    sd.add_argument("module")
    sd.add_argument("--json", action="store_true")
    sd.set_defaults(func=cmd_docs_module)

    sd = docs_sub.add_parser("api", help="look up a specific API symbol")
    sd.add_argument("symbol")
    sd.add_argument("--json", action="store_true")
    sd.set_defaults(func=cmd_docs_api)

    sd = docs_sub.add_parser("refresh", help="refresh docs cache")
    sd.add_argument("--if-needed", action="store_true", dest="if_needed")
    sd.add_argument("--json", action="store_true")
    sd.set_defaults(func=cmd_docs_refresh)

    # -- source --
    s = sub.add_parser("source", help="source code commands")
    src_sub = s.add_subparsers(dest="source_command", required=True)

    ss = src_sub.add_parser("search", help="search source code for pattern")
    ss.add_argument("pattern")
    ss.add_argument("--json", action="store_true")
    ss.set_defaults(func=cmd_source_search)

    ss = src_sub.add_parser("fetch", help="fetch source metadata")
    ss.add_argument("--json", action="store_true")
    ss.add_argument("--if-needed", action="store_true", dest="if_needed")
    ss.set_defaults(func=cmd_source_fetch)

    # -- spoon search/source --
    s = sub.add_parser("spoon", help="search and view Spoon sources")
    spoon_sub = s.add_subparsers(dest="spoon_command", required=True)

    sps = spoon_sub.add_parser("search", help="search Spoons by name")
    sps.add_argument("query")
    sps.add_argument("--json", action="store_true")
    sps.set_defaults(func=cmd_spoons_search)

    sps = spoon_sub.add_parser("source", help="show Spoon source code")
    sps.add_argument("name")
    sps.add_argument("--json", action="store_true")
    sps.set_defaults(func=cmd_spoons_source)

    # -- lua quality --
    s = sub.add_parser("lint", help="lint Lua with luacheck")
    s.add_argument("path")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("fmt", help="format Lua with stylua")
    s.add_argument("path")
    s.add_argument("--check", action="store_true", help="check only, don't write")
    s.add_argument("--write", action="store_true", help="write formatted output")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_fmt)

    s = sub.add_parser("test", help="run Lua tests with busted")
    s.add_argument("path")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_test)

    s = sub.add_parser("annotations", help="EmmyLua annotations status")
    s.add_argument("sub", choices=["status"], help="subcommand")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_annotations_status)

    s = sub.add_parser("lsp-config", help="LSP configuration helpers")
    s.add_argument("sub", choices=["print"], help="subcommand")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_lsp_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
