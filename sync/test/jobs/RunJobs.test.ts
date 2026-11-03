import { afterEach, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunServices } from "@effect/platform-bun"
import { Effect, Layer } from "effect"
import { FetchHttpClient } from "effect/http"

import { runJobsWithPreserve } from "#jobs/RunJobs"
import { FilesPosix } from "#platform/Files"
import { PosixLayer as HostLive } from "#platform/Host"
import { LinksPosix as LinksLive } from "#platform/Links"
import { Proc } from "#platform/Proc"
import { PosixLayer as OutputLive } from "#services/Output"

const { join } = path
const live = Layer.mergeAll(
  BunServices.layer,
  FilesPosix,
  HostLive,
  LinksLive,
  Proc.layer,
  FetchHttpClient.layer,
  OutputLive,
)
const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

test("directory jobs preserve configured paths and file jobs copy content", async () => {
  const root = mkdtempSync(join(tmpdir(), "sync-jobs-"))
  roots.push(root)
  const src = join(root, "src")
  const dst = join(root, "dst")
  mkdirSync(src)
  mkdirSync(dst)
  writeFileSync(join(src, "new"), "new")
  writeFileSync(join(dst, "keep"), "keep")
  writeFileSync(join(dst, "stale"), "stale")
  const result = await Effect.runPromise(
    runJobsWithPreserve(
      [
        { _tag: "Dir", src, dst, scope: "Tree", preservePaths: [] },
        {
          _tag: "File",
          src: join(src, "new"),
          dst: join(root, "copy"),
          endpointTemplate: false,
          deployment: null,
        },
      ],
      new Map([[dst, ["keep"]]]),
    ).pipe(Effect.provide(live)),
  )
  expect(result).toBe(true)
  expect(readFileSync(join(dst, "keep"), "utf8")).toBe("keep")
  expect(readFileSync(join(root, "copy"), "utf8")).toBe("new")
  expect(() => readFileSync(join(dst, "stale"))).toThrow()
})
