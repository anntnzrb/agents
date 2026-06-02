import path from "node:path";

export const toPosixPath = (value: string): string => value.replace(/\\/g, "/");

export const compactDisplayPath = (value: string, keepSegments = 4): string => {
  if (value === "." || value.startsWith("paths:")) return value;
  const normalized = toPosixPath(value);
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= keepSegments) return value;
  return `…/${parts.slice(-keepSegments).join("/")}`;
};

export const relativePosixPath = (
  cwd: string,
  absolutePath: string,
): string => {
  const relativeToCwd = path.relative(cwd, absolutePath);
  return toPosixPath(
    relativeToCwd.length === 0 ? path.basename(absolutePath) : relativeToCwd,
  );
};
