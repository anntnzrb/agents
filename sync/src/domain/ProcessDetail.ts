import { Array as Arr, String as Str } from "effect"

import { MAX_DETAIL_CHARS } from "#domain/Constants"

export const detailFromOutput = (stdout: string, stderr: string): string => {
  const detail = Str.trim(stderr) || Str.trim(stdout) || "unknown error"
  const chars: string[] = []
  for (const char of detail) {
    chars.push(char)
  }
  return chars.length > MAX_DETAIL_CHARS
    ? `${Arr.join(chars.slice(0, MAX_DETAIL_CHARS), "")}…[truncated]`
    : detail
}
