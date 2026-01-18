import { JSDOM } from "jsdom";
import type { FetchLike, SearchResult } from "./types";

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36";

export function parseSearchResults(
  html: string,
  numResults: number,
): SearchResult[] {
  const dom = new JSDOM(html);
  const doc = dom.window.document;

  const results: SearchResult[] = [];
  const snippets = Array.from(
    doc.querySelectorAll<HTMLDivElement>("div.snippet[data-type='web']"),
  );

  for (const snippet of snippets) {
    if (results.length >= numResults) {
      break;
    }

    const titleLink =
      snippet.querySelector<HTMLAnchorElement>("a.svelte-14r20fy");
    if (!titleLink) {
      continue;
    }

    const link = titleLink.getAttribute("href")?.trim();
    if (!link || isBraveLink(link)) {
      continue;
    }

    const titleEl = titleLink.querySelector<HTMLElement>(".title");
    const title =
      titleEl?.textContent?.trim() || titleLink.textContent?.trim() || "";

    const descEl = snippet.querySelector<HTMLElement>(
      ".generic-snippet .content",
    );
    let snippetText = descEl?.textContent?.trim() || "";
    snippetText = snippetText.replace(/^[A-Z][a-z]+ \d{1,2}, \d{4} -\s*/, "");

    if (title) {
      results.push({ title, link, snippet: snippetText });
    }
  }

  return results;
}

export async function fetchBraveResults(
  query: string,
  numResults: number,
  fetcher: FetchLike = fetch,
): Promise<SearchResult[]> {
  const url = `https://search.brave.com/search?q=${encodeURIComponent(query)}`;

  const response = await fetcher(url, {
    headers: {
      "User-Agent": USER_AGENT,
      Accept:
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9",
      "sec-ch-ua":
        '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
      "sec-ch-ua-mobile": "?0",
      "sec-ch-ua-platform": '"macOS"',
      "sec-fetch-dest": "document",
      "sec-fetch-mode": "navigate",
      "sec-fetch-site": "none",
      "sec-fetch-user": "?1",
    },
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  const html = await response.text();
  return parseSearchResults(html, numResults);
}

function isBraveLink(link: string): boolean {
  try {
    const url = new URL(link);
    return url.hostname.endsWith("brave.com");
  } catch {
    return false;
  }
}
