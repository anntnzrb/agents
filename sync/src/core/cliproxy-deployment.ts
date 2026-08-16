import fs from "node:fs";
import { isIPv6 } from "node:net";
import { hostname as currentHostname } from "node:os";
import { isErrno, panicMessage } from "@runtime/errors.ts";
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
    parsed = JSON.parse(fs.readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`parse CLIProxyAPI deployment ${path} (${panicMessage(error)})`, {
      cause: error,
    });
  }
  return parseCliProxyDeployment(parsed);
}

export function parseCliProxyDeployment(value: unknown): CliProxyDeployment {
  const root = expectRecord(value, "CLIProxyAPI deployment");
  rejectUnknownFields(root, ["server", "listen", "client"], "CLIProxyAPI deployment");

  const server = expectRecord(root["server"], "CLIProxyAPI deployment.server");
  rejectUnknownFields(server, ["hostname"], "CLIProxyAPI deployment.server");
  const serverHostname = requireServerHostname(server["hostname"]);

  const listen = expectRecord(root["listen"], "CLIProxyAPI deployment.listen");
  rejectUnknownFields(listen, ["host", "port"], "CLIProxyAPI deployment.listen");
  const host = requireListenHost(listen["host"]);
  const port = listen["port"];
  if (typeof port !== "number" || !Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error("invalid CLIProxyAPI deployment.listen.port: expected integer from 1 to 65535");
  }

  const client = expectRecord(root["client"], "CLIProxyAPI deployment.client");
  rejectUnknownFields(client, ["baseUrl"], "CLIProxyAPI deployment.client");
  const baseUrl = requireClientBaseUrl(client["baseUrl"]);

  return {
    server: { hostname: serverHostname },
    listen: { host, port },
    client: { baseUrl },
  };
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
  clientApiKeyPath: string,
  options: CliProxyEndpointSyncOptions = {},
): Promise<CliProxyEndpointPublication> {
  if (targets.length === 0) {
    return "published";
  }

  const clientApiKey = readClientApiKey(clientApiKeyPath);
  if (
    !options.skipReadiness &&
    (!clientApiKey || !(await isCliProxyTargetReady(deployment, clientApiKey, options)))
  ) {
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
  clientApiKey: string,
  options: CliProxyEndpointSyncOptions = {},
): Promise<boolean> {
  try {
    const response = await (options.fetch ?? fetch)(cliProxyModelsUrl(deployment), {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${clientApiKey}`,
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
    syncTextFile(dst, `${rendered}${readPreservedTopLevelTail(dst, preserveTopLevels)}`, mode);
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

function readPreservedTopLevelTail(path: string, topLevels: readonly string[]): string {
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

  let firstHeader = -1;
  for (const topLevel of topLevels) {
    const header = `[${topLevel}`;
    let offset = 0;
    for (const line of existing.split(NEWLINE_SPLIT_PATTERN)) {
      const trimmed = line.endsWith("\n")
        ? line.slice(0, -1).replace(TRAILING_CR_PATTERN, "")
        : line;
      if (
        trimmed.startsWith(header) &&
        (trimmed[header.length] === "." || trimmed[header.length] === "]")
      ) {
        firstHeader = firstHeader < 0 ? offset : Math.min(firstHeader, offset);
        break;
      }
      offset += line.length;
    }
  }
  if (firstHeader < 0) {
    return "";
  }
  const separatorStart =
    firstHeader >= 2 && existing.slice(firstHeader - 2, firstHeader) === "\r\n"
      ? firstHeader - 2
      : firstHeader >= 1 && existing[firstHeader - 1] === "\n"
        ? firstHeader - 1
        : firstHeader;
  return existing.slice(separatorStart);
}

function requireListenHost(value: unknown): string {
  const host = requireNonEmptyString(value, "CLIProxyAPI deployment.listen.host");
  if (
    host !== host.trim() ||
    INVALID_LISTEN_HOST_PATTERN.test(host) ||
    host.includes("://") ||
    host.includes("[") ||
    host.includes("]") ||
    isUnspecifiedIpv4(host) ||
    isUnspecifiedIpv6(host)
  ) {
    throw new Error(
      "invalid CLIProxyAPI deployment.listen.host: expected a specific host or interface address",
    );
  }
  return host;
}

function requireServerHostname(value: unknown): string {
  const hostname = requireNonEmptyString(value, "CLIProxyAPI deployment.server.hostname");
  if (hostname !== hostname.trim() || INVALID_SERVER_HOSTNAME_PATTERN.test(hostname)) {
    throw new Error("invalid CLIProxyAPI deployment.server.hostname: expected a local OS hostname");
  }
  return hostname;
}

function isUnspecifiedIpv4(host: string): boolean {
  return IPV4_ZERO_PATTERN.test(host);
}

function requireClientBaseUrl(value: unknown): string {
  const raw = requireNonEmptyString(value, "CLIProxyAPI deployment.client.baseUrl");
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch (error) {
    throw new Error("invalid CLIProxyAPI deployment.client.baseUrl: expected URL", {
      cause: error,
    });
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
    throw new Error(
      "invalid CLIProxyAPI deployment.client.baseUrl: expected an HTTP(S) /v1 endpoint without credentials, query, or fragment",
    );
  }
  return raw.replace(TRAILING_SLASH_PATTERN, "");
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

export function readClientApiKey(path: string): string | undefined {
  try {
    const key = fs.readFileSync(path, "utf8").trim();
    return key.length > 0 ? key : undefined;
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return undefined;
    }
    throw new Error(`read CLIProxyAPI client key ${path} (${panicMessage(error)})`, {
      cause: error,
    });
  }
}

export function readCliProxyCandidateClientApiKey(path: string): string | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(fs.readFileSync(path, "utf8"));
  } catch {
    return undefined;
  }
  if (!isRecord(parsed) || !Array.isArray(parsed["CLIPROXY_CLIENT_API_KEYS"])) {
    return undefined;
  }
  const first = parsed["CLIPROXY_CLIENT_API_KEYS"][0];
  return typeof first === "string" && first.length > 0 ? first : undefined;
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

function requireNonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`invalid ${label}: expected non-empty string`);
  }
  return value;
}
