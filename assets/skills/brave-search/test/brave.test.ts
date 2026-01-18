import { describe, expect, it } from "bun:test";
import { fetchBraveResults, parseSearchResults } from "@/brave";
import type { FetchLike } from "@/types";

const sampleHtml = `
<html>
  <body>
    <div class="snippet" data-type="web">
      <a class="svelte-14r20fy" href="https://example.com">
        <div class="title">Example Title</div>
      </a>
      <div class="generic-snippet"><span class="content">January 2, 2024 - Example snippet.</span></div>
    </div>
    <div class="snippet" data-type="web">
      <a class="svelte-14r20fy" href="not-a-url">
        <div class="title">Loose Link</div>
      </a>
      <div class="generic-snippet"><span class="content">Loose snippet.</span></div>
    </div>
    <div class="snippet" data-type="web">
      <a class="svelte-14r20fy" href="https://brave.com">
        <div class="title">Brave Result</div>
      </a>
      <div class="generic-snippet"><span class="content">Brave snippet.</span></div>
    </div>
  </body>
</html>
`;

describe("parseSearchResults", () => {
  it("parses and filters results", () => {
    const results = parseSearchResults(sampleHtml, 5);
    expect(results.length).toBe(2);
    expect(results[0]?.title).toBe("Example Title");
    expect(results[0]?.link).toBe("https://example.com");
    expect(results[0]?.snippet).toBe("Example snippet.");
    expect(results[1]?.link).toBe("not-a-url");
  });
});

describe("fetchBraveResults", () => {
  it("returns parsed results", async () => {
    const fetcher: FetchLike = async () =>
      new Response(sampleHtml, { status: 200 });
    const results = await fetchBraveResults("query", 5, fetcher);
    expect(results.length).toBe(2);
  });

  it("throws on bad response", async () => {
    const fetcher: FetchLike = async () =>
      new Response("nope", { status: 500, statusText: "Fail" });

    await expect(fetchBraveResults("query", 5, fetcher)).rejects.toThrow(
      "HTTP 500: Fail",
    );
  });
});
