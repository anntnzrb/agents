import { parseContentArgs, contentUsage } from "./src/args";
import { extractReadableContent } from "./src/content";

async function runContent(argv: string[]): Promise<number> {
  const parsed = parseContentArgs(argv);
  if (!parsed.ok) {
    console.log(contentUsage());
    console.log("\nError:", parsed.error);
    return 1;
  }

  const { url } = parsed.value;

  try {
    const response = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        Accept:
          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
      },
      signal: AbortSignal.timeout(15000),
    });

    if (!response.ok) {
      console.error(`HTTP ${response.status}: ${response.statusText}`);
      return 1;
    }

    const html = await response.text();
    const extracted = extractReadableContent(html, url);
    if (!extracted) {
      console.error("Could not extract readable content from this page.");
      return 1;
    }

    if (extracted.title) {
      console.log(`# ${extracted.title}\n`);
    }
    console.log(extracted.content);
    return 0;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Error: ${message}`);
    return 1;
  }
}

if (import.meta.main) {
  const code = await runContent(process.argv.slice(2));
  process.exit(code);
}
