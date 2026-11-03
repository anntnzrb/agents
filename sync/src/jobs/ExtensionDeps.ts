import { Array as Arr, Effect, FileSystem, Option, Order, Path, String as Str } from "effect"

import { missingPackageRoots } from "#domain/ImportScan"
import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"

const sourceExtension = /\.(?:ts|js|mts|cts|mjs|cjs)$/u
const emptyPackage = '{\n  "name": "pi-extension-deps",\n  "private": true\n}\n'

const walk = Effect.fn("ExtensionDeps.walk")(function* (root: string, followLinks: boolean) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const files: string[] = []
  const directories: string[] = []
  const visit = Effect.fn("ExtensionDeps.visit")(function* (dir: string): Effect.fn.Return<void> {
    const names = yield* fs.readDirectory(dir).pipe(Effect.orElseSucceed((): string[] => []))
    directories.push(dir)
    for (const name of names) {
      const entry = path.join(dir, name)
      const info = yield* (followLinks ? fs.stat(entry) : fs.lstat(entry)).pipe(
        Effect.orElseSucceed(() => null),
      )
      if (info?.type === "Directory") {
        if (name !== "node_modules" && !Str.startsWith(".")(name)) {
          yield* visit(entry)
        }
      } else if (info !== null && info.type !== "SymbolicLink") {
        files.push(entry)
      } else if (!followLinks && info?.type === "SymbolicLink") {
        const target = yield* fs.stat(entry).pipe(Effect.orElseSucceed(() => null))
        if (target !== null && target.type !== "Directory") {
          files.push(entry)
        }
      }
    }
  })
  const info = yield* fs.stat(root).pipe(Effect.orElseSucceed(() => null))
  if (info?.type === "Directory") {
    yield* visit(root)
  }
  return { files, directories }
})

export const iterExtensionPackages = Effect.fn("ExtensionDeps.iterExtensionPackages")(function* (
  root: string,
) {
  const path = yield* Path.Path
  const tree = yield* walk(root, false)
  const manifests = new Set(tree.files)
  return Arr.sort(
    Arr.filter<string>((dir) => manifests.has(path.join(dir, "package.json")))(tree.directories),
    Order.String,
  )
})

export const runInstall = Effect.fn("ExtensionDeps.runInstall")(function* (
  command: readonly string[],
  directory: string,
  timeoutMs: number,
) {
  const proc = yield* Proc
  const output = yield* Output
  const outcome = yield* proc.outcome(command, directory, timeoutMs)
  const name = command[0] ?? ""
  switch (outcome._tag) {
    case "Success": {
      return true
    }
    case "MissingCommand": {
      yield* output.err(`missing installer: ${name}`)
      break
    }
    case "Failure": {
      yield* output.err(`deps install failed in ${directory}: ${name} (${outcome.detail})`)
      break
    }
    case "TimedOut": {
      yield* output.err(`deps install timed out in ${directory}: ${name}`)
      break
    }
    case "OutputLimit": {
      yield* output.err(`deps install output limit exceeded in ${directory}: ${name}`)
      break
    }
  }
  return false
})

const ensureProject = Effect.fn("ExtensionDeps.ensureProject")(function* (target: string) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const output = yield* Output
  const manifest = path.join(target, "package.json")
  if (yield* fs.exists(manifest)) {
    return true
  }
  return yield* fs.writeFileString(manifest, emptyPackage).pipe(
    Effect.as(true),
    Effect.catch((error) => output.err(`write ${manifest} (${String(error)})`).pipe(Effect.as(false))),
  )
})

export const installInferredImportPackages = Effect.fn("ExtensionDeps.installInferredImportPackages")(
  function* (target: string, timeoutMs: number, source: string = target) {
    const fs = yield* FileSystem.FileSystem
    const path = yield* Path.Path
    const proc = yield* Proc
    const output = yield* Output
    const tree = yield* walk(source, true)
    const contents: string[] = []
    const sourceFiles = Arr.filter<string>((entry) => sourceExtension.test(entry))(tree.files)
    for (const file of sourceFiles) {
      const content = yield* fs.readFileString(file).pipe(
        Effect.map((value) => ({ value, error: null })),
        Effect.catch((error) => Effect.succeed({ value: null, error })),
      )
      if (content.value === null) {
        yield* output.err(`dependency scan failed in ${target}: read ${file} (${String(content.error)})`)
        return false
      }
      contents.push(content.value)
    }
    const candidates = missingPackageRoots(contents, () => false)
    const installed = new Set<string>()
    for (const root of candidates) {
      if (yield* fs.exists(path.join(source, "node_modules", root))) {
        installed.add(root)
      }
    }
    const missing = Arr.filter<string>((root) => !installed.has(root))(candidates)
    if (missing.length === 0) {
      return true
    }
    if (!(yield* ensureProject(target))) {
      return false
    }
    const bun = yield* proc.resolveExecutable("bun")
    if (Option.isNone(bun)) {
      yield* output.err(`bun is required for inferred imports in ${target}`)
      return false
    }
    const outcome = yield* proc.outcome([bun.value, "add", "--no-save", ...missing], target, timeoutMs)
    if (outcome._tag === "Success") {
      return true
    }
    const detail = outcome._tag === "Failure" || outcome._tag === "OutputLimit" ? `: ${outcome.detail}` : ""
    yield* output.err(`install inferred packages failed (${outcome._tag}${detail})`)
    return false
  },
)

export const installExtensionDeps = Effect.fn("ExtensionDeps.installExtensionDeps")(function* (
  root: string,
  sourceRoot: string,
  timeoutMs: number,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const proc = yield* Proc
  const output = yield* Output
  if (!(yield* proc.commandExists("bun"))) {
    yield* output.err("bun is required for extension dependency install")
    return false
  }
  let success = true
  for (const sourceDir of yield* iterExtensionPackages(sourceRoot)) {
    const directory = path.join(root, path.relative(sourceRoot, sourceDir))
    const manifest = yield* fs
      .stat(path.join(directory, "package.json"))
      .pipe(Effect.orElseSucceed(() => null))
    if (manifest?.type === "File" && !(yield* runInstall(["bun", "install"], directory, timeoutMs))) {
      success = false
    }
  }
  const inferred = yield* installInferredImportPackages(root, timeoutMs, sourceRoot)
  return success && inferred
})
