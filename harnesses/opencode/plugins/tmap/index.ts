import { Plugin } from "@opencode/plugin";

const MANUAL_CONTINUE_PROMPT = `<system-notice>
Continue.

MUST resume most recent intent; complete unfinished work.
If interrupted mid-step: resume where stopped.
NEVER pause to summarize progress, re-confirm plan, or ask whether to proceed; continue.
</system-notice>`;

export default Plugin.define({
  id: "tmap",
  async setup(ctx) {
    await ctx.session.hook("context", (event) => {
      const index = event.messages.findLastIndex((message) => message.role === "user");
      const message = event.messages[index];
      if (!message || message.content.length !== 1) return;
      const part = message.content[0];
      if (part?.type !== "text" || part.text.trim() !== ".") return;

      // Change only model-visible context. Keep the submitted dot in history;
      // v2 prompt admission has no v1 synthetic/system-message fields.
      event.messages[index] = { ...message, content: [{ ...part, text: "Continue." }] };
      event.system.push({ type: "text", text: MANUAL_CONTINUE_PROMPT });
    });
  },
});
