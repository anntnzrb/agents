import { describe, expect, it } from "bun:test";
import type {
  AnswerResponse,
  ContentsOptions,
  Research,
  SearchResponse,
} from "exa-js";
import {
  formatAnswerResponse,
  formatResearchOutput,
  formatResearchResponse,
  formatSearchOutput,
  formatSearchResponse,
  formatTextResult,
} from "@/format";
import type { ResearchOutput, SearchOutput, TextResult } from "@/types";

const searchResponse: SearchResponse<ContentsOptions> = {
  requestId: "req-1",
  context: "Context here",
  results: [
    {
      id: "1",
      title: "Example",
      url: "https://example.com",
      publishedDate: "2024-01-01",
      author: "Author",
      score: 0.9,
    },
    {
      id: "2",
      title: null,
      url: "https://example.org",
    },
  ],
};

const searchResultWithText = {
  ...searchResponse,
  results: [
    {
      ...searchResponse.results[0],
      text: "Sample text.",
      summary: "Summary text.",
      highlights: ["highlight"],
    },
  ],
} as SearchResponse<ContentsOptions> & {
  results: Array<
    SearchResponse<ContentsOptions>["results"][number] & {
      text: string;
      summary: string;
      highlights: string[];
    }
  >;
};

const answerResponse: AnswerResponse = {
  answer: "Yes",
  citations: [
    {
      id: "c1",
      title: "Citation",
      url: "https://example.com",
    },
  ],
  requestId: "req-2",
};

const answerResponseObject: AnswerResponse = {
  answer: { value: 42 },
  citations: [],
};

const researchResponse = {
  researchId: "r1",
  instructions: "Do the thing",
  createdAt: 0,
  status: "completed",
} as Research;

describe("formatSearchResponse", () => {
  it("renders search results", () => {
    const output = formatSearchResponse(searchResultWithText);
    expect(output).toContain("Example");
    expect(output).toContain("https://example.com");
    expect(output).toContain("Summary text.");
    expect(output).toContain("Sample text.");
    expect(output).toContain("Context here");
    expect(output).toContain("Request ID: req-1");
  });
});

describe("formatSearchOutput", () => {
  it("renders text output", () => {
    const output: SearchOutput = { kind: "text", text: "MCP text" };
    expect(formatSearchOutput(output)).toBe("MCP text");
  });

  it("renders structured output", () => {
    const output: SearchOutput = { kind: "search", data: searchResponse };
    expect(formatSearchOutput(output)).toContain("Request ID: req-1");
  });
});

describe("formatAnswerResponse", () => {
  it("renders answer and citations", () => {
    const output = formatAnswerResponse(answerResponse);
    expect(output).toContain("Answer:");
    expect(output).toContain("Yes");
    expect(output).toContain("Citation");
    expect(output).toContain("Request ID: req-2");
  });

  it("renders answer object", () => {
    const output = formatAnswerResponse(answerResponseObject);
    expect(output).toContain('"value": 42');
  });
});

describe("formatResearchResponse", () => {
  it("renders research JSON", () => {
    const output = formatResearchResponse(researchResponse);
    expect(output).toContain("r1");
    expect(output).toContain("completed");
  });
});

describe("formatResearchOutput", () => {
  it("renders text output", () => {
    const output: ResearchOutput = { kind: "text", text: "done" };
    expect(formatResearchOutput(output)).toBe("done");
  });

  it("renders structured output", () => {
    const output: ResearchOutput = { kind: "research", data: researchResponse };
    expect(formatResearchOutput(output)).toContain("r1");
  });
});

describe("formatTextResult", () => {
  it("returns text", () => {
    const output: TextResult = { kind: "text", text: "plain" };
    expect(formatTextResult(output)).toBe("plain");
  });
});
