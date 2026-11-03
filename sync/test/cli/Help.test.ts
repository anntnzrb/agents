import { expect, test } from "bun:test"

import { Array as Arr } from "effect"

import { parseCli } from "#cli/Parse"

const cases: readonly (readonly [readonly string[], string])[] = [
  [["--help"], "help.txt"],
  [["-h"], "help.txt"],
  [["help"], "help.txt"],
  [["sync", "--help"], "help.txt"],
  [["sync", "-h"], "help.txt"],
  [["sync", "help"], "help.txt"],
  [["launch", "--help"], "launch-help.txt"],
  [["launch", "-h"], "launch-help.txt"],
  [["launch", "help"], "launch-help.txt"],
  [["job", "--help"], "job-help.txt"],
  [["job", "-h"], "job-help.txt"],
  [["job", "help"], "job-help.txt"],
]

for (const [args, file] of cases) {
  test(`help ${Arr.join(args, " ")} matches ${file}`, async () => {
    const text = await Bun.file(`${import.meta.dir}/golden/${file}`).text()
    expect(parseCli(args)).toEqual({ _tag: "Help", text })
  })
}
