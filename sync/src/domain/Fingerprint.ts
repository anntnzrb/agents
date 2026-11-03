import { Array as Arr, Option, String as Str } from "effect"

import { isIgnoredSyncEntry } from "#domain/EntryNames"

const { sort: sortArray } = Arr

export type FingerprintEntry =
  | { readonly name: string; readonly kind: "directory"; readonly entries: readonly FingerprintEntry[] }
  | { readonly name: string; readonly kind: "file"; readonly content: Uint8Array }
  | { readonly name: string; readonly kind: "broken" }
  | { readonly name: string; readonly kind: "unreadable-file" }

export const shouldSkipFingerprintEntry = (name: string): boolean =>
  Str.startsWith(".")(name) || isIgnoredSyncEntry(name)

/** Python compares Unicode code points, not UTF-16 code units. */
export const compareCodePoints = (left: string, right: string): -1 | 0 | 1 => {
  const a = Array.from(left, (character) => Option.getOrElse(Str.codePointAt(character, 0), () => 0))
  const b = Array.from(right, (character) => Option.getOrElse(Str.codePointAt(character, 0), () => 0))
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const difference = (a[i] ?? 0) - (b[i] ?? 0)
    if (difference !== 0) {
      return difference < 0 ? -1 : 1
    }
  }
  return a.length === b.length ? 0 : a.length < b.length ? -1 : 1
}

export const fingerprintTree = (entries: readonly FingerprintEntry[] | null): string => {
  const hash = new Bun.CryptoHasher("sha256")
  if (entries === null) {
    return hash.update("missing").digest("hex")
  }
  const walk = (children: readonly FingerprintEntry[], prefix: string): void => {
    for (const entry of sortArray((a: FingerprintEntry, b: FingerprintEntry) =>
      compareCodePoints(a.name, b.name),
    )(children)) {
      if (shouldSkipFingerprintEntry(entry.name)) {
        continue
      }
      const path = prefix === "" ? entry.name : `${prefix}/${entry.name}`
      switch (entry.kind) {
        case "directory": {
          hash.update(`dir:${path}\n`)
          walk(entry.entries, path)
          break
        }
        case "file": {
          hash.update(`file:${path}\n`).update(entry.content).update("\n")
          break
        }
        case "broken": {
          hash.update(`broken:${path}\n`)
          break
        }
        case "unreadable-file": {
          hash.update(`file:${path}\nbroken:${path}\n`)
          break
        }
      }
    }
  }
  walk(entries, "")
  return hash.digest("hex")
}
