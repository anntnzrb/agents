import { access, constants, stat } from "node:fs/promises";
import path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { Effect, Schema } from "effect";

export class SearchBinaryNotFoundError extends Schema.TaggedError<SearchBinaryNotFoundError>()(
  "SearchBinaryNotFoundError",
  {
    name: Schema.String,
    candidates: Schema.Array(Schema.String),
  },
) {
  override get message(): string {
    return `Unable to find executable for '${this.name}'`;
  }
}

const pathKey = (): string =>
  Object.keys(process.env).find((key) => key.toLowerCase() === "path") ??
  "PATH";

const executableNames = (name: string): string[] => {
  if (process.platform !== "win32") return [name];
  const lower = name.toLowerCase();
  const hasExecutableExtension = [".exe", ".cmd", ".bat", ".com"].some((ext) =>
    lower.endsWith(ext),
  );
  if (hasExecutableExtension) return [name];
  const pathext = process.env["PATHEXT"] ?? ".COM;.EXE;.BAT;.CMD";
  return pathext
    .split(";")
    .map((ext) => ext.trim())
    .filter(Boolean)
    .map((ext) => `${name}${ext.startsWith(".") ? ext : `.${ext}`}`);
};

const pathCandidates = (name: string): string[] => {
  const envPath = process.env[pathKey()] ?? "";
  const dirs = envPath.split(path.delimiter).filter(Boolean);
  return dirs.flatMap((dir) =>
    executableNames(name).map((candidate) => path.join(dir, candidate)),
  );
};

const managedCandidates = (name: string): string[] =>
  executableNames(name).map((candidate) =>
    path.join(getAgentDir(), "bin", candidate),
  );

const isRunnableEffect = Effect.fn("isRunnable")(function*(
  candidate: string,
): Effect.fn.Return<boolean> {
    const fileStat = yield* Effect.tryPromise({
      try: () => stat(candidate),
      catch: () => undefined,
    }).pipe(Effect.orElseSucceed(() => undefined));

    if (!fileStat) return false;
    if (process.platform === "win32") return true;

    return yield* Effect.tryPromise({
      try: () => access(candidate, constants.X_OK),
      catch: () => undefined,
    }).pipe(
      Effect.map(() => true),
      Effect.orElseSucceed(() => false),
    );
});

export const resolveSearchBinaryEffect = Effect.fn("resolveSearchBinary")(function*(
  name: "fd" | "rg",
): Effect.fn.Return<string, SearchBinaryNotFoundError> {
  const candidates = [...managedCandidates(name), ...pathCandidates(name)];
  for (const candidate of candidates) {
    const runnable = yield* isRunnableEffect(candidate);
    if (runnable) return candidate;
  }
  return yield* new SearchBinaryNotFoundError({ name, candidates });
});

export const resolveSearchBinary = (name: "fd" | "rg"): Promise<string | undefined> =>
  Effect.runPromise(
    resolveSearchBinaryEffect(name).pipe(
      Effect.orElseSucceed(() => undefined),
    ),
  );
