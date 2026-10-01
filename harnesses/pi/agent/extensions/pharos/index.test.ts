import { expect, test } from "bun:test";
import type { BeforeAgentStartEvent, ExtensionAPI } from "@earendil-works/pi-coding-agent";
import pharos from "./index.ts";

function load() {
  let handler: ((event: BeforeAgentStartEvent) => unknown) | undefined;
  const api = {
    on(name: string, callback: (event: BeforeAgentStartEvent) => unknown) {
      if (name === "before_agent_start") handler = callback;
      return () => {};
    },
  };
  pharos(api as ExtensionAPI);
  return (event: BeforeAgentStartEvent) => {
    if (!handler) throw new Error("Pharos did not register its prompt hook");
    return handler(event);
  };
}

function event(selectedTools: string[]): BeforeAgentStartEvent {
  return {
    type: "before_agent_start",
    prompt: "Find a file",
    systemPrompt: "Existing prompt",
    systemPromptOptions: {
      cwd: "/tmp",
      selectedTools,
      toolSnippets: {},
      toolGuidelines: {},
      sections: { project_rules: "Keep these rules" },
      promptGuidelines: ["Keep this guideline"],
      appendSystemPrompt: "",
      contextFiles: [],
      skills: [],
    },
  };
}

test("adds a guidance section without replacing the prompt or other guidance", () => {
  const run = load();
  const input = event(["bash", "read"]);
  expect(run(input)).toBeUndefined();
  expect(Object.keys(input.systemPromptOptions.sections)).toEqual(["project_rules", "pharos"]);
  expect(input.systemPromptOptions.sections.pharos).toEqual(expect.any(String));
  expect(input.systemPromptOptions.sections.project_rules).toBe("Keep these rules");
  expect(input.systemPromptOptions.promptGuidelines).toEqual(["Keep this guideline"]);
  expect(input.systemPrompt).toBe("Existing prompt");
});

test("repeated starts do not accumulate guidance", () => {
  const run = load();
  const input = event(["bash"]);
  run(input);
  const first = structuredClone(input.systemPromptOptions);
  run(input);
  expect(Object.keys(input.systemPromptOptions.sections)).toEqual(["project_rules", "pharos"]);
  expect(input.systemPromptOptions).toEqual(first);
});

test("removes only its own section when bash is no longer active", () => {
  const run = load();
  const input = event(["bash"]);
  run(input);
  expect(Object.keys(input.systemPromptOptions.sections)).toEqual(["project_rules", "pharos"]);
  input.systemPromptOptions.selectedTools = ["read"];
  run(input);
  expect(input.systemPromptOptions.sections).toEqual({ project_rules: "Keep these rules" });
});
