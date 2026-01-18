import type {
  AnswerResponse,
  ContentsOptions,
  Research,
  SearchResponse,
} from "exa-js";
import type { ResearchOutput, SearchOutput, TextResult } from "@/types";

type SearchResult = SearchResponse<ContentsOptions>["results"][number];

type SearchResultWithText = SearchResult & {
  text?: string;
  summary?: string;
  highlights?: string[];
};

export function formatSearchResponse(
  response: SearchResponse<ContentsOptions>,
): string {
  const lines: string[] = [];

  response.results.forEach((result, index) => {
    lines.push(`--- Result ${index + 1} ---`);
    lines.push(`Title: ${result.title ?? "(untitled)"}`);
    lines.push(`URL: ${result.url}`);

    if (result.publishedDate) {
      lines.push(`Published: ${result.publishedDate}`);
    }
    if (result.author) {
      lines.push(`Author: ${result.author}`);
    }
    if (typeof result.score === "number") {
      lines.push(`Score: ${result.score}`);
    }

    const summary = pickSummary(result);
    if (summary) {
      lines.push(`Summary: ${summary}`);
    }

    const text = pickText(result);
    if (text) {
      lines.push(`Text: ${text}`);
    }

    const highlights = pickHighlights(result);
    if (highlights.length > 0) {
      lines.push(`Highlights: ${highlights.join(" | ")}`);
    }

    lines.push("");
  });

  if (response.context) {
    lines.push("Context:");
    lines.push(response.context);
    lines.push("");
  }

  lines.push(`Request ID: ${response.requestId}`);

  return lines.join("\n");
}

export function formatSearchOutput(output: SearchOutput): string {
  if (output.kind === "text") {
    return output.text;
  }
  return formatSearchResponse(output.data);
}

export function formatAnswerResponse(response: AnswerResponse): string {
  const lines: string[] = [];
  lines.push("Answer:");

  if (typeof response.answer === "string") {
    lines.push(response.answer);
  } else {
    lines.push(JSON.stringify(response.answer, null, 2));
  }

  if (response.citations.length > 0) {
    lines.push("");
    lines.push("Citations:");
    response.citations.forEach((citation, index) => {
      const title = citation.title ?? "(untitled)";
      lines.push(`${index + 1}. ${title} - ${citation.url}`);
    });
  }

  if (response.requestId) {
    lines.push("");
    lines.push(`Request ID: ${response.requestId}`);
  }

  return lines.join("\n");
}

export function formatResearchResponse(research: Research): string {
  return JSON.stringify(research, null, 2);
}

export function formatResearchOutput(output: ResearchOutput): string {
  if (output.kind === "text") {
    return output.text;
  }
  return formatResearchResponse(output.data);
}

export function formatTextResult(result: TextResult): string {
  return result.text;
}

function pickText(result: SearchResult): string | undefined {
  const candidate = (result as SearchResultWithText).text;
  if (typeof candidate === "string") {
    const trimmed = candidate.trim();
    return trimmed.length > 0 ? trimmed : undefined;
  }
  return undefined;
}

function pickSummary(result: SearchResult): string | undefined {
  const candidate = (result as SearchResultWithText).summary;
  if (typeof candidate === "string") {
    const trimmed = candidate.trim();
    return trimmed.length > 0 ? trimmed : undefined;
  }
  return undefined;
}

function pickHighlights(result: SearchResult): string[] {
  const candidate = (result as SearchResultWithText).highlights;
  if (Array.isArray(candidate)) {
    return candidate.filter((item) => typeof item === "string");
  }
  return [];
}
