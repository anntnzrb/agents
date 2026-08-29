import { accessSync, constants } from "node:fs";
import { stat } from "node:fs/promises";
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
  const envKey =
    Object.keys(process.env).find((key) => key.toLowerCase() === "path") ??
    "PATH";
  const envPath = process.env[envKey] ?? "";
  const dirs = envPath.split(path.delimiter).filter(Boolean);
  return dirs.flatMap((dir) =>
    executableNames(name).map((candidate) => path.join(dir, candidate)),
  );
};

const isRunnableEffect = Effect.fn("isRunnable")(function*(
  candidate: string,
): Effect.fn.Return<boolean> {
    const fileStat = yield* Effect.tryPromise({
      try: () => stat(candidate),
      catch: () => undefined,
    }).pipe(Effect.orElseSucceed(() => undefined));

    if (!fileStat) return false;
    if (process.platform === "win32") return true;

    try {
      accessSync(candidate, constants.X_OK);
      return true;
    } catch {
      return false;
    }
});
export const resolveSearchBinaryEffect = Effect.fn("resolveSearchBinary")(function*(
  name: "fd" | "rg",
): Effect.fn.Return<string, SearchBinaryNotFoundError> {
  const managedCandidates = executableNames(name).map((candidate) =>
    path.join(getAgentDir(), "bin", candidate),
  );
  const candidates = [...managedCandidates, ...pathCandidates(name)];
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
