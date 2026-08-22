import type {
  SearchError,
  SearchFailurePayload,
  SearchResult,
  SearchSource,
  SearchSuccessPayload,
} from "./models.ts";

export function mergeParallelResults(
  fallbackQuery: string,
  results: readonly SearchResult[],
  compact: boolean
): SearchResult {
  const successful: SearchSuccessPayload[] = [];
  for (const r of results) {
    if (r.ok) {
      successful.push(r);
    }
  }

  if (successful.length === 0) {
    let firstError: SearchError = {
      code: "all_providers_failed",
      message: "All parallel providers failed",
    };
    for (const r of results) {
      if (!r.ok && r.error) {
        firstError = r.error;
        break;
      }
    }

    const failurePayload: SearchFailurePayload = {
      ok: false,
      query: fallbackQuery,
      provider: results.map((r) => r.provider || "unknown").join(" | "),
      providers: results.map((r) => r.provider || "unknown"),
      providers_count: results.length,
      answer: "",
      sources: [],
      sources_count: 0,
      truncated: false,
      compact,
      parsed: false,
      error: firstError,
      exit_code: 1,
    };
    return failurePayload;
  }

  const mergedSources: SearchSource[] = [];
  const seenSources = new Set<string>();
  const answerSections: string[] = [];
  const usedProviders: string[] = [];

  for (const r of successful) {
    const prov = r.provider || "Unknown";
    usedProviders.push(prov);
    const ans = r.answer.trim();
    if (ans) {
      answerSections.push(`### [${prov}]\n${ans}`);
    }

    for (const src of r.sources) {
      const title = src.title.trim();
      const domain = src.domain.trim();
      const key = `${title.toLowerCase()}|${domain.toLowerCase()}`;
      if (!seenSources.has(key)) {
        seenSources.add(key);
        mergedSources.push({
          title,
          domain,
          age: src.age ?? null,
        });
      }
    }
  }

  const successPayload: SearchSuccessPayload = {
    ok: true,
    query: fallbackQuery,
    provider: usedProviders.join("+"),
    providers: usedProviders,
    providers_count: usedProviders.length,
    answer: answerSections.join("\n\n"),
    sources: mergedSources,
    sources_count: mergedSources.length,
    truncated: successful.some((r) => r.truncated),
    compact,
    parsed: true,
    exit_code: 0,
  };

  return successPayload;
}
