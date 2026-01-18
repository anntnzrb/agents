import { parseSearchArgs, searchUsage } from "./src/args";
import { fetchBraveResults } from "./src/brave";
import { fetchPageContent } from "./src/content";
import type { SearchResult } from "./src/types";

async function runSearch(argv: string[]): Promise<number> {
  const parsed = parseSearchArgs(argv);
  if (!parsed.ok) {
    console.log(searchUsage());
    console.log("\nError:", parsed.error);
    return 1;
  }

  const { query, numResults, fetchContent } = parsed.value;

  try {
    const results = await fetchBraveResults(query, numResults);

    if (results.length === 0) {
      console.error("No results found.");
      return 0;
    }

    const hydrated = await hydrateResults(results, fetchContent);
    printResults(hydrated);
    return 0;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Error: ${message}`);
    return 1;
  }
}

async function hydrateResults(
  results: SearchResult[],
  fetchContent: boolean,
): Promise<SearchResult[]> {
  if (!fetchContent) {
    return results;
  }

  const hydrated: SearchResult[] = [];
  for (const result of results) {
    const content = await fetchPageContent(result.link);
    hydrated.push({ ...result, content });
  }
  return hydrated;
}

function printResults(results: SearchResult[]): void {
  for (let i = 0; i < results.length; i += 1) {
    const result = results[i];
    if (!result) {
      continue;
    }
    console.log(`--- Result ${i + 1} ---`);
    console.log(`Title: ${result.title}`);
    console.log(`Link: ${result.link}`);
    console.log(`Snippet: ${result.snippet}`);
    if (result.content) {
      console.log(`Content:\n${result.content}`);
    }
    console.log("");
  }
}

if (import.meta.main) {
  const code = await runSearch(process.argv.slice(2));
  process.exit(code);
}
