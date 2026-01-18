import { afterEach, describe, expect, it, spyOn } from "bun:test";
import type {
  AnswerResponse,
  ContentsOptions,
  Research,
  SearchResponse,
} from "exa-js";
import { dispatchCommand, runExa } from "@/cli";
import type { Command, ExaClient, TextResult } from "@/types";

const searchResponse: SearchResponse<ContentsOptions> = {
  requestId: "req-1",
  results: [
    {
      id: "1",
      title: "Example",
      url: "https://example.com",
    },
  ],
};

const answerResponse: AnswerResponse = {
  answer: "ok",
  citations: [],
};

const researchResponse = {
  researchId: "r1",
  instructions: "Do work",
  createdAt: 0,
  status: "completed",
} as Research;

const textResult: TextResult = { kind: "text", text: "ok" };

function createFakeClient(): ExaClient {
  return {
    search: async () => ({ kind: "search", data: searchResponse }),
    getContents: async () => ({ kind: "search", data: searchResponse }),
    answer: async () => answerResponse,
    research: {
      create: async () => ({ kind: "research", data: researchResponse }),
      get: async () => ({ kind: "research", data: researchResponse }),
    },
    deepSearch: async () => textResult,
    codeContext: async () => textResult,
    companyResearch: async () => textResult,
    linkedinSearch: async () => textResult,
  };
}

function mockConsole() {
  const logSpy = spyOn(console, "log").mockImplementation(() => {});
  const errorSpy = spyOn(console, "error").mockImplementation(() => {});
  return {
    restore: () => {
      logSpy.mockRestore();
      errorSpy.mockRestore();
    },
  };
}

describe("runExa", () => {
  afterEach(() => {
    delete process.env.EXA_API_KEY;
  });

  it("returns error when missing api key", async () => {
    const consoleMock = mockConsole();
    const code = await runExa(["search", "hello"], () => createFakeClient());
    consoleMock.restore();
    expect(code).toBe(1);
  });

  it("returns error on bad args", async () => {
    const consoleMock = mockConsole();
    const code = await runExa([], () => createFakeClient());
    consoleMock.restore();
    expect(code).toBe(1);
  });

  it("handles search", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const code = await runExa(["search", "hello"], () => createFakeClient());
    consoleMock.restore();
    expect(code).toBe(0);
  });

  it("handles contents", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const code = await runExa(
      ["contents", "https://example.com", "--text-max", "1000"],
      () => createFakeClient(),
    );
    consoleMock.restore();
    expect(code).toBe(0);
  });

  it("handles answer", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const code = await runExa(["answer", "hello"], () => createFakeClient());
    consoleMock.restore();
    expect(code).toBe(0);
  });

  it("handles research-start", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const code = await runExa(["research-start", "do", "work"], () =>
      createFakeClient(),
    );
    consoleMock.restore();
    expect(code).toBe(0);
  });

  it("handles research-check", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const code = await runExa(["research-check", "task"], () =>
      createFakeClient(),
    );
    consoleMock.restore();
    expect(code).toBe(0);
  });

  it("handles deep-search", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const code = await runExa(["deep-search", "find", "docs"], () =>
      createFakeClient(),
    );
    consoleMock.restore();
    expect(code).toBe(0);
  });

  it("handles code-context", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const code = await runExa(["code-context", "query"], () =>
      createFakeClient(),
    );
    consoleMock.restore();
    expect(code).toBe(0);
  });

  it("handles company-research", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const code = await runExa(["company-research", "Acme"], () =>
      createFakeClient(),
    );
    consoleMock.restore();
    expect(code).toBe(0);
  });

  it("handles linkedin-search", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const code = await runExa(["linkedin-search", "Jane"], () =>
      createFakeClient(),
    );
    consoleMock.restore();
    expect(code).toBe(0);
  });

  it("handles thrown errors", async () => {
    process.env.EXA_API_KEY = "test";
    const consoleMock = mockConsole();
    const client: ExaClient = {
      search: async () => {
        throw new Error("boom");
      },
      getContents: async () => ({ kind: "search", data: searchResponse }),
      answer: async () => answerResponse,
      research: {
        create: async () => ({ kind: "research", data: researchResponse }),
        get: async () => ({ kind: "research", data: researchResponse }),
      },
      deepSearch: async () => textResult,
      codeContext: async () => textResult,
      companyResearch: async () => textResult,
      linkedinSearch: async () => textResult,
    };

    const code = await runExa(["search", "hello"], () => client);
    consoleMock.restore();
    expect(code).toBe(1);
  });
});

describe("dispatchCommand", () => {
  it("throws on unsupported command kinds", async () => {
    const unexpected = async () => {
      throw new Error("unexpected");
    };
    const client: ExaClient = {
      search: unexpected,
      getContents: unexpected,
      answer: unexpected,
      research: {
        create: unexpected,
        get: unexpected,
      },
      deepSearch: unexpected,
      codeContext: unexpected,
      companyResearch: unexpected,
      linkedinSearch: unexpected,
    };
    const badCommand = { kind: "nope" } as unknown as Command;
    await expect(dispatchCommand(badCommand, client)).rejects.toThrow(
      "Unsupported command: nope",
    );
  });
});
