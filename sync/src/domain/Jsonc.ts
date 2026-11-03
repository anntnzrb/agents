// Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
import { Array as Arr, String as Str } from "effect"

export function isObjDict(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Arr.isArray(value)
}

export function isObjList(value: unknown): value is unknown[] {
  return Arr.isArray(value)
}

function skipComment(content: string, start: number): [number, number] {
  let i = start + 2
  let newlines = 0
  if (content[start + 1] === "/") {
    while (i < content.length && content[i] !== "\n") {
      i++
    }
  } else {
    while (i < content.length) {
      if (content[i] === "\n") {
        newlines++
      } else if (content[i] === "*" && content[i + 1] === "/") {
        return [i + 2, newlines]
      }
      i++
    }
  }
  return [i, newlines]
}

/** Remove JSONC comments and trailing commas without changing strings. */
export function stripJsonc(content: string): string {
  const result: string[] = []
  let i = 0
  while (i < content.length) {
    const ch = content[i]
    if (ch === '"') {
      result.push(ch)
      i++
      while (i < content.length) {
        const current = content[i++] ?? ""
        result.push(current)
        if (current === "\\" && i < content.length) {
          result.push(content[i++] ?? "")
        } else if (current === '"') {
          break
        }
      }
    } else if (ch === "/" && (content[i + 1] === "/" || content[i + 1] === "*")) {
      const [end, newlines] = skipComment(content, i)
      result.push(Str.repeat(newlines)("\n"))
      i = end
    } else if (ch === ",") {
      let j = i + 1
      while (true) {
        while (j < content.length && Str.includes(content[j] ?? "")(" \t\r\n")) {
          j++
        }
        if (content[j] === "/" && (content[j + 1] === "/" || content[j + 1] === "*")) {
          ;[j] = skipComment(content, j)
        } else {
          break
        }
      }
      if (j >= content.length || (content[j] !== "}" && content[j] !== "]")) {
        result.push(",")
      }
      i++
    } else {
      result.push(content[i++] ?? "")
    }
  }
  return Arr.join("")(result)
}
