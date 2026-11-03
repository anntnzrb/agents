import { Array as Arr, String as Str } from "effect"

/** Join and normalize POSIX path segments without consulting the filesystem. */
export const joinPath = (...segments: readonly string[]): string => {
  const parts: string[] = []
  let absolute = false
  for (const segment of segments) {
    if (segment === "") {
      continue
    }
    if (parts.length === 0 && Str.startsWith("/")(segment)) {
      absolute = true
    }
    for (const part of Str.split("/")(segment)) {
      if (part === "" || part === ".") {
        continue
      }
      if (part === ".." && parts.length > 0 && parts.at(-1) !== "..") {
        parts.pop()
      } else if (part !== ".." || !absolute) {
        parts.push(part)
      }
    }
  }
  const joined = Arr.join("/")(parts)
  return absolute ? `/${joined}` : joined === "" ? "." : joined
}
