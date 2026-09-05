import fs from "node:fs";
import { panicMessage } from "@runtime/errors.ts";
import { Schema } from "effect";
import type { CliProxyDeployment } from "./cliproxy-deployment.ts";
import { syncPrivateTextFile } from "./secret-template.ts";

const POOL_NAME_PATTERN = /^[a-z][a-z0-9-]*$/;
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
  readonly CLIPROXY_CREDENTIAL_POOLS: Readonly<Record<string, readonly Credential[]>>;
}

type ConfigRecord = Record<string, unknown>;

export function renderCliProxyConfig(
  template: string,
  secrets: CliProxySecrets,
  deployment: CliProxyDeployment,
): string {
  let parsed: unknown;
  try {
    parsed = Bun.YAML.parse(template);
  } catch (error) {
    throw new Error(`parse CLIProxyAPI template (${panicMessage(error)})`, { cause: error });
  }

  const config = expectRecord(parsed, "CLIProxyAPI template root");
  if ("x-model-sources" in config) {
    throw new Error("unsupported CLIProxyAPI template field: x-model-sources");
  }
  config["host"] = deployment.listen.host;
  config["port"] = deployment.listen.port;
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

export async function syncCliProxyConfig(
  src: string,
  dst: string,
  secretsPath: string,
  deployment: CliProxyDeployment,
): Promise<void> {
  const template = readText(src, "CLIProxyAPI template");
  const secrets = readCliProxySecrets(secretsPath);
  const content = renderCliProxyConfig(template, secrets, deployment);
  try {
    syncPrivateTextFile(dst, content);
  } catch (error) {
    throw new Error(`render CLIProxyAPI config ${src} -> ${dst} (${panicMessage(error)})`, {
      cause: error,
    });
  }
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

const CredentialSchema = Schema.Struct({
  apiKey: Schema.NonEmptyString,
  weight: Schema.optionalKey(
    Schema.Int.pipe(
      Schema.check(
        Schema.makeFilter((w: number) =>
          w >= 1 && w <= MAX_CREDENTIAL_WEIGHT
            ? undefined
            : `expected integer from 1 to ${MAX_CREDENTIAL_WEIGHT}`,
        ),
      ),
    ),
  ),
  proxyUrl: Schema.optionalKey(Schema.NonEmptyString),
});

const PoolNameSchema = Schema.NonEmptyString.pipe(
  Schema.check(
    Schema.makeFilter((name: string) =>
      POOL_NAME_PATTERN.test(name) ? undefined : "invalid pool name",
    ),
  ),
);

const CliProxySecretsSchema = Schema.Struct({
  CLIPROXY_CREDENTIAL_POOLS: Schema.Record(PoolNameSchema, Schema.NonEmptyArray(CredentialSchema)),
});

function readCliProxySecrets(path: string): CliProxySecrets {
  let parsed: unknown;
  try {
    parsed = Bun.JSONC.parse(readText(path, "CLIProxyAPI secrets"));
  } catch (error) {
    throw new Error(`parse CLIProxyAPI secrets ${path} (${panicMessage(error)})`, { cause: error });
  }
  let decoded: {
    readonly CLIPROXY_CREDENTIAL_POOLS: Readonly<Record<string, readonly Credential[]>>;
  };
  try {
    decoded = Schema.decodeUnknownSync(CliProxySecretsSchema)(parsed);
  } catch (error) {
    throw new Error(`invalid CLIProxyAPI secrets ${path} (${panicMessage(error)})`, {
      cause: error,
    });
  }
  for (const [poolName, credentials] of Object.entries(decoded.CLIPROXY_CREDENTIAL_POOLS)) {
    rejectDuplicateCredentialKeys(poolName, credentials);
  }
  return decoded;
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

const isRecord = Schema.is(Schema.Record(Schema.String, Schema.Unknown));

function expectRecord(value: unknown, label: string): ConfigRecord {
  if (!isRecord(value)) {
    throw new Error(`invalid ${label}: expected object`);
  }
  return value;
}
function readText(path: string, label: string): string {
  try {
    return fs.readFileSync(path, "utf8");
  } catch (error) {
    throw new Error(`read ${label} ${path} (${panicMessage(error)})`, { cause: error });
  }
}
