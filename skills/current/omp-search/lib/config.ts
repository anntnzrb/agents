import { Effect, FileSystem, Path } from "effect";

export function extractYamlList(text: string, targetKey: string): string[] {
  const lines = text.split("\n");
  let inSection = false;
  let inKey = false;
  const items: string[] = [];

  for (const line of lines) {
    const stripped = line.trim();
    if (!stripped || stripped.startsWith("#")) {
      continue;
    }
    const indent = line.length - line.trimStart().length;
    if (indent === 0) {
      inSection = false;
      inKey = false;
      if (stripped.startsWith("providers:")) {
        inSection = true;
      }
      continue;
    }
    if (!inSection) {
      continue;
    }
    if (indent <= 2 && !stripped.startsWith("-")) {
      inKey = stripped.startsWith(`${targetKey}:`);
      continue;
    }
    if (inKey) {
      if (stripped.startsWith("-")) {
        const item = stripped.slice(1).trim();
        const cleanedItem = item.replace(/#.*$/, "").trim().replace(/^['"]|['"]$/g, "");
        if (cleanedItem) {
          items.push(cleanedItem);
        }
      } else if (indent <= 2 && !stripped.startsWith("-")) {
        inKey = false;
      }
    }
  }

  return items;
}

export function discoverActiveOmpProviders(
  cwd?: string
): Effect.Effect<readonly string[], never, FileSystem.FileSystem | Path.Path> {
  return Effect.gen(function* () {
    const fs = yield* FileSystem.FileSystem;
    const path = yield* Path.Path;

    const effectiveCwd = cwd ?? process.cwd();
    const home = process.env["HOME"] || process.env["USERPROFILE"] || "";

    const candidates: string[] = [];
    const ompConfigDir = process.env["OMP_CONFIG_DIR"];
    if (ompConfigDir) {
      candidates.push(path.join(ompConfigDir, "config.yml"));
    }
    if (home) {
      candidates.push(path.join(home, ".omp", "agent", "config.yml"));
    }
    candidates.push(path.join(effectiveCwd, ".omp", "agent", "config.yml"));
    candidates.push(path.join(effectiveCwd, "harnesses", "omp", "agent", "config.yml"));
    if (home) {
      candidates.push(path.join(home, ".omp", "config.yml"));
    }
    candidates.push(path.join(effectiveCwd, ".omp", "config.yml"));

    for (const filePath of candidates) {
      const exists = yield* fs.exists(filePath).pipe(Effect.orElseSucceed(() => false));
      if (exists) {
        const content = yield* fs.readFileString(filePath, "utf-8").pipe(Effect.orElseSucceed(() => ""));
        if (content) {
          const order = extractYamlList(content, "webSearchOrder");
          const exclude = new Set(extractYamlList(content, "webSearchExclude"));
          const active = order.filter((p) => !exclude.has(p));
          if (active.length > 0) {
            return active;
          }
        }
      }
    }

    return [];
  });
}
