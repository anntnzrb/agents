import fs from "node:fs";
import { basename, dirname, join } from "node:path";
import { isErrno, panicMessage } from "@runtime/errors.ts";

const PLACEHOLDER_PATTERN = /\$\{([^{}]+)\}/g;
const SECRET_NAME_PATTERN = /^[A-Z][A-Z0-9_]*$/;
const OUTPUT_MODE = 0o600;

export function syncSecretTemplate(src: string, dst: string, secretsPath: string): void {
  const template = readText(src, "template");
  const secrets = readSecrets(secretsPath);
  const content = renderSecretTemplate(template, secrets);

  if (matchesOutput(dst, content)) {
    return;
  }

  fs.mkdirSync(dirname(dst), { recursive: true });
  const { fd, tempPath } = createTempFile(dst);
  try {
    fs.writeFileSync(fd, content, "utf8");
    fs.fchmodSync(fd, OUTPUT_MODE);
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fs.renameSync(tempPath, dst);
  } catch (error) {
    try {
      fs.closeSync(fd);
    } catch {
      // Already closed.
    }
    fs.rmSync(tempPath, { force: true });
    throw new Error(`render secret template ${src} -> ${dst} (${panicMessage(error)})`, {
      cause: error,
    });
  }
}

export function renderSecretTemplate(
  template: string,
  secrets: Readonly<Record<string, string>>,
): string {
  return template.replaceAll(PLACEHOLDER_PATTERN, (_placeholder, rawName: string) => {
    if (!SECRET_NAME_PATTERN.test(rawName)) {
      throw new Error(`invalid secret placeholder: ${rawName}`);
    }
    const value = secrets[rawName];
    if (typeof value !== "string" || value.length === 0) {
      throw new Error(`missing secret: ${rawName}`);
    }
    return JSON.stringify(value);
  });
}

function readSecrets(path: string): Readonly<Record<string, string>> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(readText(path, "secrets"));
  } catch (error) {
    throw new Error(`parse secrets ${path} (${panicMessage(error)})`, { cause: error });
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(`invalid secrets file: ${path} (expected object)`);
  }

  const secrets: Record<string, string> = {};
  for (const [name, value] of Object.entries(parsed)) {
    if (!SECRET_NAME_PATTERN.test(name) || typeof value !== "string" || value.length === 0) {
      throw new Error(`invalid secret entry: ${name}`);
    }
    secrets[name] = value;
  }
  return secrets;
}

function readText(path: string, label: string): string {
  try {
    return fs.readFileSync(path, "utf8");
  } catch (error) {
    throw new Error(`read ${label} ${path} (${panicMessage(error)})`, { cause: error });
  }
}

function matchesOutput(path: string, content: string): boolean {
  try {
    const metadata = fs.lstatSync(path);
    return (
      metadata.isFile() &&
      !metadata.isSymbolicLink() &&
      (metadata.mode & 0o777) === OUTPUT_MODE &&
      fs.readFileSync(path, "utf8") === content
    );
  } catch {
    return false;
  }
}

function createTempFile(path: string): { readonly fd: number; readonly tempPath: string } {
  const nonce = Date.now().toString(16);
  for (let attempt = 0; attempt < 16; attempt += 1) {
    const tempPath = join(
      dirname(path),
      `.${basename(path) || "config"}.${process.pid}.${nonce}-${attempt}.tmp`,
    );
    try {
      return { fd: fs.openSync(tempPath, "wx", OUTPUT_MODE), tempPath };
    } catch (error) {
      if (!isErrno(error, "EEXIST")) {
        throw error;
      }
    }
  }
  throw new Error(`create temporary config near ${path} (name collision)`);
}
