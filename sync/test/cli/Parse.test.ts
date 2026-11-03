import { describe, expect, test } from "bun:test"

import { parseCli } from "#cli/Parse"

describe("CLI parsing", () => {
  test("selects sync and update", () => {
    expect(parseCli([])).toEqual({ _tag: "Sync" })
    expect(parseCli(["sync"])).toEqual({ _tag: "Sync" })
    expect(parseCli(["update", "ignored"])).toEqual({ _tag: "Update" })
  })

  test("preserves launch arguments only after the separator", () => {
    expect(parseCli(["launch", "codex"])).toEqual({ _tag: "Launch", name: "codex", args: [] })
    expect(parseCli(["launch", "codex", "--", "--help", "a b"])).toEqual({
      _tag: "Launch",
      name: "codex",
      args: ["--help", "a b"],
    })
    expect(parseCli(["launch", "codex", "arg"])).toEqual({
      _tag: "Usage",
      text: "sync: usage: launch NAME -- [ARGS...]\n",
    })
    expect(parseCli(["launch", ""])).toEqual({
      _tag: "Usage",
      text: "sync: usage: launch NAME -- [ARGS...]\n",
    })
  })

  test("dispatches both maintenance jobs", () => {
    expect(parseCli(["job", "npm-cache-clean"])).toEqual({ _tag: "Job", name: "npm-cache-clean" })
    expect(parseCli(["job", "refresh-packages"])).toEqual({ _tag: "Job", name: "refresh-packages" })
    expect(parseCli(["job"])).toEqual({
      _tag: "Usage",
      text: "sync: usage: job <npm-cache-clean|refresh-packages>\n",
    })
    expect(parseCli(["job", "other"])._tag).toBe("Usage")
    expect(parseCli(["job", "refresh-packages", "extra"])._tag).toBe("Usage")
  })

  test("rejects invalid commands and extra sync arguments", () => {
    const expected = {
      _tag: "Usage",
      text: "sync: usage: sync\nRun 'sync --help' for available commands.\n",
    } as const
    expect(parseCli(["unknown"])).toEqual(expected)
    expect(parseCli(["sync", "--help", "extra"])).toEqual(expected)
    expect(parseCli(["--help", "extra"])).toEqual(expected)
  })

  test("launch help takes precedence over remaining arguments", () => {
    expect(parseCli(["launch", "help", "extra"])).toEqual(parseCli(["launch", "--help"]))
  })
})
