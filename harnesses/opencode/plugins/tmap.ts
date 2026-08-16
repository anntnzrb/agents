import type { Plugin } from "@opencode-ai/plugin";

const MANUAL_CONTINUE_PROMPT = `<system-notice>
Continue.

MUST resume most recent intent; complete unfinished work.
If interrupted mid-step: resume where stopped.
NEVER pause to summarize progress, re-confirm plan, or ask whether to proceed; continue.
</system-notice>`;

export const Tmap: Plugin = async () => ({
  "chat.message": async (_input, output) => {
    if (output.parts.length !== 1) return;

    const part = output.parts[0];
    if (part?.type !== "text" || part.text.trim() !== ".") return;

    // a user turn is needed to start the loop, but synthetic text stays
    // hidden in the TUI while the instruction receives system priority.
    part.text = "Continue.";
    part.synthetic = true;
    output.message.system = output.message.system
      ? `${output.message.system}\n\n${MANUAL_CONTINUE_PROMPT}`
      : MANUAL_CONTINUE_PROMPT;
  },
});
