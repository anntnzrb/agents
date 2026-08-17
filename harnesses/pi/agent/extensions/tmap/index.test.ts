import assert from "node:assert/strict";
import { test } from "node:test";
import { applyTransform } from "./index.ts";

test("single-dot input adds a one-turn system-priority continuation", () => {
  assert.deepEqual(
    applyTransform({
      prompt: " . ",
      images: [],
      systemPrompt: "Base system prompt",
    }),
    {
      systemPrompt: `Base system prompt\n\n<system-notice>
MUST resume the most recent intent and complete unfinished work.
If interrupted mid-step, resume where stopped.
NEVER pause to summarize progress, re-confirm the plan, or ask whether to proceed.
</system-notice>`,
    },
  );

  assert.equal(
    applyTransform({
      prompt: "Keep going",
      systemPrompt: "Base system prompt",
    }),
    undefined,
  );
});

test("unmapped and image-bearing input does not modify the system prompt", () => {
  for (const prompt of ["Keep going", "!"]) {
    assert.equal(
      applyTransform({
        prompt,
        systemPrompt: "Base system prompt",
      }),
      undefined,
    );
  }

  assert.equal(
    applyTransform({
      prompt: ".",
      images: [{ type: "image", data: "ignored", mimeType: "image/png" }],
      systemPrompt: "Base system prompt",
    }),
    undefined,
  );
});
