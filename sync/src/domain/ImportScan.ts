// Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
import { Array as Arr, Order, String as Str } from "effect"

export const BUILTIN_PACKAGE_ROOTS: readonly string[] = [
  "_http_agent",
  "_http_client",
  "_http_common",
  "_http_incoming",
  "_http_outgoing",
  "_http_server",
  "_stream_duplex",
  "_stream_passthrough",
  "_stream_readable",
  "_stream_transform",
  "_stream_wrap",
  "_stream_writable",
  "_tls_common",
  "_tls_wrap",
  "assert",
  "async_hooks",
  "buffer",
  "child_process",
  "cluster",
  "console",
  "constants",
  "crypto",
  "dgram",
  "diagnostics_channel",
  "dns",
  "domain",
  "events",
  "fs",
  "http",
  "http2",
  "https",
  "inspector",
  "module",
  "net",
  "os",
  "path",
  "perf_hooks",
  "process",
  "punycode",
  "querystring",
  "readline",
  "repl",
  "stream",
  "string_decoder",
  "sys",
  "timers",
  "tls",
  "trace_events",
  "tty",
  "url",
  "util",
  "v8",
  "vm",
  "wasi",
  "worker_threads",
  "zlib",
]

export function isValidPackageRoot(root: string): boolean {
  return /^(@[a-z0-9_.-]+\/)?[a-z0-9_.-]+$/iu.test(root)
}

export function packageRootFromSpecifier(specifier: string): string | undefined {
  const trimmed = Str.trim(specifier)
  if (trimmed === "" || /^(\.|\/|node:|bun:|data:)/u.test(trimmed) || trimmed === "bun") {
    return undefined
  }
  const parts = Str.split(trimmed, "/")
  let root = parts[0]
  if (Str.startsWith("@")(root)) {
    if (root.length === 1 || parts[1] === undefined || parts[1] === "") {
      return undefined
    }
    root += `/${parts[1]}`
  }
  return isValidPackageRoot(root) ? root : undefined
}

export function packageRootIsBuiltin(root: string): boolean {
  return BUILTIN_PACKAGE_ROOTS.includes(root)
}

type Token = { kind: "IDENT" | "STRING" | "NUMBER" | "PUNCT"; value: string }
const regexPunct = "([{;,:?=!+-*%&|^~<>"
const regexKeywords: Readonly<Record<string, true>> = {
  return: true,
  case: true,
  yield: true,
  await: true,
  typeof: true,
  void: true,
  delete: true,
  throw: true,
  default: true,
}
const alpha = (ch: string): boolean => /[\p{L}]/u.test(ch)
const digit = (ch: string): boolean => /[\p{N}]/u.test(ch)
const alnum = (ch: string): boolean => alpha(ch) || digit(ch)

function templateTail(content: string, start: number, templates: number[]): number {
  let i = start
  while (i < content.length) {
    const ch = content[i++]
    if (ch === "`") {
      return i
    }
    if (ch === "$" && content[i] === "{") {
      templates.push(0)
      return i + 1
    }
    if (ch === "\\" && i < content.length) {
      i++
    }
  }
  return i
}

function scanRegex(content: string, start: number): number {
  let i = start + 1
  let inClass = false
  while (i < content.length) {
    const ch = content[i]
    if (ch === "\n") {
      break
    }
    if (ch === "\\") {
      i += 2
      continue
    }
    if (ch === "[") {
      inClass = true
    } else if (ch === "]") {
      inClass = false
    } else if (ch === "/" && !inClass) {
      i++
      while (i < content.length && alpha(content[i] ?? "")) {
        i++
      }
      break
    }
    i++
  }
  return i
}

function scanSlash(content: string, start: number, tokens: Token[]): number {
  let i = start + 2
  if (content[start + 1] === "/") {
    while (i < content.length && content[i] !== "\n") {
      i++
    }
    return i
  }
  if (content[start + 1] === "*") {
    while (i + 1 < content.length && !(content[i] === "*" && content[i + 1] === "/")) {
      i++
    }
    return i + 2
  }
  const prev = tokens.at(-1)
  if (
    prev === undefined ||
    (prev.kind === "PUNCT" && Str.includes(prev.value)(regexPunct)) ||
    (prev.kind === "IDENT" && regexKeywords[prev.value] === true)
  ) {
    return scanRegex(content, start)
  }
  tokens.push({ kind: "PUNCT", value: "/" })
  return start + 1
}

function scanString(content: string, start: number, tokens: Token[]): number {
  const quote = content[start]
  let i = start + 1
  let value = ""
  while (i < content.length && content[i] !== quote) {
    if (content[i] === "\\" && i + 1 < content.length) {
      i++
    }
    value += content[i++] ?? ""
  }
  tokens.push({ kind: "STRING", value })
  return i < content.length ? i + 1 : i
}

function scanWord(content: string, start: number, tokens: Token[], number: boolean): number {
  let i = start + 1
  while (i < content.length) {
    const ch = content[i] ?? ""
    if (!(alnum(ch) || (number ? ch === "." : ch === "_" || ch === "$"))) {
      break
    }
    i++
  }
  tokens.push({ kind: number ? "NUMBER" : "IDENT", value: Str.slice(start, i)(content) })
  return i
}

function tokenize(content: string): Token[] {
  const tokens: Token[] = []
  const templates: number[] = []
  let i = 0
  while (i < content.length) {
    const ch = content[i] ?? ""
    if (ch === "/") {
      i = scanSlash(content, i, tokens)
    } else if (ch === "'" || ch === '"') {
      i = scanString(content, i, tokens)
    } else if (ch === "`") {
      i = templateTail(content, i + 1, templates)
    } else if (templates.length > 0 && (ch === "{" || ch === "}")) {
      const depth = templates.pop() ?? 0
      if (ch === "}" && depth === 0) {
        i = templateTail(content, i + 1, templates)
      } else {
        templates.push(depth + (ch === "{" ? 1 : -1))
        tokens.push({ kind: "PUNCT", value: ch })
        i++
      }
    } else if (/\s/u.test(ch)) {
      i++
    } else if (Str.includes(ch)("(){}[];,.*:=!<>+-&|^%?~")) {
      tokens.push({ kind: "PUNCT", value: ch })
      i++
    } else if (digit(ch)) {
      i = scanWord(content, i, tokens, true)
    } else if (alpha(ch) || ch === "_" || ch === "$") {
      i = scanWord(content, i, tokens, false)
    } else {
      i++
    }
  }
  return tokens
}

/** Extract runtime ESM and CommonJS import specifiers, including template expressions. */
export function extractImportSpecifiers(content: string): string[] {
  const tokens = tokenize(content)
  const result: string[] = []
  let i = 0
  while (i < tokens.length) {
    const [specifier, next] = scanImport(tokens, i)
    if (specifier !== undefined) {
      result.push(specifier)
    }
    i = next
  }
  return result
}

function scanImport(tokens: Token[], i: number): [string | undefined, number] {
  const is = (index: number, kind: Token["kind"], value: string): boolean =>
    tokens[index]?.kind === kind && tokens[index]?.value === value
  const token = tokens[i]
  if (
    token?.kind !== "IDENT" ||
    (token.value !== "import" && token.value !== "export" && token.value !== "require") ||
    is(i - 1, "PUNCT", ".")
  ) {
    return [undefined, i + 1]
  }
  const next = tokens[i + 1]
  const after = tokens[i + 2]
  if (token.value !== "export" && is(i + 1, "PUNCT", "(") && after?.kind === "STRING") {
    return [after.value, i + 3]
  }
  if (token.value === "require") {
    return [undefined, i + 1]
  }
  if (token.value === "import" && next?.kind === "STRING") {
    return [next.value, i + 2]
  }
  const typeOnly = isTypeOnly(tokens, i, token.value)
  for (let j = i + 1; j < tokens.length && !is(j, "PUNCT", ";") && tokens[j]?.value !== token.value; j++) {
    if (is(j, "IDENT", "from")) {
      const specifier = tokens[j + 1]
      if (specifier?.kind === "STRING") {
        return [typeOnly ? undefined : specifier.value, j + 2]
      }
      break
    }
  }
  return [undefined, i + 1]
}

function isTypeOnly(tokens: Token[], i: number, kind: string): boolean {
  const next = tokens[i + 1]
  const after = tokens[i + 2]
  return (
    next?.kind === "IDENT" &&
    next.value === "type" &&
    (kind === "export" ||
      (after !== undefined &&
        !(after.kind === "IDENT" && after.value === "from") &&
        !(after.kind === "PUNCT" && after.value === ",")))
  )
}

/** Collect missing runtime package roots from already-read source files. */
export function missingPackageRoots(
  contents: Iterable<string>,
  isInstalled: (root: string) => boolean,
): string[] {
  const missing = new Set<string>()
  for (const content of contents) {
    for (const specifier of extractImportSpecifiers(content)) {
      const root = packageRootFromSpecifier(specifier)
      if (root !== undefined && !packageRootIsBuiltin(root) && !isInstalled(root)) {
        missing.add(root)
      }
    }
  }
  return Arr.sort(missing, Order.String)
}
