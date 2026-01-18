import { createExaClient } from "@/client";
import { parseCommand, usage } from "@/args";
import {
  formatAnswerResponse,
  formatResearchOutput,
  formatSearchOutput,
  formatTextResult,
} from "@/format";
import type { Command, ExaClient } from "@/types";

export async function runExa(
  argv: string[],
  clientFactory: (apiKey: string) => ExaClient = createExaClient,
): Promise<number> {
  const parsed = parseCommand(argv);
  if (!parsed.ok) {
    console.log(usage());
    console.log(`\nError: ${parsed.error}`);
    return 1;
  }

  const apiKey = process.env.EXA_API_KEY?.trim();
  if (!apiKey) {
    console.log(usage());
    console.log("\nError: EXA_API_KEY is required.");
    return 1;
  }

  const client = clientFactory(apiKey);

  try {
    return await dispatchCommand(parsed.value, client);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Error: ${message}`);
    return 1;
  }
}

export async function dispatchCommand(
  command: Command,
  client: ExaClient,
): Promise<number> {
  switch (command.kind) {
    case "search": {
      const response = await client.search(command.query, command.options);
      console.log(formatSearchOutput(response));
      return 0;
    }
    case "contents": {
      const response = await client.getContents(command.urls, command.options);
      console.log(formatSearchOutput(response));
      return 0;
    }
    case "answer": {
      const response = await client.answer(command.query, command.options);
      console.log(formatAnswerResponse(response));
      return 0;
    }
    case "research-start": {
      const payload = {
        instructions: command.instructions,
        ...(command.options.model ? { model: command.options.model } : {}),
      };
      const response = await client.research.create(payload);
      console.log(formatResearchOutput(response));
      return 0;
    }
    case "research-check": {
      const response = await client.research.get(command.id, {
        stream: false,
      });
      console.log(formatResearchOutput(response));
      return 0;
    }
    case "deep-search": {
      const response = await client.deepSearch(
        command.objective,
        command.queries,
      );
      console.log(formatTextResult(response));
      return 0;
    }
    case "code-context": {
      const response = await client.codeContext(
        command.query,
        command.tokensNum,
      );
      console.log(formatTextResult(response));
      return 0;
    }
    case "company-research": {
      const response = await client.companyResearch(
        command.companyName,
        command.numResults,
      );
      console.log(formatTextResult(response));
      return 0;
    }
    case "linkedin-search": {
      const response = await client.linkedinSearch(
        command.query,
        command.searchType,
        command.numResults,
      );
      console.log(formatTextResult(response));
      return 0;
    }
    default: {
      return assertNever(command);
    }
  }
}

function assertNever(value: never): never {
  const kind = (value as { kind?: string }).kind ?? "unknown";
  throw new Error(`Unsupported command: ${kind}`);
}
