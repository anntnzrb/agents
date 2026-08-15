import { accessSync, constants, existsSync } from "node:fs";
import path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";

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

const isRunnable = (candidate: string): boolean => {
  if (!existsSync(candidate)) return false;
  if (process.platform === "win32") return true;
  try {
    accessSync(candidate, constants.X_OK);
    return true;
  } catch {
    return false;
  }
};

export const resolveSearchBinary = (name: "fd" | "rg"): string | undefined => {
  for (const candidate of [
    ...managedCandidates(name),
    ...pathCandidates(name),
  ]) {
    if (isRunnable(candidate)) return candidate;
  }
  return undefined;
};
