import { describe, expect, test } from "bun:test"

import { fingerprintTree, shouldSkipFingerprintEntry } from "#domain/Fingerprint"

const bytes = (value: string): Uint8Array => new TextEncoder().encode(value)

describe("tree fingerprints", () => {
  test("matches Python SHA-256 golden vectors", () => {
    expect(fingerprintTree(null)).toBe("ffa63583dfa6706b87d284b86b0d693a161e4840aad2c5cf6b5d27c3b9621f7d")
    expect(fingerprintTree([])).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    expect(
      fingerprintTree([
        {
          name: "sub",
          kind: "directory",
          entries: [{ name: "a.txt", kind: "file", content: bytes("hello") }],
        },
      ]),
    ).toBe("15d512b6bcc2bd610319078a4406fa5c32c611f2f5940fd9073d1b778bff69e7")
    expect(
      fingerprintTree([
        { name: "link", kind: "broken" },
        { name: "a", kind: "file", content: bytes("abc") },
      ]),
    ).toBe("7914cefb6f2cf04a62a7370253e9b2407f8ffbbc0cbd3ed5279e6dc92b98197d")
  })

  test("ignores hidden, cache and bytecode entries at every depth", () => {
    expect(shouldSkipFingerprintEntry("node_modules")).toBe(true)
    expect(shouldSkipFingerprintEntry("cache.pyc")).toBe(true)
    expect(shouldSkipFingerprintEntry("visible")).toBe(false)
    expect(
      fingerprintTree([
        { name: ".hidden", kind: "file", content: bytes("x") },
        { name: "__pycache__", kind: "directory", entries: [] },
      ]),
    ).toBe(fingerprintTree([]))
  })
})
