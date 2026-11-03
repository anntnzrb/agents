import { String as Str } from "effect"

const escapes: Record<string, string> = {
  "\\": "\\",
  "'": "'",
  '"': '"',
  a: "\u0007",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t",
  v: "\v",
}

class Reader {
  position = 0
  readonly text: string
  constructor(text: string) {
    this.text = text
  }

  read(pattern: RegExp): string | undefined {
    pattern.lastIndex = this.position
    const match = pattern.exec(this.text)
    if (match === null) {
      return undefined
    }
    this.position = pattern.lastIndex
    return match[0]
  }

  peek(): string | undefined {
    return this.text[this.position]
  }

  skipLine(): void {
    this.read(/[^\r\n]*(?:\r|\n|\r\n)?/uy)
  }
}

const readValue = (reader: Reader): string | undefined => {
  const equal = reader.read(/[=][^\S\r\n]*/uy) ?? "="
  const first = reader.peek()
  if (equal.length > 1 && first === "#") {
    return ""
  }
  if (first !== "'" && first !== '"') {
    return Str.trimEnd(Str.replace(/\s+#.*/u, "")(reader.read(/[^\r\n]*/uy) ?? ""))
  }
  const quoted =
    first === "'" ? reader.read(/'(?:\\[\s\S]|[^'\\])*'/uy) : reader.read(/"(?:\\[\s\S]|[^"\\])*"/uy)
  if (quoted === undefined) {
    return undefined
  }
  const value = Str.slice(1, -1)(quoted)
  const pattern = first === "'" ? /\\[\\']/gu : /\\[\\'"abfnrtv]/gu
  let result = ""
  let offset = 0
  for (const match of Str.matchAll(pattern)(value)) {
    const index = match.index ?? offset
    result += Str.slice(offset, index)(value) + (escapes[match[0][1] ?? ""] ?? match[0])
    offset = index + match[0].length
  }
  return result + Str.slice(offset)(value)
}

const readBinding = (reader: Reader): [string | null, string | null] | undefined => {
  reader.read(/\s*/uy)
  if (reader.position === reader.text.length) {
    return undefined
  }
  reader.read(/(?:export[^\S\r\n]+)?/uy)
  let key: string | null = null
  if (reader.peek() !== "#") {
    const token = reader.peek() === "'" ? reader.read(/'[^']+'/uy) : reader.read(/[^=#\s]+/uy)
    if (token === undefined) {
      reader.skipLine()
      return undefined
    }
    key = Str.startsWith("'")(token) ? Str.slice(1, -1)(token) : token
  }
  reader.read(/[^\S\r\n]*/uy)
  const value = reader.peek() === "=" ? readValue(reader) : null
  if (value === undefined) {
    reader.skipLine()
    return undefined
  }
  reader.read(/(?:[^\S\r\n]*#[^\r\n]*)?/uy)
  if (reader.read(/[^\S\r\n]*(?:\r\n|\n|\r|$)/uy) === undefined) {
    reader.skipLine()
    return undefined
  }
  return [key, value]
}

// Matches python-dotenv's parser with interpolation disabled.
export const decodeRootEnv = (content: string | null): Record<string, string> => {
  if (content === null) {
    return {}
  }
  const text = Str.startsWith("\uFEFF")(content) ? Str.slice(1)(content) : content
  const reader = new Reader(text)
  const bindings = new Map<string, string | null>()
  while (reader.position < text.length) {
    const binding = readBinding(reader)
    if (binding !== undefined && binding[0] !== null) {
      bindings.set(binding[0], binding[1])
    }
  }
  const result: Record<string, string> = {}
  for (const [key, value] of bindings) {
    if (value !== null && value !== "") {
      Object.defineProperty(result, key, { value, enumerable: true, writable: true, configurable: true })
    }
  }
  return result
}
