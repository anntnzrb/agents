import fs from "node:fs";
import { panicMessage } from "@runtime/errors.ts";
import { syncPrivateTextFile } from "./secret-template.ts";

const PLACEHOLDER_PATTERN = /^\$\{([A-Z][A-Z0-9_]*)\}$/;
const POOL_NAME_PATTERN = /^[a-z][a-z0-9-]*$/;
const BCRYPT_HASH_PATTERN = /^\$2[aby]\$\d{2}\$/;
const POOL_MARKER = "x-credential-pool";
const MAX_CREDENTIAL_WEIGHT = 1_000_000;
const NATIVE_CREDENTIAL_SECTIONS = [
  "claude-api-key",
  "codex-api-key",
  "gemini-api-key",
  "interactions-api-key",
  "vertex-api-key",
  "xai-api-key",
] as const;

interface Credential {
  readonly apiKey: string;
  readonly weight?: number;
  readonly proxyUrl?: string;
}

interface CliProxySecrets {
  readonly CLIPROXY_MANAGEMENT_KEY: string;
  readonly CLIPROXY_CLIENT_API_KEYS: readonly string[];
  readonly CLIPROXY_CREDENTIAL_POOLS: Readonly<Record<string, readonly Credential[]>>;
}

type ConfigRecord = Record<string, unknown>;

export function syncCliProxyConfig(src: string, dst: string, secretsPath: string): void {
  const template = readText(src, "CLIProxyAPI template");
  const secrets = readCliProxySecrets(secretsPath);
  const managementKey = reusableManagementKey(dst, secrets.CLIPROXY_MANAGEMENT_KEY);
  const content = renderCliProxyConfig(template, secrets, managementKey);
  try {
    syncPrivateTextFile(dst, content);
  } catch (error) {
    throw new Error(`render CLIProxyAPI config ${src} -> ${dst} (${panicMessage(error)})`, {
      cause: error,
    });
  }
}

export function renderCliProxyConfig(
  template: string,
  secrets: CliProxySecrets,
  managementKey = secrets.CLIPROXY_MANAGEMENT_KEY,
): string {
  let parsed: unknown;
  try {
    parsed = Bun.YAML.parse(template);
  } catch (error) {
    throw new Error(`parse CLIProxyAPI template (${panicMessage(error)})`, { cause: error });
  }

  const config = expectRecord(
    resolvePlaceholders(parsed, secrets, managementKey),
    "CLIProxyAPI template root",
  );
  const referencedPools = new Set<string>();

  for (const sectionName of NATIVE_CREDENTIAL_SECTIONS) {
    const section = config[sectionName];
    if (section === undefined) {
      continue;
    }
    config[sectionName] = expandNativeCredentialSection(
      sectionName,
      section,
      secrets.CLIPROXY_CREDENTIAL_POOLS,
      referencedPools,
    );
  }

  const compatibility = config["openai-compatibility"];
  if (compatibility !== undefined) {
    config["openai-compatibility"] = expandCompatibilitySection(
      compatibility,
      secrets.CLIPROXY_CREDENTIAL_POOLS,
      referencedPools,
    );
  }

  const unreferencedPools = Object.keys(secrets.CLIPROXY_CREDENTIAL_POOLS).filter(
    (name) => !referencedPools.has(name),
  );
  if (unreferencedPools.length > 0) {
    throw new Error(`unreferenced CLIProxyAPI credential pool: ${unreferencedPools.join(", ")}`);
  }

  const content = Bun.YAML.stringify(config, null, 2);
  Bun.YAML.parse(content);
  return content.endsWith("\n") ? content : `${content}\n`;
}

function resolvePlaceholders(
  value: unknown,
  secrets: CliProxySecrets,
  managementKey: string,
): unknown {
  if (typeof value === "string") {
    const match = PLACEHOLDER_PATTERN.exec(value);
    if (!match) {
      return value;
    }
    const name = match[1];
    if (name === undefined) {
      return value;
    }
    switch (name) {
      case "CLIPROXY_MANAGEMENT_KEY":
        return managementKey;
      case "CLIPROXY_CLIENT_API_KEYS":
        return [...secrets.CLIPROXY_CLIENT_API_KEYS];
      default:
        throw new Error(`unsupported CLIProxyAPI secret placeholder: ${name}`);
    }
  }
  if (Array.isArray(value)) {
    return value.map((entry) => resolvePlaceholders(entry, secrets, managementKey));
  }
  if (!isRecord(value)) {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value).map(([name, entry]) => [
      name,
      resolvePlaceholders(entry, secrets, managementKey),
    ]),
  );
}

function reusableManagementKey(path: string, plaintextKey: string): string {
  try {
    const config = expectRecord(Bun.YAML.parse(fs.readFileSync(path, "utf8")), "generated config");
    const remoteManagement = expectRecord(config["remote-management"], "remote-management");
    const storedKey = remoteManagement["secret-key"];
    if (
      typeof storedKey === "string" &&
      BCRYPT_HASH_PATTERN.test(storedKey) &&
      Bun.password.verifySync(plaintextKey, storedKey)
    ) {
      return storedKey;
    }
  } catch {
    // A missing, malformed, or stale output is replaced from the source template.
  }
  return Bun.password.hashSync(plaintextKey, {
    algorithm: "bcrypt",
    cost: 10,
  });
}

function expandNativeCredentialSection(
  sectionName: string,
  value: unknown,
  pools: Readonly<Record<string, readonly Credential[]>>,
  referencedPools: Set<string>,
): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`invalid ${sectionName}: expected array`);
  }
  return value.flatMap((rawProfile, index) => {
    const profile = expectRecord(rawProfile, `${sectionName}[${index}]`);
    const poolName = profile[POOL_MARKER];
    if (poolName === undefined) {
      return [profile];
    }
    validatePoolMarker(poolName, `${sectionName}[${index}]`);
    rejectOwnedFields(profile, `${sectionName}[${index}]`, ["api-key", "weight", "proxy-url"]);
    const credentials = requirePool(poolName, pools);
    referencedPools.add(poolName);
    const { [POOL_MARKER]: _marker, ...sharedProfile } = profile;
    return credentials.map((credential) =>
      Object.assign(credentialConfig(credential), sharedProfile),
    );
  });
}

function expandCompatibilitySection(
  value: unknown,
  pools: Readonly<Record<string, readonly Credential[]>>,
  referencedPools: Set<string>,
): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error("invalid openai-compatibility: expected array");
  }
  return value.map((rawProfile, index) => {
    const label = `openai-compatibility[${index}]`;
    const profile = expectRecord(rawProfile, label);
    const poolName = profile[POOL_MARKER];
    if (poolName === undefined) {
      return profile;
    }
    validatePoolMarker(poolName, label);
    rejectOwnedFields(profile, label, ["api-key-entries"]);
    const credentials = requirePool(poolName, pools);
    referencedPools.add(poolName);
    const { [POOL_MARKER]: _marker, ...sharedProfile } = profile;
    return {
      ...sharedProfile,
      "api-key-entries": credentials.map(credentialConfig),
    };
  });
}

function credentialConfig(credential: Credential): ConfigRecord {
  return {
    "api-key": credential.apiKey,
    ...(credential.weight === undefined ? {} : { weight: credential.weight }),
    ...(credential.proxyUrl === undefined ? {} : { "proxy-url": credential.proxyUrl }),
  };
}

function readCliProxySecrets(path: string): CliProxySecrets {
  let parsed: unknown;
  try {
    parsed = JSON.parse(readText(path, "CLIProxyAPI secrets"));
  } catch (error) {
    throw new Error(`parse CLIProxyAPI secrets ${path} (${panicMessage(error)})`, { cause: error });
  }
  const root = expectRecord(parsed, "CLIProxyAPI secrets");
  const managementKey = requireNonEmptyString(
    root["CLIPROXY_MANAGEMENT_KEY"],
    "CLIPROXY_MANAGEMENT_KEY",
  );
  const clientKeys = requireUniqueStrings(
    root["CLIPROXY_CLIENT_API_KEYS"],
    "CLIPROXY_CLIENT_API_KEYS",
  );
  const rawPools = expectRecord(root["CLIPROXY_CREDENTIAL_POOLS"], "CLIPROXY_CREDENTIAL_POOLS");
  const pools: Record<string, readonly Credential[]> = {};
  for (const [poolName, rawCredentials] of Object.entries(rawPools)) {
    if (!POOL_NAME_PATTERN.test(poolName)) {
      throw new Error(`invalid CLIProxyAPI credential pool name: ${poolName}`);
    }
    if (!Array.isArray(rawCredentials) || rawCredentials.length === 0) {
      throw new Error(`invalid CLIProxyAPI credential pool ${poolName}: expected non-empty array`);
    }
    const credentials = rawCredentials.map((value, index) =>
      parseCredential(value, `${poolName}[${index}]`),
    );
    rejectDuplicateCredentialKeys(poolName, credentials);
    pools[poolName] = credentials;
  }
  if (Object.keys(pools).length === 0) {
    throw new Error("invalid CLIPROXY_CREDENTIAL_POOLS: expected at least one pool");
  }
  return {
    CLIPROXY_MANAGEMENT_KEY: managementKey,
    CLIPROXY_CLIENT_API_KEYS: clientKeys,
    CLIPROXY_CREDENTIAL_POOLS: pools,
  };
}

function parseCredential(value: unknown, label: string): Credential {
  const record = expectRecord(value, `CLIProxyAPI credential ${label}`);
  const allowedFields = new Set(["apiKey", "weight", "proxyUrl"]);
  for (const name of Object.keys(record)) {
    if (!allowedFields.has(name)) {
      throw new Error(`invalid CLIProxyAPI credential ${label}: unknown field ${name}`);
    }
  }
  const apiKey = requireNonEmptyString(record["apiKey"], `${label}.apiKey`);
  const weight = record["weight"];
  if (
    weight !== undefined &&
    (typeof weight !== "number" ||
      !Number.isInteger(weight) ||
      weight <= 0 ||
      weight > MAX_CREDENTIAL_WEIGHT)
  ) {
    throw new Error(
      `invalid CLIProxyAPI credential ${label}.weight: expected integer from 1 to ${MAX_CREDENTIAL_WEIGHT}`,
    );
  }
  const proxyUrl =
    record["proxyUrl"] === undefined
      ? undefined
      : requireNonEmptyString(record["proxyUrl"], `${label}.proxyUrl`);
  return {
    apiKey,
    ...(weight === undefined ? {} : { weight }),
    ...(proxyUrl === undefined ? {} : { proxyUrl }),
  };
}

function requirePool(
  poolName: string,
  pools: Readonly<Record<string, readonly Credential[]>>,
): readonly Credential[] {
  const pool = pools[poolName];
  if (!pool) {
    throw new Error(`missing CLIProxyAPI credential pool: ${poolName}`);
  }
  return pool;
}

function validatePoolMarker(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`invalid ${label}.${POOL_MARKER}: expected non-empty string`);
  }
}

function rejectOwnedFields(record: ConfigRecord, label: string, fields: readonly string[]): void {
  for (const field of fields) {
    if (field in record) {
      throw new Error(`invalid ${label}: ${field} is owned by its credential pool`);
    }
  }
}

function rejectDuplicateCredentialKeys(poolName: string, credentials: readonly Credential[]): void {
  const keys = new Set<string>();
  for (const credential of credentials) {
    if (keys.has(credential.apiKey)) {
      throw new Error(`duplicate API key in CLIProxyAPI credential pool: ${poolName}`);
    }
    keys.add(credential.apiKey);
  }
}

function requireUniqueStrings(value: unknown, label: string): readonly string[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`invalid ${label}: expected non-empty array`);
  }
  const entries = value.map((entry, index) => requireNonEmptyString(entry, `${label}[${index}]`));
  if (new Set(entries).size !== entries.length) {
    throw new Error(`invalid ${label}: duplicate value`);
  }
  return entries;
}

function requireNonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`invalid ${label}: expected non-empty string`);
  }
  return value;
}

function expectRecord(value: unknown, label: string): ConfigRecord {
  if (!isRecord(value)) {
    throw new Error(`invalid ${label}: expected object`);
  }
  return value;
}

function isRecord(value: unknown): value is ConfigRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readText(path: string, label: string): string {
  try {
    return fs.readFileSync(path, "utf8");
  } catch (error) {
    throw new Error(`read ${label} ${path} (${panicMessage(error)})`, { cause: error });
  }
}
