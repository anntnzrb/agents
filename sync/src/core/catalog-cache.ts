import fs from "node:fs";
import { syncTextFile } from "./secret-template.ts";

const CACHE_VERSION = 2;
const CACHE_MODE = 0o600;

interface CacheEntry {
  readonly version: typeof CACHE_VERSION;
  readonly url: string;
  readonly fetchedAt: number;
  readonly etag?: string;
  readonly payload: unknown;
}

export interface CachedJsonRequest {
  readonly url: string;
  readonly cachePath: string;
  readonly ttlMs: number;
  readonly force?: boolean;
  readonly allowStaleOnError?: boolean;
  readonly headers?: Readonly<Record<string, string>>;
  readonly fetch?: CatalogFetch;
  readonly now?: () => number;
}

export interface CachedJsonResult {
  readonly payload: unknown;
  readonly source: "cache" | "network" | "stale";
}

export type CatalogFetch = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export async function fetchCachedJson(request: CachedJsonRequest): Promise<CachedJsonResult> {
  validateRequest(request);
  const now = request.now ?? Date.now;
  const cached = readCache(request.cachePath, request.url);
  if (!request.force && cached && now() - cached.fetchedAt < request.ttlMs) {
    return { payload: cached.payload, source: "cache" };
  }

  const headers = new Headers(request.headers);
  headers.set("Accept", "application/json");
  if (cached?.etag) {
    headers.set("If-None-Match", cached.etag);
  }

  try {
    const response = await (request.fetch ?? fetch)(request.url, {
      headers,
      signal: AbortSignal.timeout(20_000),
    });
    if (response.status === 304 && cached) {
      writeCache(request.cachePath, {
        ...cached,
        fetchedAt: now(),
      });
      return { payload: cached.payload, source: "network" };
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const etag = response.headers.get("etag");
    const entry: CacheEntry = {
      version: CACHE_VERSION,
      url: request.url,
      fetchedAt: now(),
      ...(etag ? { etag } : {}),
      payload: await response.json(),
    };
    writeCache(request.cachePath, entry);
    return { payload: entry.payload, source: "network" };
  } catch (error) {
    if (cached && request.allowStaleOnError !== false) {
      return { payload: cached.payload, source: "stale" };
    }
    throw new Error(`refresh model catalog ${request.url}`, { cause: error });
  }
}

function validateRequest(request: CachedJsonRequest): void {
  const url = new URL(request.url);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`invalid model catalog URL: ${request.url}`);
  }
  if (!Number.isSafeInteger(request.ttlMs) || request.ttlMs <= 0) {
    throw new Error(`invalid model catalog TTL: ${request.ttlMs}`);
  }
}

function readCache(path: string, requestUrl: string): CacheEntry | undefined {
  try {
    const value: unknown = JSON.parse(fs.readFileSync(path, "utf8"));
    if (
      typeof value !== "object" ||
      value === null ||
      Array.isArray(value) ||
      !("version" in value) ||
      value.version !== CACHE_VERSION ||
      !("url" in value) ||
      typeof value.url !== "string" ||
      value.url !== requestUrl ||
      !("fetchedAt" in value) ||
      typeof value.fetchedAt !== "number" ||
      !Number.isSafeInteger(value.fetchedAt) ||
      !("payload" in value) ||
      ("etag" in value && typeof value.etag !== "string")
    ) {
      return undefined;
    }
    const etag = "etag" in value ? value.etag : undefined;
    return {
      version: CACHE_VERSION,
      url: value.url,
      fetchedAt: value.fetchedAt,
      ...(typeof etag === "string" ? { etag } : {}),
      payload: value.payload,
    };
  } catch {
    return undefined;
  }
}

function writeCache(path: string, entry: CacheEntry): void {
  syncTextFile(path, `${JSON.stringify(entry)}\n`, CACHE_MODE);
}
