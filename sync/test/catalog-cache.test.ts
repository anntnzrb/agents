import { expect, test } from "bun:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fetchCachedJson } from "@core/catalog-cache.ts";

test("model_catalog_cache_uses_ttl_and_revalidates_with_etag", async () => {
  const root = mkdtempSync(join(tmpdir(), "catalog-cache-test-"));
  try {
    const cachePath = join(root, "catalog.json");
    let now = 1000;
    const requests: string[] = [];
    const fetchImpl = async (_input: string | URL | Request, init?: RequestInit) => {
      requests.push(new Headers(init?.headers).get("if-none-match") ?? "");
      if (requests.length === 1) {
        return Response.json({ data: [{ id: "one" }] }, { headers: { etag: '"one"' } });
      }
      return new Response(null, { status: 304 });
    };
    const request = {
      url: "https://example.test/v1/models",
      cachePath,
      ttlMs: 100,
      fetch: fetchImpl,
      now: () => now,
    };

    expect(await fetchCachedJson(request)).toMatchObject({ source: "network" });
    now = 1050;
    expect(await fetchCachedJson(request)).toMatchObject({ source: "cache" });
    now = 1200;
    expect(await fetchCachedJson(request)).toMatchObject({ source: "network" });
    expect(requests).toEqual(["", '"one"']);
    expect(JSON.parse(readFileSync(cachePath, "utf8")).fetchedAt).toBe(1200);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("model_catalog_cache_uses_stale_data_only_when_allowed", async () => {
  const root = mkdtempSync(join(tmpdir(), "catalog-cache-test-"));
  try {
    const cachePath = join(root, "catalog.json");
    let fail = false;
    const fetchImpl = async () => {
      if (fail) {
        throw new Error("offline");
      }
      return Response.json({ data: [{ id: "one" }] });
    };
    const base = {
      url: "https://example.test/v1/models",
      cachePath,
      ttlMs: 100,
      force: true,
      fetch: fetchImpl,
      now: () => 1000,
    };
    await fetchCachedJson(base);
    fail = true;

    expect(await fetchCachedJson(base)).toMatchObject({
      source: "stale",
      payload: { data: [{ id: "one" }] },
    });
    await assert.rejects(
      fetchCachedJson({ ...base, allowStaleOnError: false }),
      /refresh model catalog/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("model_catalog_cache_does_not_reuse_data_for_a_different_request_url", async () => {
  const root = mkdtempSync(join(tmpdir(), "catalog-cache-url-test-"));
  try {
    const cachePath = join(root, "catalog.json");
    let requests = 0;
    const fetchImpl = async (input: string | URL | Request) => {
      requests += 1;
      const url =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      return Response.json({ data: [{ id: url }] });
    };
    const firstUrl = "https://old-gateway.test/v1/models";
    const secondUrl = "https://new-gateway.test/v1/models";
    const base = {
      cachePath,
      ttlMs: 60_000,
      now: () => 1000,
      fetch: fetchImpl,
    };

    await fetchCachedJson({ ...base, url: firstUrl });
    const result = await fetchCachedJson({ ...base, url: secondUrl });

    expect(result.source).toBe("network");
    expect(result.payload).toEqual({ data: [{ id: secondUrl }] });
    expect(requests).toBe(2);
    expect(JSON.parse(readFileSync(cachePath, "utf8")).url).toBe(secondUrl);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
