import { expect, test } from "bun:test"

test("output writes plain text and prefixed diagnostics to their streams", async () => {
  const source = `
    import { Effect } from "effect";
    import { Output, PosixLayer } from "#services/Output";
    await Effect.runPromise(Effect.gen(function* () {
      const output = yield* Output;
      yield* output.write("hello\\n");
      yield* output.err("failed");
      yield* output.warn("careful");
    }).pipe(Effect.provide(PosixLayer)));
  `
  const child = Bun.spawn([process.execPath, "-e", source], {
    cwd: `${import.meta.dir}/../..`,
    stdout: "pipe",
    stderr: "pipe",
  })
  const [stdout, stderr, code] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ])
  expect(code).toBe(0)
  expect(stdout).toBe("hello\n")
  expect(stderr).toBe("sync: failed\nsync: warning: careful\n")
})
