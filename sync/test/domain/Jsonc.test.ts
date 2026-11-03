import { describe, expect, test } from "bun:test"

import { isObjDict, isObjList, stripJsonc } from "#domain/Jsonc"

describe("stripJsonc", () => {
  test("preserves strings and newlines while removing comments and trailing commas", () => {
    const input =
      '{\n  "url": "https://example.com/a/*b*/", // line\n  "text": "quote: \\\" ok",\n  "items": [1, 2, /* first\nsecond */ ],\n  /* before end */\n}'
    expect(stripJsonc(input)).toBe(
      '{\n  "url": "https://example.com/a/*b*/", \n  "text": "quote: \\\" ok",\n  "items": [1, 2 \n ]\n  \n}',
    )
  })

  test("preserves non-trailing commas and incomplete text for the JSON parser", () => {
    expect(stripJsonc("[1, /* comment */ 2, // tail\n]")).toBe("[1,  2 \n]")
    expect(stripJsonc('{"x": 1, /* unterminated\ncomment')).toBe('{"x": 1, \n')
    expect(stripJsonc('"unterminated\\')).toBe('"unterminated\\')
  })
})

test("distinguishes JSON objects and arrays from other JSON values", () => {
  expect(isObjDict({ key: 1 })).toBe(true)
  expect(isObjDict({})).toBe(true)
  expect(isObjList([])).toBe(true)
  expect(isObjList([1, null])).toBe(true)
  for (const value of [null, true, 0, "text"]) {
    expect(isObjDict(value)).toBe(false)
    expect(isObjList(value)).toBe(false)
  }
  expect(isObjDict([])).toBe(false)
  expect(isObjList({})).toBe(false)
})
