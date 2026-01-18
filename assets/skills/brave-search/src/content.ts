import { JSDOM } from "jsdom";
import { htmlToMarkdown } from "./markdown";
import type { ExtractedContent, FetchLike } from "./types";

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

export const MAX_CONTENT_CHARS = 5000;

export function extractReadableContent(
  html: string,
  url: string,
): ExtractedContent | null {
  const dom = new JSDOM(html, { url });
  const doc = dom.window.document;
  const cleanupNodes = Array.from(
    doc.querySelectorAll("script, style, noscript, nav, header, footer, aside"),
  );
  for (const node of cleanupNodes) {
    node.remove();
  }

  const title = doc.querySelector("title")?.textContent?.trim() || undefined;
  const main =
    doc.querySelector("main, article, [role='main'], .content, #content") ||
    doc.body;
  const text = main?.innerHTML || "";

  if (text.trim().length > 100) {
    const content = htmlToMarkdown(text);
    return title ? { title, content } : { content };
  }

  return null;
}

export async function fetchPageContent(
  url: string,
  fetcher: FetchLike = fetch,
): Promise<string> {
  try {
    const response = await fetcher(url, {
      headers: {
        "User-Agent": USER_AGENT,
        Accept:
          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
      },
      signal: AbortSignal.timeout(15000),
    });

    if (!response.ok) {
      return `(HTTP ${response.status})`;
    }

    const html = await response.text();
    const extracted = extractReadableContent(html, url);
    if (extracted?.content) {
      return extracted.content.substring(0, MAX_CONTENT_CHARS);
    }

    return "(Could not extract content)";
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return `(Error: ${message})`;
  }
}
