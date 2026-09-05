import fs from "node:fs";
import { isIPv6 } from "node:net";
import { hostname as currentHostname } from "node:os";
import { isErrno, panicMessage } from "@runtime/errors.ts";
import { Schema } from "effect";
import { syncTextFile } from "./secret-template.ts";

const INVALID_LISTEN_HOST_PATTERN = /[\s/?#@]/;
const INVALID_SERVER_HOSTNAME_PATTERN = /[\s/?#@:]/;
const INVALID_CLIENT_URL_DELIMITER_PATTERN = /[?#]/;
const IPV4_ZERO_PATTERN = /^(?:0+(?:\.0+){0,3}|0x0+)$/i;
const IPV4_PART_PATTERN = /^\d{1,3}$/;
const ZERO_IPV6_GROUP_PATTERN = /^0{1,4}$/i;
const TRAILING_SLASH_PATTERN = /\/+$/;
const NEWLINE_SPLIT_PATTERN = /(?<=\n)/;
const TRAILING_CR_PATTERN = /\r$/;
const CLIENT_BASE_URL_PLACEHOLDER_NAME = "CLIPROXY_CLIENT_BASE_URL";
export const CLI_PROXY_SOURCE_DIR = "tools/cliproxyapi";
export const CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER = `\${${CLIENT_BASE_URL_PLACEHOLDER_NAME}}`;

const ENDPOINT_READY_TIMEOUT_MS = 500;

export interface CliProxyDeployment {
  readonly server: {
    readonly hostname: string;
  };
  readonly listen: {
    readonly host: string;
    readonly port: number;
  };
  readonly client: {
    readonly baseUrl: string;
  };
}

export interface CliProxyEndpointTarget {
  readonly src: string;
  readonly dst: string;
  readonly preserveTopLevels?: readonly string[];
}

export interface CliProxyEndpointSyncOptions {
  readonly fetch?: EndpointFetch;
  readonly timeoutMs?: number;
  readonly skipReadiness?: boolean;
}

export type EndpointFetch = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export type CliProxyEndpointPublication = "published" | "skipped";

export function readCliProxyDeployment(path: string): CliProxyDeployment {
  let parsed: unknown;
  try {
    parsed = Bun.JSONC.parse(fs.readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`parse CLIProxyAPI deployment ${path} (${panicMessage(error)})`, {
      cause: error,
    });
  }
  return parseCliProxyDeployment(parsed);
}

const ServerHostnameSchema = Schema.NonEmptyString.pipe(
  Schema.check(
    Schema.makeFilter((h: string) =>
      h === h.trim() && !INVALID_SERVER_HOSTNAME_PATTERN.test(h)
        ? undefined
        : "expected a local OS hostname",
    ),
  ),
);

const ListenHostSchema = Schema.NonEmptyString.pipe(
  Schema.check(
    Schema.makeFilter((host: string) =>
      host === host.trim() &&
      !INVALID_LISTEN_HOST_PATTERN.test(host) &&
      !host.includes("://") &&
      !host.includes("[") &&
      !host.includes("]") &&
      !isUnspecifiedIpv4(host) &&
      !isUnspecifiedIpv6(host)
        ? undefined
        : "expected a specific host or interface address",
    ),
  ),
);

const ListenPortSchema = Schema.Int.pipe(
  Schema.check(
    Schema.makeFilter((p: number) =>
      p >= 1 && p <= 65535 ? undefined : "expected integer from 1 to 65535",
    ),
  ),
);

const ClientBaseUrlSchema = Schema.NonEmptyString.pipe(
  Schema.check(
    Schema.makeFilter((raw: string) => {
      let parsed: URL;
      try {
        parsed = new URL(raw);
      } catch {
        return "expected URL";
      }
      if (
        raw !== raw.trim() ||
        INVALID_CLIENT_URL_DELIMITER_PATTERN.test(raw) ||
        (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
        parsed.username ||
        parsed.password ||
        parsed.search ||
        parsed.hash ||
        !parsed.hostname ||
        parsed.pathname.replace(TRAILING_SLASH_PATTERN, "") !== "/v1"
      ) {
        return "expected an HTTP(S) /v1 endpoint without credentials, query, or fragment";
      }
      return undefined;
    }),
  ),
);

export const CliProxyDeploymentSchema = Schema.Struct({
  server: Schema.Struct({
    hostname: ServerHostnameSchema,
  }),
  listen: Schema.Struct({
    host: ListenHostSchema,
    port: ListenPortSchema,
  }),
  client: Schema.Struct({
    baseUrl: ClientBaseUrlSchema,
  }),
});

export function parseCliProxyDeployment(value: unknown): CliProxyDeployment {
  const root = expectRecord(value, "CLIProxyAPI deployment");
  rejectUnknownFields(root, ["server", "listen", "client"], "CLIProxyAPI deployment");

  const server = expectRecord(root["server"], "CLIProxyAPI deployment.server");
  rejectUnknownFields(server, ["hostname"], "CLIProxyAPI deployment.server");

  const listen = expectRecord(root["listen"], "CLIProxyAPI deployment.listen");
  rejectUnknownFields(listen, ["host", "port"], "CLIProxyAPI deployment.listen");

  const client = expectRecord(root["client"], "CLIProxyAPI deployment.client");
  rejectUnknownFields(client, ["baseUrl"], "CLIProxyAPI deployment.client");

  try {
    const decoded = Schema.decodeUnknownSync(CliProxyDeploymentSchema)(value);
    return {
      server: { hostname: decoded.server.hostname },
      listen: { host: decoded.listen.host, port: decoded.listen.port },
      client: { baseUrl: decoded.client.baseUrl.replace(TRAILING_SLASH_PATTERN, "") },
    };
  } catch (error) {
    throw new Error(`invalid CLIProxyAPI deployment (${panicMessage(error)})`, { cause: error });
  }
}

export function isCliProxyGatewayHost(
  deployment: CliProxyDeployment,
  hostname = currentHostname(),
): boolean {
  return hostname.trim().toLowerCase() === deployment.server.hostname.toLowerCase();
}

export function cliProxyModelsUrl(deployment: CliProxyDeployment): string {
  return `${deployment.client.baseUrl.replace(TRAILING_SLASH_PATTERN, "")}/models`;
}

export async function publishCliProxyEndpointTemplates(
  targets: readonly CliProxyEndpointTarget[],
  deployment: CliProxyDeployment,
  options: CliProxyEndpointSyncOptions = {},
): Promise<CliProxyEndpointPublication> {
  if (targets.length === 0) {
    return "published";
  }

  if (!options.skipReadiness && !(await isCliProxyTargetReady(deployment, options))) {
    return "skipped";
  }

  const snapshots = targets.map((target) => snapshotEndpointTarget(target.dst));
  try {
    for (const target of targets) {
      syncCliProxyEndpointTemplate(
        target.src,
        target.dst,
        deployment,
        target.preserveTopLevels ?? [],
      );
    }
  } catch (error) {
    restoreEndpointTargets(snapshots);
    throw error;
  }
  return "published";
}

export async function isCliProxyTargetReady(
  deployment: CliProxyDeployment,
  options: CliProxyEndpointSyncOptions = {},
): Promise<boolean> {
  try {
    const response = await (options.fetch ?? fetch)(cliProxyModelsUrl(deployment), {
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-cache",
      },
      cache: "no-store",
      signal: AbortSignal.timeout(options.timeoutMs ?? ENDPOINT_READY_TIMEOUT_MS),
    });
    if (!response.ok) {
      return false;
    }
    const payload: unknown = await response.json();
    return isRecord(payload) && Array.isArray(payload["data"]) && payload["data"].length > 0;
  } catch {
    return false;
  }
}

export function renderCliProxyEndpointTemplate(
  template: string,
  deployment: CliProxyDeployment,
): string {
  if (!template.includes(CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER)) {
    throw new Error(
      `missing CLIProxyAPI endpoint placeholder: ${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}`,
    );
  }
  return template.replaceAll(CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER, deployment.client.baseUrl);
}

export function syncCliProxyEndpointTemplate(
  src: string,
  dst: string,
  deployment: CliProxyDeployment,
  preserveTopLevels: readonly string[] = [],
): void {
  let template: string;
  let mode: number;
  try {
    template = fs.readFileSync(src, "utf8");
    mode = existingFileMode(dst) ?? fs.statSync(src).mode & 0o777;
  } catch (error) {
    throw new Error(`read CLIProxyAPI endpoint template ${src} (${panicMessage(error)})`, {
      cause: error,
    });
  }
  try {
    const rendered = renderCliProxyEndpointTemplate(template, deployment);
    const preserved = readPreservedTopLevels(dst, preserveTopLevels);
    syncTextFile(dst, appendPreservedSections(rendered, preserved), mode);
  } catch (error) {
    throw new Error(
      `render CLIProxyAPI endpoint template ${src} -> ${dst} (${panicMessage(error)})`,
      {
        cause: error,
      },
    );
  }
}

function existingFileMode(path: string): number | undefined {
  try {
    const metadata = fs.lstatSync(path);
    return metadata.isFile() && !metadata.isSymbolicLink() ? metadata.mode & 0o777 : undefined;
  } catch {
    return undefined;
  }
}

export function readPreservedTopLevels(path: string, topLevels: readonly string[]): string {
  if (topLevels.length === 0) {
    return "";
  }
  let existing: string;
  try {
    existing = fs.readFileSync(path, "utf8");
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return "";
    }
    throw error;
  }
  return extractPreservedTopLevels(existing, topLevels);
}

export function extractPreservedTopLevels(existing: string, topLevels: readonly string[]): string {
  if (topLevels.length === 0) {
    return "";
  }
  const parsedTopLevels = topLevels
    .map((tl) => parseTomlKeyPath(tl))
    .filter((segments): segments is string[] => segments !== null && segments.length > 0);
  if (parsedTopLevels.length === 0) {
    return "";
  }

  const lines = existing.split(NEWLINE_SPLIT_PATTERN);
  interface TomlSection {
    headerSegments: string[] | null;
    lines: string[];
  }
  const sections: TomlSection[] = [];
  let currentSection: TomlSection = { headerSegments: null, lines: [] };

  for (const line of lines) {
    const header = parseTomlTableHeader(line);
    if (header !== null) {
      if (currentSection.headerSegments !== null || currentSection.lines.length > 0) {
        sections.push(currentSection);
      }
      currentSection = { headerSegments: header, lines: [line] };
    } else {
      currentSection.lines.push(line);
    }
  }
  if (currentSection.headerSegments !== null || currentSection.lines.length > 0) {
    sections.push(currentSection);
  }

  const preservedSections = sections.filter((section) => {
    if (section.headerSegments === null) {
      return false;
    }
    return parsedTopLevels.some(
      (topLevelSegments) =>
        section.headerSegments !== null &&
        section.headerSegments.length >= topLevelSegments.length &&
        topLevelSegments.every((seg, idx) => seg === section.headerSegments?.[idx]),
    );
  });

  if (preservedSections.length === 0) {
    return "";
  }

  return `${preservedSections.map((section) => section.lines.join("").trimEnd()).join("\n\n")}\n`;
}

export function appendPreservedSections(rendered: string, preserved: string): string {
  if (preserved.length === 0) {
    return rendered;
  }
  if (rendered.length === 0) {
    return preserved;
  }
  if (rendered.endsWith("\n\n")) {
    return `${rendered}${preserved}`;
  }
  if (rendered.endsWith("\n")) {
    return `${rendered}\n${preserved}`;
  }
  return `${rendered}\n\n${preserved}`;
}

function parseTomlKeyPath(raw: string): string[] | null {
  const segments: string[] = [];
  let i = 0;
  const len = raw.length;

  while (i < len) {
    while (i < len && (raw[i] === " " || raw[i] === "\t")) {
      i++;
    }
    if (i >= len) {
      break;
    }

    const char = raw[i];
    if (char === '"') {
      i++;
      let value = "";
      let closed = false;
      while (i < len) {
        const c = raw[i];
        if (c === "\\") {
          i++;
          if (i >= len) {
            return null;
          }
          const esc = raw[i];
          if (esc === '"' || esc === "\\") {
            value += esc;
          } else if (esc === "n") {
            value += "\n";
          } else if (esc === "t") {
            value += "\t";
          } else if (esc === "r") {
            value += "\r";
          } else {
            value += esc;
          }
          i++;
        } else if (c === '"') {
          closed = true;
          i++;
          break;
        } else {
          value += c;
          i++;
        }
      }
      if (!closed) {
        return null;
      }
      segments.push(value);
    } else if (char === "'") {
      i++;
      let value = "";
      let closed = false;
      while (i < len) {
        const c = raw[i];
        if (c === "'") {
          closed = true;
          i++;
          break;
        }
        value += c;
        i++;
      }
      if (!closed) {
        return null;
      }
      segments.push(value);
    } else {
      let key = "";
      while (i < len) {
        const c = raw[i];
        if (
          c === "." ||
          c === "]" ||
          c === "[" ||
          c === " " ||
          c === "\t" ||
          c === "#" ||
          c === "\r" ||
          c === "\n" ||
          c === "="
        ) {
          break;
        }
        key += c;
        i++;
      }
      if (key.length === 0) {
        return null;
      }
      segments.push(key);
    }

    while (i < len && (raw[i] === " " || raw[i] === "\t")) {
      i++;
    }
    if (i < len && raw[i] === ".") {
      i++;
      while (i < len && (raw[i] === " " || raw[i] === "\t")) {
        i++;
      }
      if (i >= len) {
        return null;
      }
    } else {
      break;
    }
  }

  while (i < len && (raw[i] === " " || raw[i] === "\t")) {
    i++;
  }
  if (i < len) {
    return null;
  }

  return segments.length > 0 ? segments : null;
}

function parseTomlTableHeader(line: string): string[] | null {
  const trimmed = line.endsWith("\n")
    ? line.slice(0, -1).replace(TRAILING_CR_PATTERN, "").trim()
    : line.trim();

  if (!trimmed.startsWith("[")) {
    return null;
  }

  const isArray = trimmed.startsWith("[[");
  const openBracketCount = isArray ? 2 : 1;

  let i = openBracketCount;
  const len = trimmed.length;
  let inDoubleQuote = false;
  let inSingleQuote = false;
  let closeBracketIndex = -1;

  while (i < len) {
    const c = trimmed[i];
    if (inDoubleQuote) {
      if (c === "\\") {
        i += 2;
        continue;
      }
      if (c === '"') {
        inDoubleQuote = false;
      }
      i++;
      continue;
    }
    if (inSingleQuote) {
      if (c === "'") {
        inSingleQuote = false;
      }
      i++;
      continue;
    }

    if (c === '"') {
      inDoubleQuote = true;
      i++;
      continue;
    }
    if (c === "'") {
      inSingleQuote = true;
      i++;
      continue;
    }

    if (isArray) {
      if (c === "]" && i + 1 < len && trimmed[i + 1] === "]") {
        closeBracketIndex = i;
        break;
      }
    } else {
      if (c === "]") {
        closeBracketIndex = i;
        break;
      }
    }
    i++;
  }

  if (closeBracketIndex === -1) {
    return null;
  }

  const rest = trimmed.slice(closeBracketIndex + openBracketCount).trim();
  if (rest.length > 0 && !rest.startsWith("#")) {
    return null;
  }

  const inner = trimmed.slice(openBracketCount, closeBracketIndex);
  return parseTomlKeyPath(inner);
}

function isUnspecifiedIpv4(host: string): boolean {
  return IPV4_ZERO_PATTERN.test(host);
}

function isUnspecifiedIpv6(host: string): boolean {
  const address = host.split("%")[0] ?? host;
  if (!isIPv6(address)) {
    return false;
  }

  const groups = address.includes(".") ? ipv4TailGroups(address) : address.split(":");
  if (!groups) {
    return false;
  }
  const compression = address.indexOf("::");
  if (compression >= 0) {
    if (address.indexOf("::", compression + 2) >= 0) {
      return false;
    }
    const explicit = groups.filter((group) => group.length > 0);
    return explicit.every(isZeroIpv6Group) && explicit.length < 8;
  }
  return groups.length === 8 && groups.every(isZeroIpv6Group);
}

function ipv4TailGroups(address: string): string[] | undefined {
  const separator = address.lastIndexOf(":");
  if (separator < 0) {
    return undefined;
  }
  const ipv4 = address.slice(separator + 1).split(".");
  if (ipv4.length !== 4 || ipv4.some((part) => !IPV4_PART_PATTERN.test(part))) {
    return undefined;
  }
  const bytes = ipv4.map(Number);
  if (bytes.some((byte) => byte > 255)) {
    return undefined;
  }
  const [first, second, third, fourth] = bytes;
  if (first === undefined || second === undefined || third === undefined || fourth === undefined) {
    return undefined;
  }
  const tail = `${((first << 8) | second).toString(16)}:${((third << 8) | fourth).toString(16)}`;
  return [...address.slice(0, separator).split(":"), ...tail.split(":")];
}

function isZeroIpv6Group(group: string): boolean {
  return ZERO_IPV6_GROUP_PATTERN.test(group);
}

interface EndpointTargetSnapshot {
  readonly path: string;
  readonly kind: "missing" | "file" | "symlink" | "other";
  readonly content?: string;
  readonly mode?: number;
  readonly link?: string;
}

function snapshotEndpointTarget(path: string): EndpointTargetSnapshot {
  try {
    const metadata = fs.lstatSync(path);
    if (metadata.isSymbolicLink()) {
      return { path, kind: "symlink", link: fs.readlinkSync(path) };
    }
    if (!metadata.isFile()) {
      return { path, kind: "other" };
    }
    return {
      path,
      kind: "file",
      content: fs.readFileSync(path, "utf8"),
      mode: metadata.mode & 0o777,
    };
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return { path, kind: "missing" };
    }
    throw error;
  }
}

function restoreEndpointTargets(snapshots: readonly EndpointTargetSnapshot[]): void {
  for (const snapshot of snapshots) {
    switch (snapshot.kind) {
      case "missing":
        fs.rmSync(snapshot.path, { force: true });
        break;
      case "file":
        syncTextFile(snapshot.path, snapshot.content ?? "", snapshot.mode ?? 0o644);
        break;
      case "symlink":
        if (snapshot.link === undefined) {
          throw new Error(`missing endpoint symlink target: ${snapshot.path}`);
        }
        fs.rmSync(snapshot.path, { force: true });
        fs.symlinkSync(snapshot.link, snapshot.path);
        break;
      case "other":
        break;
      default:
        assertNeverSnapshot(snapshot.kind);
    }
  }
}

function assertNeverSnapshot(value: never): never {
  throw new Error(`unknown endpoint target snapshot: ${String(value)}`);
}

function expectRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`invalid ${label}: expected object`);
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function rejectUnknownFields(
  record: Readonly<Record<string, unknown>>,
  allowedFields: readonly string[],
  label: string,
): void {
  const allowed = new Set(allowedFields);
  for (const field of Object.keys(record)) {
    if (!allowed.has(field)) {
      throw new Error(`invalid ${label}: unknown field ${field}`);
    }
  }
}
