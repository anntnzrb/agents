import { dlopen, FFIType } from "bun:ffi"
import { afterEach, expect, test } from "bun:test"
import {
  chmodSync,
  closeSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  readlinkSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { homedir, tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { Array as Arr, String as Str } from "effect"

const syncRoot = fileURLToPath(new URL("../..", import.meta.url))
const roots: string[] = []
const servers: { stop: (closeActiveConnections?: boolean) => unknown }[] = []
afterEach(() => {
  for (const server of servers.splice(0)) {
    server.stop(true)
  }
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

const put = (file: string, content: string, mode?: number) => {
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, content)
  if (mode !== undefined) {
    chmodSync(file, mode)
  }
}

const homeFixture = () => {
  const home = mkdtempSync(path.join(tmpdir(), "sync-integration-"))
  roots.push(home)
  return home
}

const environment = (home: string) => ({
  ...process.env,
  HOME: home,
  BUN_INSTALL_CACHE_DIR: process.env["BUN_INSTALL_CACHE_DIR"] ?? path.join(homedir(), ".bun/install/cache"),
  XDG_CACHE_HOME: path.join(home, ".cache"),
  PATH: `${path.join(home, "bin")}:${process.env["PATH"] ?? ""}`,
  npm_config_offline: "true",
  npm_config_audit: "false",
  npm_config_fund: "false",
})

const run = async (home: string, args: string[], executable = process.execPath) => {
  const cmd =
    executable === process.execPath ? [executable, "run", "src/main.ts", ...args] : [executable, ...args]
  const child = Bun.spawn(cmd, {
    cwd: syncRoot,
    env: environment(home),
    stdin: "ignore",
    stdout: "pipe",
    stderr: "pipe",
  })
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ])
  return { stdout, stderr, exitCode }
}

const seedCache = (home: string, script: string) => {
  const key = Str.slice(0, 16)(new Bun.CryptoHasher("sha256").update("mcporter").digest("hex"))
  const root = path.join(home, ".cache/npm-tools/mcporter/packages", key)
  const version = path.join(root, "versions/1.0.0")
  put(path.join(version, "node_modules/mcporter/package.json"), '{"name":"mcporter","version":"1.0.0"}')
  put(path.join(version, "node_modules/.bin/mcporter"), script, 0o755)
  symlinkSync("versions/1.0.0", path.join(root, "current"))
}

const fixture = () => {
  const home = homeFixture()
  const server = Bun.serve({
    port: 0,
    hostname: "127.0.0.1",
    fetch: (request) =>
      new URL(request.url).pathname === "/v1/models"
        ? Response.json({ data: [{ id: "fixture" }] })
        : new Response("not found", { status: 404 }),
  })
  servers.push(server)
  const ssot = path.join(home, "src/agents")
  put(path.join(ssot, "agents.toml"), `[gateway]\nbase_url = "http://127.0.0.1:${server.port}/v1"\n`)
  put(path.join(ssot, "HARNESS.md"), "agent-instructions\n")
  put(path.join(ssot, "skills/current/example/SKILL.md"), "skill-content\n")
  put(path.join(ssot, "harnesses/codex/custom.txt"), "managed-content\n")
  put(path.join(ssot, "tools/mcporter/mcporter.jsonc"), "{}\n")
  cpSync(
    path.join(syncRoot, "test/fixtures/summarize-config.json"),
    path.join(ssot, "tools/summarize/config.json"),
  )
  const source = path.join(ssot, "sync")
  mkdirSync(source, { recursive: true })
  cpSync(path.join(syncRoot, "src"), path.join(source, "src"), { recursive: true })
  cpSync(path.join(syncRoot, "package.json"), path.join(source, "package.json"))
  cpSync(path.join(syncRoot, "bun.lock"), path.join(source, "bun.lock"))
  return { home, ssot }
}

test("help and invalid command are handled at the process boundary", async () => {
  const home = homeFixture()
  const helps = await Promise.all(
    Arr.map([["--help"], ["launch", "--help"], ["job", "--help"]], (args) => run(home, args)),
  )
  for (const result of helps) {
    expect(result.exitCode).toBe(0)
    expect(Str.toLowerCase(result.stdout)).toContain("usage")
  }
  const invalid = await run(home, ["not-a-command"])
  expect(invalid.exitCode).toBe(2)
  expect(invalid.stderr.length).toBeGreaterThan(0)
})

test("sync publishes an idempotent release, cleans owned entries and preserves user files", async () => {
  const { home, ssot } = fixture()
  const userFile = path.join(home, ".codex/user.txt")
  put(userFile, "user-content\n")
  const first = await run(home, [])
  expect(first.exitCode).toBe(0)
  const instruction = path.join(home, ".codex/AGENTS.md")
  const managed = path.join(home, ".codex/custom.txt")
  const wrapper = path.join(home, ".local/bin/codex")
  const release = path.join(home, ".local/share/agents/sync-current/sync")
  expect(readFileSync(instruction, "utf8")).toBe("agent-instructions\n")
  expect(readFileSync(managed, "utf8")).toBe("managed-content\n")
  expect(readFileSync(path.join(home, ".codex/skills/example/SKILL.md"), "utf8")).toBe("skill-content\n")
  expect(readFileSync(wrapper, "utf8")).toContain("agents-managed-wrapper:v1")
  const initial = statSync(instruction)
  const current = readlinkSync(path.join(home, ".local/share/agents/sync-current"))
  const second = await run(home, [])
  expect(second.exitCode).toBe(0)
  expect(readlinkSync(path.join(home, ".local/share/agents/sync-current"))).toBe(current)
  expect(statSync(instruction).ino).toBe(initial.ino)
  expect(statSync(instruction).mtimeMs).toBe(initial.mtimeMs)
  rmSync(path.join(ssot, "harnesses/codex/custom.txt"))
  const third = await run(home, [])
  expect(third.exitCode).toBe(0)
  expect(existsSync(managed)).toBe(false)
  expect(readFileSync(userFile, "utf8")).toBe("user-content\n")
  const compiledHelp = await run(home, ["--help"], release)
  expect(compiledHelp.exitCode).toBe(0)
  expect(Str.toLowerCase(compiledHelp.stdout)).toContain("usage")
  seedCache(home, '#!/bin/sh\nprintf "compiled:<%s>\\n" "$@"\nexit 7\n')
  const compiledLaunch = await run(home, ["launch", "mcporter", "--", "hello world"], release)
  expect(compiledLaunch.exitCode).toBe(7)
  expect(compiledLaunch.stdout).toContain("hello world")
}, 180_000)

test("cached launch replaces the process, preserves PID, arguments and exit status", async () => {
  const home = homeFixture()
  seedCache(home, '#!/bin/sh\nprintf "pid=%s\\n" "$$"\nprintf "arg=<%s>\\n" "$@"\nexit 7\n')
  const child = Bun.spawn(
    [process.execPath, "run", "src/main.ts", "launch", "mcporter", "--", "hello world", "--flag"],
    { cwd: syncRoot, env: environment(home), stdin: "ignore", stdout: "pipe", stderr: "pipe" },
  )
  const [stdout, stderr, status] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ])
  expect(status).toBe(7)
  expect(stdout).toContain(`pid=${child.pid}`)
  expect(stdout).toContain("arg=<hello world>")
  expect(stdout).toContain("arg=<--flag>")
  expect(stderr).not.toContain("launch failed")
})

test("cold launch installs from npm and forwards the tool exit status", async () => {
  const home = homeFixture()
  put(
    path.join(home, "bin/npm"),
    `#!/bin/sh
case "$1" in
  view) echo 1.0.0 ;;
  install)
    shift
    while [ "$1" != "--prefix" ]; do shift; done
    prefix="$2"
    mkdir -p "$prefix/node_modules/mcporter" "$prefix/node_modules/.bin"
    printf '%s\\n' '{"name":"mcporter","version":"1.0.0"}' > "$prefix/node_modules/mcporter/package.json"
    printf '%s\\n' '#!/bin/sh' 'if [ "$1" = "--version" ]; then echo 1.0.0; exit 0; fi' 'printf "cold:<%s>\\n" "$@"' 'exit 9' > "$prefix/node_modules/.bin/mcporter"
    chmod +x "$prefix/node_modules/.bin/mcporter" ;;
  *) exit 1 ;;
esac
`,
    0o755,
  )
  const result = await run(home, ["launch", "mcporter", "--", "cold arg"])
  expect(result.exitCode).toBe(9)
  expect(result.stdout).toContain("cold:<cold arg>")
})

test("a held sync lock skips reconciliation and is released on exit", async () => {
  const { home } = fixture()
  const state = path.join(home, ".local/share/agents/sync-managed")
  mkdirSync(state, { recursive: true })
  const fd = openSync(path.join(state, "sync.lock"), "w")
  const library = dlopen(process.platform === "darwin" ? "/usr/lib/libSystem.B.dylib" : "libc.so.6", {
    flock: { args: [FFIType.i32, FFIType.i32], returns: FFIType.i32 },
  })
  try {
    expect(library.symbols.flock(fd, 2 | 4)).toBe(0)
    const contended = await run(home, [])
    expect(contended.exitCode).toBe(0)
    expect(contended.stderr).toContain("already running")
    expect(existsSync(path.join(home, ".codex/AGENTS.md"))).toBe(false)
  } finally {
    closeSync(fd)
    library.close()
  }
  const released = await run(home, [])
  expect(released.exitCode).toBe(0)
  expect(readFileSync(path.join(home, ".codex/AGENTS.md"), "utf8")).toBe("agent-instructions\n")
}, 180_000)

test("SIGTERM sent to the launch PID reaches the cached tool", async () => {
  const home = homeFixture()
  seedCache(home, '#!/bin/sh\ntrap "exit 143" TERM\necho ready\nwhile :; do sleep 0.1; done\n')
  const child = Bun.spawn([process.execPath, "run", "src/main.ts", "launch", "mcporter"], {
    cwd: syncRoot,
    env: environment(home),
    stdin: "ignore",
    stdout: "pipe",
    stderr: "ignore",
  })
  try {
    const reader = child.stdout.getReader()
    const first = await reader.read()
    expect(new TextDecoder().decode(first.value)).toContain("ready")
    reader.releaseLock()
    child.kill("SIGTERM")
    expect(await child.exited).toBe(143)
  } finally {
    child.kill("SIGKILL")
    await child.exited
  }
}, 20_000)
