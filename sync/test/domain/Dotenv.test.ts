import { describe, expect, test } from "bun:test"

import { decodeRootEnv } from "#domain/Dotenv"

describe("root dotenv", () => {
  test("preserves literals, comments in quotes, and excludes empty values", () => {
    expect(decodeRootEnv(null)).toEqual({})
    expect(
      decodeRootEnv(
        `\uFEFF# comment\nexport QUOTED="secret # value"\nSINGLE='single'\nEMPTY=\nEMPTY_QUOTED=""\nNO_VALUE\nREF=\${UNEXPANDED}\nDOLLAR=$LITERAL\nHASH=#literal\nCOMMENT=hello # comment\nBLANK= # comment\n`,
      ),
    ).toEqual({
      QUOTED: "secret # value",
      SINGLE: "single",
      REF: `\${UNEXPANDED}`,
      DOLLAR: "$LITERAL",
      HASH: "#literal",
      COMMENT: "hello",
    })
  })

  test("handles quoted escapes, multiline values, duplicate keys and malformed lines", () => {
    const input = String.raw`'quoted key'='it\'s \\ fine'
DOUBLE="line\nnext\t\"quoted\"\q"
MULTI='first
second'
DUP=first
DUP=
INVALID="closed" trailing
AFTER=ok
`
    expect(decodeRootEnv(input)).toEqual({
      "quoted key": String.raw`it's \ fine`,
      DOUBLE: 'line\nnext\t"quoted"\\q',
      MULTI: "first\nsecond",
      AFTER: "ok",
    })
  })
})
