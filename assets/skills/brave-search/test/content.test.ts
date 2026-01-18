import { describe, expect, it } from "bun:test";
import {
  extractReadableContent,
  fetchPageContent,
  MAX_CONTENT_CHARS,
} from "@/content";
import type { FetchLike } from "@/types";

const articleHtml = `
<html>
  <head><title>Sample Page</title></head>
  <body>
    <article>
      <h1>Sample Page</h1>
      <p>This is a sample article with enough content to parse.</p>
      <p>${"word ".repeat(400)}</p>
    </article>
  </body>
</html>
`;

const fallbackHtml = `
<html>
  <head><title>Fallback Page</title></head>
  <body>
    <main>
      <p>${"fallback ".repeat(30)}</p>
    </main>
  </body>
</html>
`;

describe("extractReadableContent", () => {
  it("extracts article content", () => {
    const extracted = extractReadableContent(
      articleHtml,
      "https://example.com",
    );
    expect(extracted).not.toBeNull();
    expect(extracted?.title).toContain("Sample Page");
    expect(extracted?.content.length).toBeGreaterThan(10);
  });

  it("extracts content without a title", () => {
    const html = `<html><body><main>${"text ".repeat(50)}</main></body></html>`;
    const extracted = extractReadableContent(html, "https://example.com");
    expect(extracted).not.toBeNull();
    expect(extracted?.title).toBeUndefined();
    expect(extracted?.content.length).toBeGreaterThan(10);
  });

  it("strips non-content nodes", () => {
    const html = `
      <html>
        <head><script>console.log("nope")</script></head>
        <body><main>${"keep ".repeat(40)}</main></body>
      </html>
    `;
    const extracted = extractReadableContent(html, "https://example.com");
    expect(extracted).not.toBeNull();
    expect(extracted?.content).toContain("keep");
  });

  it("falls back to main content", () => {
    const extracted = extractReadableContent(
      fallbackHtml,
      "https://example.com",
    );
    expect(extracted).not.toBeNull();
    expect(extracted?.title).toBe("Fallback Page");
  });

  it("returns null when content too short", () => {
    const extracted = extractReadableContent(
      "<html><body></body></html>",
      "https://example.com",
    );
    expect(extracted).toBeNull();
  });
});

describe("fetchPageContent", () => {
  it("returns extracted content", async () => {
    const fetcher: FetchLike = async () =>
      new Response(articleHtml, { status: 200 });
    const content = await fetchPageContent("https://example.com", fetcher);
    expect(content.length).toBeGreaterThan(10);
    expect(content.length).toBeLessThanOrEqual(MAX_CONTENT_CHARS);
  });

  it("returns http status on failure", async () => {
    const fetcher: FetchLike = async () => new Response("", { status: 404 });
    const content = await fetchPageContent("https://example.com", fetcher);
    expect(content).toBe("(HTTP 404)");
  });

  it("returns fallback message when no content extracted", async () => {
    const fetcher: FetchLike = async () =>
      new Response("<html><body></body></html>", { status: 200 });
    const content = await fetchPageContent("https://example.com", fetcher);
    expect(content).toBe("(Could not extract content)");
  });

  it("returns error message on exception", async () => {
    const fetcher: FetchLike = async () => {
      throw new Error("boom");
    };
    const content = await fetchPageContent("https://example.com", fetcher);
    expect(content).toBe("(Error: boom)");
  });
});
