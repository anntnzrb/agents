import { complete, type Message } from "@mariozechner/pi-ai";
import type { ExtensionAPI, SessionEntry } from "@mariozechner/pi-coding-agent";
import {
	BorderedLoader,
	convertToLlm,
	serializeConversation,
} from "@mariozechner/pi-coding-agent";

const SYSTEM_PROMPT = `You are a context transfer assistant. Given a conversation history and the user's goal for a new thread, generate a focused prompt that:

1. Summarizes relevant context from the conversation (decisions made, approaches taken, key findings)
2. Lists any relevant files that were discussed or modified
3. Clearly states the next task based on the user's goal
4. Is self-contained - the new thread should be able to proceed without the old conversation

Format your response as a prompt the user can send to start the new thread. Be concise but include all necessary context. Do not include any preamble like "Here's the prompt" - just output the prompt itself.

Example output format:
## Context
We've been working on X. Key decisions:
- Decision 1
- Decision 2

Files involved:
- path/to/file1.ts
- path/to/file2.ts

## Task
[Clear description of what to do next based on the user's goal]`;

type CommandCheckResult = { ok: true; goal: string } | { ok: false; message: string };
type PromptGenerationInput = {
	conversationText: string;
	goal: string;
};

const isMessageEntry = (
	entry: SessionEntry,
): entry is SessionEntry & { type: "message" } => entry.type === "message";

const getMessages = (entries: readonly SessionEntry[]): readonly Message[] =>
	entries.filter(isMessageEntry).map((entry) => entry.message);

const buildPromptGenerationMessage = (input: PromptGenerationInput): Message => ({
	role: "user",
	content: [
		{
			type: "text",
			text: `## Conversation History\n\n${input.conversationText}\n\n## User's Goal for New Thread\n\n${input.goal}`,
		},
	],
	timestamp: Date.now(),
});

const validateCommand = (args: string): CommandCheckResult => {
	const goal = args.trim();
	return goal ? { ok: true, goal } : { ok: false, message: "Usage: /handoff <goal for new thread>" };
};

const getConversationText = (entries: readonly SessionEntry[]): string =>
	serializeConversation(convertToLlm(getMessages(entries)));

const generateHandoffPrompt = async (
	ctx: Parameters<Parameters<ExtensionAPI["registerCommand"]>[1]["handler"]>[1],
	input: PromptGenerationInput,
): Promise<string | null> =>
	ctx.ui.custom<string | null>((tui, theme, _keybindings, done) => {
		const loader = new BorderedLoader(tui, theme, "Generating handoff prompt...");
		loader.onAbort = () => done(null);

		const run = async () => {
			if (!ctx.model) return null;
			const apiKey = await ctx.modelRegistry.getApiKey(ctx.model);
			const response = await complete(
				ctx.model,
				{
					systemPrompt: SYSTEM_PROMPT,
					messages: [buildPromptGenerationMessage(input)],
				},
				{ apiKey, signal: loader.signal },
			);

			if (response.stopReason === "aborted") return null;
			return response.content
				.filter((part): part is { type: "text"; text: string } => part.type === "text")
				.map((part) => part.text)
				.join("\n");
		};

		run()
			.then(done)
			.catch((error) => {
				console.error("Handoff generation failed:", error);
				done(null);
			});

		return loader;
	});

export default function handoffExtension(pi: ExtensionAPI) {
	pi.registerCommand("handoff", {
		description: "Transfer context to a new focused session",
		handler: async (args, ctx) => {
			if (!ctx.hasUI) {
				ctx.ui.notify("handoff requires interactive mode", "error");
				return;
			}

			if (!ctx.model) {
				ctx.ui.notify("No model selected", "error");
				return;
			}

			const commandCheck = validateCommand(args);
			if (!commandCheck.ok) {
				ctx.ui.notify(commandCheck.message, "error");
				return;
			}

			const branch = ctx.sessionManager.getBranch();
			const messages = getMessages(branch);
			if (messages.length === 0) {
				ctx.ui.notify("No conversation to hand off", "error");
				return;
			}

			const generatedPrompt = await generateHandoffPrompt(ctx, {
				conversationText: getConversationText(branch),
				goal: commandCheck.goal,
			});
			if (generatedPrompt === null) {
				ctx.ui.notify("Cancelled", "info");
				return;
			}

			const editedPrompt = await ctx.ui.editor("Edit handoff prompt", generatedPrompt);
			if (editedPrompt === undefined) {
				ctx.ui.notify("Cancelled", "info");
				return;
			}

			const newSessionResult = await ctx.newSession({
				parentSession: ctx.sessionManager.getSessionFile(),
			});
			if (newSessionResult.cancelled) {
				ctx.ui.notify("New session cancelled", "info");
				return;
			}

			ctx.ui.setEditorText(editedPrompt);
			ctx.ui.notify("Handoff ready. Submit when ready.", "info");
		},
	});
}
