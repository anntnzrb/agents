import type { ContentArgs, ParseResult, SearchArgs } from "./types";

export function parseSearchArgs(argv: string[]): ParseResult<SearchArgs> {
  const args = [...argv];

  const contentIndex = args.indexOf("--content");
  const fetchContent = contentIndex !== -1;
  if (fetchContent) {
    args.splice(contentIndex, 1);
  }

  let numResults = 5;
  const nIndex = args.indexOf("-n");
  if (nIndex !== -1) {
    const raw = args[nIndex + 1];
    if (!raw) {
      return { ok: false, error: "Missing value for -n." };
    }
    const parsed = Number.parseInt(raw, 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return { ok: false, error: "-n must be a positive integer." };
    }
    numResults = parsed;
    args.splice(nIndex, 2);
  }

  const query = args.join(" ").trim();
  if (!query) {
    return { ok: false, error: "Missing query." };
  }

  return {
    ok: true,
    value: {
      query,
      numResults,
      fetchContent,
    },
  };
}

export function parseContentArgs(argv: string[]): ParseResult<ContentArgs> {
  const url = argv[0]?.trim();
  if (!url) {
    return { ok: false, error: "Missing URL." };
  }
  return { ok: true, value: { url } };
}

export function searchUsage(): string {
  return [
    "Usage: search.ts <query> [-n <num>] [--content]",
    "",
    "Options:",
    "  -n <num>    Number of results (default: 5)",
    "  --content   Fetch readable content as markdown",
    "",
    "Examples:",
    '  search.ts "javascript async await"',
    '  search.ts "rust programming" -n 10',
    '  search.ts "climate change" --content',
  ].join("\n");
}

export function contentUsage(): string {
  return [
    "Usage: content.ts <url>",
    "",
    "Extracts readable content from a webpage as markdown.",
    "",
    "Examples:",
    "  content.ts https://example.com/article",
    "  content.ts https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
  ].join("\n");
}
