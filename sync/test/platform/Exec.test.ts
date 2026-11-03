import { expect, test } from "bun:test"

import { Effect } from "effect"

import { Exec, PosixLayer } from "#platform/Exec"

test("exec reports a failed replacement", async () => {
  const program = Effect.gen(function* () {
    const exec = yield* Exec
    return yield* exec.exec({ executable: "/nonexistent/sync-executable", args: [], env: {} })
  })
  const failure = Effect.flip(program)
  const result = await Effect.runPromise(failure.pipe(Effect.provide(PosixLayer)))
  expect(result.message).toBe("exec /nonexistent/sync-executable failed")
})

test("exec replaces the process after flushing output", async () => {
  const source = `
    import { Effect } from "effect";
    import { Exec, PosixLayer } from "#platform/Exec";
    process.stdout.write("before:" + process.pid + "\\n");
    process.stderr.write("before-error\\n");
    await Effect.runPromise(Effect.gen(function* () {
      const exec = yield* Exec;
      return yield* exec.exec({ executable: "/bin/sh", args: ["-c", \`printf 'after:%s:%s\\n' "$$" "$VALUE"\`], env: { VALUE: "passed" } });
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
  expect(stdout).toBe(`before:${child.pid}\nafter:${child.pid}:passed\n`)
  expect(stderr).toBe("before-error\n")
})
