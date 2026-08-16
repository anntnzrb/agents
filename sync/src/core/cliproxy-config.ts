import fs from "node:fs";
import { join } from "node:path";
import { panicMessage, warn } from "@runtime/errors.ts";
import { type CachedJsonRequest, fetchCachedJson } from "./catalog-cache.ts";
import { type CliProxyDeployment, cliProxyModelsUrl } from "./cliproxy-deployment.ts";
import type {
  CatalogApi,
  CliProxyModelMapping,
  ModelCatalogSource,
  SourceModels,
} from "./model-catalog.ts";
import { enrichGatewayModels, modelsForSource, writeModelCatalog } from "./model-catalog.ts";
import { syncPrivateTextFile } from "./secret-template.ts";

const PLACEHOLDER_PATTERN = /^\$\{([A-Z][A-Z0-9_]*)\}$/;
const POOL_NAME_PATTERN = /^[a-z][a-z0-9-]*$/;
const BCRYPT_HASH_PATTERN = /^\$2[aby]\$\d{2}\$/;
const TRAILING_SLASH_PATTERN = /\/+$/;
const TRAILING_V1_PATTERN = /\/v1\/?$/;
const POOL_MARKER = "x-credential-pool";
const MODEL_SOURCES_MARKER = "x-model-sources";
const MAX_CREDENTIAL_WEIGHT = 1_000_000;
const MODELS_DEV_URL = "https://models.dev/api.json";
const MODELS_DEV_TTL_MS = 60 * 60 * 1000;
const UPSTREAM_MODELS_TTL_MS = 6 * 60 * 60 * 1000;
const GATEWAY_MODELS_TTL_MS = 60 * 60 * 1000;
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
  readonly CLIPROXY_CREDENTIAL_POOLS: Readonly<Record<string, readonly Credential[]>>;
}

export interface CliProxyModelSource extends ModelCatalogSource {
  readonly credentialPool: string;
}

type ConfigRecord = Record<string, unknown>;

export interface CliProxyConfigSyncOptions {
  readonly writeServerConfig?: boolean;
  readonly cacheRoot?: string;
  readonly runtimeRoot?: string;
  readonly forceModelRefresh?: boolean;
  readonly quietModelRefresh?: boolean;
  readonly fetch?: CachedJsonRequest["fetch"];
  readonly now?: () => number;
}

export async function syncCliProxyConfig(
  src: string,
  dst: string,
  secretsPath: string,
  deployment: CliProxyDeployment,
  options: CliProxyConfigSyncOptions = {},
): Promise<void> {
  const template = readText(src, "CLIProxyAPI template");
  const secrets = readCliProxySecrets(secretsPath);
  if (options.runtimeRoot) {
    fs.rmSync(runtimeClientApiKeyPath(options.runtimeRoot), { force: true });
  }
  const sources = modelSourcesFromTemplate(template);
  const discovery =
    sources.length === 0
      ? { sources: new Map<string, SourceModels>(), modelsDev: undefined }
      : await discoverModelSources(sources, secrets, options);
  const managementKey = reusableManagementKey(dst, secrets.CLIPROXY_MANAGEMENT_KEY);
  const content = renderCliProxyConfig(
    template,
    secrets,
    deployment,
    managementKey,
    discovery.sources,
  );
  if (options.writeServerConfig !== false) {
    try {
      syncPrivateTextFile(dst, content);
    } catch (error) {
      throw new Error(`render CLIProxyAPI config ${src} -> ${dst} (${panicMessage(error)})`, {
        cause: error,
      });
    }
  }
  if (sources.length > 0) {
    await syncSharedModelCatalog(
      deployment,
      sources,
      discovery.sources,
      discovery.modelsDev,
      options,
    );
    removeLegacyModelCatalog(requireCacheRoot(options.cacheRoot));
  }
}

export function renderCliProxyConfig(
  template: string,
  secrets: CliProxySecrets,
  deployment: CliProxyDeployment,
  managementKey = secrets.CLIPROXY_MANAGEMENT_KEY,
  discoveredSources: ReadonlyMap<string, SourceModels> = new Map(),
): string {
  let parsed: unknown;
  try {
    parsed = Bun.YAML.parse(template);
  } catch (error) {
    throw new Error(`parse CLIProxyAPI template (${panicMessage(error)})`, { cause: error });
  }

  const unresolvedConfig = expectRecord(parsed, "CLIProxyAPI template root");
  unresolvedConfig["host"] = deployment.listen.host;
  unresolvedConfig["port"] = deployment.listen.port;
  const config = expectRecord(
    resolvePlaceholders(unresolvedConfig, managementKey),
    "CLIProxyAPI template root",
  );
  const referencedPools = new Set<string>();
  expandModelSources(config, secrets.CLIPROXY_CREDENTIAL_POOLS, referencedPools, discoveredSources);

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

export function modelSourcesFromTemplate(template: string): readonly CliProxyModelSource[] {
  let parsed: unknown;
  try {
    parsed = Bun.YAML.parse(template);
  } catch (error) {
    throw new Error(`parse CLIProxyAPI template (${panicMessage(error)})`, { cause: error });
  }
  const config = expectRecord(parsed, "CLIProxyAPI template root");
  return parseModelSources(config[MODEL_SOURCES_MARKER]);
}

function runtimeClientApiKeyPath(runtimeRoot: string): string {
  return join(runtimeRoot, "cliproxyapi", "client-api-key");
}

export const runtimeModelCatalogPath = (runtimeRoot: string): string =>
  join(runtimeRoot, "model-catalog", "catalog.json");

export const legacyModelCatalogPath = (cacheRoot: string): string =>
  join(cacheRoot, "catalog.json");

async function discoverModelSources(
  sources: readonly CliProxyModelSource[],
  secrets: CliProxySecrets,
  options: CliProxyConfigSyncOptions,
): Promise<{
  readonly sources: ReadonlyMap<string, SourceModels>;
  readonly modelsDev: unknown;
}> {
  const cacheRoot = requireCacheRoot(options.cacheRoot);
  const modelsDevResult = await cachedCatalogRequest(
    {
      url: MODELS_DEV_URL,
      cachePath: join(cacheRoot, "models-dev.json"),
      ttlMs: MODELS_DEV_TTL_MS,
    },
    options,
  );
  const entries = await Promise.all(
    sources.map(async (source) => {
      const credentials = requirePool(source.credentialPool, secrets.CLIPROXY_CREDENTIAL_POOLS);
      const apiKey = firstCredentialKey(credentials, source.credentialPool);
      const result = await cachedCatalogRequest(
        {
          url: `${source.baseUrl}/models`,
          cachePath: join(cacheRoot, `source-${source.id}.json`),
          ttlMs: UPSTREAM_MODELS_TTL_MS,
          headers: { Authorization: `Bearer ${apiKey}` },
        },
        options,
      );
      const discovered = modelsForSource(source, result.payload, modelsDevResult.payload);
      if (
        options.forceModelRefresh &&
        discovered.unsupported.length > 0 &&
        !options.quietModelRefresh
      ) {
        const npmPackages = [
          ...new Set(discovered.unsupported.map((model) => model.npm ?? "unknown")),
        ].toSorted();
        warn(
          `${source.id}: skipped ${discovered.unsupported.length} models with unsupported transports (${npmPackages.join(", ")})`,
        );
      }
      return [source.id, discovered] as const;
    }),
  );
  return {
    sources: new Map(entries),
    modelsDev: modelsDevResult.payload,
  };
}

async function syncSharedModelCatalog(
  deployment: CliProxyDeployment,
  sources: readonly CliProxyModelSource[],
  discoveredSources: ReadonlyMap<string, SourceModels>,
  modelsDev: unknown,
  options: CliProxyConfigSyncOptions,
): Promise<void> {
  const cacheRoot = requireCacheRoot(options.cacheRoot);
  const runtimeRoot = requireRuntimeRoot(options.runtimeRoot);
  const externalModels = [...discoveredSources.values()].flatMap((source) => source.models);
  let gatewayPayload: unknown = { data: [] };
  try {
    gatewayPayload = (
      await cachedCatalogRequest(
        {
          url: cliProxyModelsUrl(deployment),
          cachePath: join(cacheRoot, "gateway.json"),
          ttlMs: GATEWAY_MODELS_TTL_MS,
        },
        options,
      )
    ).payload;
  } catch (error) {
    if (options.forceModelRefresh) {
      throw error;
    }
  }
  writeModelCatalog(
    runtimeModelCatalogPath(runtimeRoot),
    enrichGatewayModels(externalModels, gatewayPayload, {
      modelsDev,
      managedPrefixes: sources.map((source) => source.prefix),
    }),
  );
}

async function cachedCatalogRequest(
  request: Omit<CachedJsonRequest, "allowStaleOnError" | "fetch" | "force" | "now">,
  options: CliProxyConfigSyncOptions,
) {
  const result = await fetchCachedJson({
    ...request,
    allowStaleOnError: !options.forceModelRefresh,
    ...(options.forceModelRefresh === undefined ? {} : { force: options.forceModelRefresh }),
    ...(options.fetch === undefined ? {} : { fetch: options.fetch }),
    ...(options.now === undefined ? {} : { now: options.now }),
  });
  if (result.source === "stale" && !options.quietModelRefresh) {
    warn(`model catalog refresh failed; using stale cache for ${request.url}`);
  }
  return result;
}

function requireCacheRoot(value: string | undefined): string {
  if (!value) {
    throw new Error("missing model catalog cache root");
  }
  return value;
}

function requireRuntimeRoot(value: string | undefined): string {
  if (!value) {
    throw new Error("missing agents runtime root");
  }
  return value;
}

function removeLegacyModelCatalog(cacheRoot: string): void {
  fs.rmSync(legacyModelCatalogPath(cacheRoot), { force: true });
}

function resolvePlaceholders(value: unknown, managementKey: string): unknown {
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
      default:
        throw new Error(`unsupported CLIProxyAPI secret placeholder: ${name}`);
    }
  }
  if (Array.isArray(value)) {
    return value.map((entry) => resolvePlaceholders(entry, managementKey));
  }
  if (!isRecord(value)) {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value).map(([name, entry]) => [name, resolvePlaceholders(entry, managementKey)]),
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

function expandModelSources(
  config: ConfigRecord,
  pools: Readonly<Record<string, readonly Credential[]>>,
  referencedPools: Set<string>,
  discoveredSources: ReadonlyMap<string, SourceModels>,
): void {
  const rawSources = config[MODEL_SOURCES_MARKER];
  if (rawSources === undefined) {
    if (discoveredSources.size > 0) {
      throw new Error("CLIProxyAPI model catalogs were discovered without model sources");
    }
    return;
  }
  const sources = parseModelSources(rawSources);
  delete config[MODEL_SOURCES_MARKER];

  const generated: Partial<Record<NativeModelSection, ConfigRecord[]>> = {};
  const compatibility: ConfigRecord[] = [];
  for (const source of sources) {
    const credentials = requirePool(source.credentialPool, pools);
    const discovered = discoveredSources.get(source.id);
    if (!discovered) {
      throw new Error(`missing discovered CLIProxyAPI model source: ${source.id}`);
    }
    referencedPools.add(source.credentialPool);
    for (const [api, models] of discovered.groups) {
      if (models.length === 0) {
        continue;
      }
      if (api === "openai-completions") {
        compatibility.push(compatibilityProfile(source, credentials, models));
        continue;
      }
      const sectionName = nativeSectionForApi(api);
      const profiles = generated[sectionName] ?? [];
      profiles.push(
        ...credentials.map((credential) => nativeModelProfile(source, credential, models, api)),
      );
      generated[sectionName] = profiles;
    }
  }
  for (const [sectionName, profiles] of Object.entries(generated)) {
    appendProfiles(config, sectionName, profiles);
  }
  appendProfiles(config, "openai-compatibility", compatibility);
}

type NativeModelSection = "claude-api-key" | "codex-api-key";

function nativeSectionForApi(api: Exclude<CatalogApi, "openai-completions">): NativeModelSection {
  return api === "anthropic-messages" ? "claude-api-key" : "codex-api-key";
}

function compatibilityProfile(
  source: CliProxyModelSource,
  credentials: readonly Credential[],
  models: readonly CliProxyModelMapping[],
): ConfigRecord {
  return {
    name: source.id,
    prefix: source.prefix,
    "base-url": source.baseUrl,
    "api-key-entries": credentials.map(credentialConfig),
    models,
  };
}

function nativeModelProfile(
  source: CliProxyModelSource,
  credential: Credential,
  models: readonly CliProxyModelMapping[],
  api: Exclude<CatalogApi, "openai-completions">,
): ConfigRecord {
  return {
    ...credentialConfig(credential),
    prefix: source.prefix,
    "base-url":
      api === "anthropic-messages"
        ? source.baseUrl.replace(TRAILING_V1_PATTERN, "")
        : source.baseUrl,
    models,
  };
}

function appendProfiles(
  config: ConfigRecord,
  sectionName: string,
  profiles: readonly ConfigRecord[],
): void {
  if (profiles.length === 0) {
    return;
  }
  const existing = config[sectionName];
  if (existing !== undefined && !Array.isArray(existing)) {
    throw new Error(`invalid ${sectionName}: expected array`);
  }
  config[sectionName] = [...(existing ?? []), ...profiles];
}

function parseModelSources(value: unknown): CliProxyModelSource[] {
  if (value === undefined) {
    return [];
  }
  if (!Array.isArray(value)) {
    throw new Error(`invalid ${MODEL_SOURCES_MARKER}: expected array`);
  }
  const seen = new Set<string>();
  const seenPrefixes = new Set<string>();
  return value.map((rawSource, index) => {
    const label = `${MODEL_SOURCES_MARKER}[${index}]`;
    const source = expectRecord(rawSource, label);
    const allowed = new Set(["id", "models-dev-provider", "credential-pool", "prefix", "base-url"]);
    for (const field of Object.keys(source)) {
      if (!allowed.has(field)) {
        throw new Error(`invalid ${label}: unknown field ${field}`);
      }
    }
    const id = requireNonEmptyString(source["id"], `${label}.id`);
    if (!POOL_NAME_PATTERN.test(id) || seen.has(id)) {
      throw new Error(`invalid ${label}.id: ${id}`);
    }
    seen.add(id);
    const modelsDevProvider = requireNonEmptyString(
      source["models-dev-provider"],
      `${label}.models-dev-provider`,
    );
    const credentialPool = requireNonEmptyString(
      source["credential-pool"],
      `${label}.credential-pool`,
    );
    const prefix = requireNonEmptyString(source["prefix"], `${label}.prefix`);
    if (!POOL_NAME_PATTERN.test(prefix) || seenPrefixes.has(prefix)) {
      throw new Error(`invalid ${label}.prefix: ${prefix}`);
    }
    seenPrefixes.add(prefix);
    const baseUrl = requireHttpUrl(source["base-url"], `${label}.base-url`);
    return {
      id,
      modelsDevProvider,
      credentialPool,
      prefix,
      baseUrl,
    };
  });
}

function firstCredentialKey(credentials: readonly Credential[], poolName: string): string {
  const credential = credentials[0];
  if (!credential) {
    throw new Error(`empty CLIProxyAPI credential pool: ${poolName}`);
  }
  return credential.apiKey;
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

function requireNonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`invalid ${label}: expected non-empty string`);
  }
  return value;
}

function requireHttpUrl(value: unknown, label: string): string {
  const raw = requireNonEmptyString(value, label).replace(TRAILING_SLASH_PATTERN, "");
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch (error) {
    throw new Error(`invalid ${label}: expected URL`, { cause: error });
  }
  if (
    (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(`invalid ${label}: expected HTTP URL without credentials, query, or fragment`);
  }
  return raw;
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
