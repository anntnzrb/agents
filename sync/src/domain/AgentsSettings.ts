import { Array as Arr, Option, Result, Schema, SchemaGetter, String as Str } from "effect"

export const AGENTS_SETTINGS_FILE = "agents.toml"
export const CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER = `\${CLIPROXY_CLIENT_BASE_URL}`
export const CLI_PROXY_CLIENT_ORIGIN_PLACEHOLDER = `\${CLIPROXY_CLIENT_ORIGIN}`
export const CLI_PROXY_ENDPOINT_PLACEHOLDERS = [
  CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER,
  CLI_PROXY_CLIENT_ORIGIN_PLACEHOLDER,
] as const

const stripTrailingSlashes = Str.replace(/\/+$/u, "")

const validGatewayUrl = (raw: string): boolean => {
  if (raw === "" || raw !== Str.trim(raw) || /[?#]/u.test(raw)) {
    return false
  }
  const url = Str.replaceAll(/[\t\r\n]/gu, "")(raw)
  const match = /^([a-z][a-z0-9+.-]*):\/\/([^/]*)(.*)$/iu.exec(url)
  if (match === null) {
    return false
  }
  const scheme = Str.toLowerCase(match[1] ?? "")
  const authority = match[2] ?? ""
  const path = match[3] ?? ""
  if ((scheme !== "http" && scheme !== "https") || stripTrailingSlashes(path) !== "/v1") {
    return false
  }
  const at = Option.getOrElse(Str.lastIndexOf("@")(authority), () => -1)
  if (at !== -1 && Str.replace(":", "")(Str.slice(0, at)(authority)) !== "") {
    return false
  }
  const host = Str.slice(at + 1)(authority)
  if (Str.includes("[")(host) || Str.includes("]")(host)) {
    if (!/^\[[^\]]+\](?::.*)?$/u.test(host)) {
      return false
    }
    const literal = Str.split(host, "]")[0]
    if (!/^\[v[0-9a-f]+\..+$/iu.test(literal)) {
      try {
        return new URL(`http://${literal}]/`).hostname !== ""
      } catch {
        return false
      }
    }
    return true
  }
  return Str.split(host, ":")[0] !== ""
}

const GatewayBaseUrl = Schema.String.check(
  Schema.makeFilter(validGatewayUrl, {
    message: "expected an HTTP(S) /v1 endpoint without credentials, query, or fragment",
  }),
).pipe(
  Schema.decodeTo(Schema.String, {
    decode: SchemaGetter.transform(stripTrailingSlashes),
    encode: SchemaGetter.transform((value) => value),
  }),
)

export const GatewaySettings = Schema.Struct({ base_url: GatewayBaseUrl })
export type GatewaySettings = typeof GatewaySettings.Type
export const AgentsSettings = Schema.Struct({ gateway: GatewaySettings })
export type AgentsSettings = typeof AgentsSettings.Type

const decodeSettings = Schema.decodeUnknownResult(AgentsSettings, { onExcessProperty: "error" })
export const parseAgentsSettings = (input: unknown): AgentsSettings =>
  Result.getOrThrow(decodeSettings(input))

export const cliproxyModelsUrl = (settings: AgentsSettings): string =>
  `${stripTrailingSlashes(settings.gateway.base_url)}/models`

export const hasCliproxyEndpointPlaceholder = (text: string): boolean =>
  Arr.some<string>((placeholder) => Str.includes(placeholder)(text))(CLI_PROXY_ENDPOINT_PLACEHOLDERS)

export const renderCliproxyEndpointTemplate = (template: string, settings: AgentsSettings): string => {
  if (!hasCliproxyEndpointPlaceholder(template)) {
    throw new Error(
      `missing CLIProxyAPI endpoint placeholder: ${Arr.join(CLI_PROXY_ENDPOINT_PLACEHOLDERS, " or ")}`,
    )
  }
  const base = settings.gateway.base_url
  const origin = Str.endsWith("/v1")(base) ? Str.slice(0, -3)(base) : base
  return Str.replaceAll(
    CLI_PROXY_CLIENT_ORIGIN_PLACEHOLDER,
    origin,
  )(Str.replaceAll(CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER, base)(template))
}

const parseBasicKey = (value: string): string | null => {
  let invalid = false
  let decoded = ""
  let offset = 0
  for (const match of Str.matchAll(/\\(?:[btnfr"\\]|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)/gu)(value)) {
    const index = match.index ?? offset
    decoded += Str.slice(offset, index)(value)
    offset = index + match[0].length
    const escape = match[0]
    const simple: Record<string, string> = {
      b: "\b",
      t: "\t",
      n: "\n",
      f: "\f",
      r: "\r",
      '"': '"',
      "\\": "\\",
    }
    const code = escape[1] ?? ""
    if (code === "u" || code === "U") {
      const point = Number.parseInt(Str.slice(2)(escape), 16)
      if (point > 1_114_111 || (point >= 55_296 && point <= 57_343)) {
        invalid = true
        continue
      }
      decoded += String.fromCodePoint(point)
      continue
    }
    const result = simple[code]
    if (result === undefined) {
      invalid = true
      continue
    }
    decoded += result
  }
  decoded += Str.slice(offset)(value)
  return invalid ? null : decoded
}

export const parseTomlKeyPath = (raw: string): string[] | null => {
  const parts: string[] = []
  let remaining = Str.trim(raw)
  while (remaining !== "") {
    const match = /^(?:([A-Za-z0-9_-]+)|'([^']*)'|"((?:\\.|[^"\\])*)")/u.exec(remaining)
    if (match === null) {
      return null
    }
    for (const char of match[0]) {
      const point = Option.getOrElse(Str.codePointAt(0)(char), () => 0)
      if (point < 32 || point === 127) {
        return null
      }
    }
    const key = match[1] ?? match[2] ?? parseBasicKey(match[3] ?? "")
    if (key === null) {
      return null
    }
    parts.push(key)
    remaining = Str.trimStart(Str.slice(match[0].length)(remaining))
    if (remaining === "") {
      return parts
    }
    if (!Str.startsWith(".")(remaining)) {
      return null
    }
    remaining = Str.trimStart(Str.slice(1)(remaining))
    if (remaining === "") {
      return null
    }
  }
  return null
}

export const parseTomlTableHeader = (line: string): string[] | null => {
  const text = Str.trim(line)
  const match = /^(\[\[|\[)(.*?)(\]\]|\])\s*(?:#.*)?$/u.exec(text)
  if (match === null || (match[1] === "[[") !== (match[3] === "]]")) {
    return null
  }
  return parseTomlKeyPath(match[2] ?? "")
}

const splitLines = (text: string): string[] => {
  const lines: string[] = []
  let start = 0
  for (let index = 0; index < text.length; index++) {
    const code = Option.getOrElse(Str.codePointAt(index)(text), () => -1)
    if (
      code === 10 ||
      code === 13 ||
      code === 11 ||
      code === 12 ||
      (code >= 28 && code <= 30) ||
      code === 133 ||
      code === 8232 ||
      code === 8233
    ) {
      if (code === 13 && Option.getOrElse(Str.codePointAt(index + 1)(text), () => -1) === 10) {
        index++
      }
      lines.push(Str.slice(start, index + 1)(text))
      start = index + 1
    }
  }
  if (start < text.length) {
    lines.push(Str.slice(start)(text))
  }
  return lines
}

export const extractPreservedTopLevels = (existing: string, topLevels: readonly string[]): string => {
  const prefixes: string[][] = []
  for (const key of topLevels) {
    const parsed = parseTomlKeyPath(key)
    if (parsed !== null) {
      prefixes.push(parsed)
    }
  }
  const sections: string[] = []
  let current: string | null = null
  for (const line of splitLines(existing)) {
    if (line === "") {
      continue
    }
    const header = parseTomlTableHeader(line)
    if (header !== null) {
      if (current !== null) {
        sections.push(Str.trimEnd(current))
      }
      current = Arr.some<string[]>(
        (prefix) =>
          prefix.length <= header.length && Arr.every<string>((key, index) => header[index] === key)(prefix),
      )(prefixes)
        ? ""
        : null
    }
    if (current !== null) {
      current += line
    }
  }
  if (current !== null) {
    sections.push(Str.trimEnd(current))
  }
  return sections.length === 0 ? "" : `${Arr.join(sections, "\n\n")}\n`
}

export const appendPreservedSections = (rendered: string, preserved: string): string => {
  if (preserved === "") {
    return rendered
  }
  if (rendered === "") {
    return preserved
  }
  if (Str.endsWith("\n\n")(rendered)) {
    return `${rendered}${preserved}`
  }
  if (Str.endsWith("\n")(rendered)) {
    return `${rendered}\n${preserved}`
  }
  return `${rendered}\n\n${preserved}`
}
