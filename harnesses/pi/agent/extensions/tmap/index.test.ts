import { expect, test } from "bun:test";
import type { BeforeAgentStartEvent } from "@earendil-works/pi-coding-agent";
import { applyTransform } from "./index.ts";

const BASE_SYSTEM_PROMPT = "Base system prompt";
const CONTINUATION_RESULT = {
  systemPrompt: `Base system prompt\n\n<system-notice>
MUST resume the most recent intent and complete unfinished work.
If interrupted mid-step, resume where stopped.
NEVER pause to summarize progress, re-confirm the plan, or ask whether to proceed.
</system-notice>`,
};

type Images = BeforeAgentStartEvent["images"];

function transform(prompt: string, images?: Images) {
  const event = { prompt, systemPrompt: BASE_SYSTEM_PROMPT };
  return images === undefined ? applyTransform(event) : applyTransform({ ...event, images });
}

test("maps one dot surrounded only by whitespace", () => {
  for (const prompt of [".", " .", ". ", " . ", "\t.\t", "\n.\n", "\n \t.\t \n", "\u00a0.\u00a0"]) {
    expect(transform(prompt)).toEqual(CONTINUATION_RESULT);
  }
});

test("maps an image-free dot with an empty image list", () => {
  expect(transform(" . ", [])).toEqual(CONTINUATION_RESULT);
});

test("does not map empty or whitespace-only messages", () => {
  for (const prompt of ["", " ", "\t", "\n", " \n\t "]) {
    expect(transform(prompt)).toBe(undefined);
  }
});

test("does not map multiple dots or dots separated by whitespace", () => {
  for (const prompt of ["..", "...", " . . ", ".\n.", "\n.\n."]) {
    expect(transform(prompt)).toBe(undefined);
  }
});

test("does not map a dot embedded in ordinary text or a paragraph", () => {
  for (const prompt of [
    ".text",
    "text.",
    "text .",
    "text . text",
    "This is a sentence.",
    "One paragraph.\n\nAnother paragraph.",
    "Use ./relative/path.",
    "Version 1.2 is installed.",
    "A quoted full stop: \".\"",
  ]) {
    expect(transform(prompt)).toBe(undefined);
  }
});

test("leaves currently unmapped trigger candidates unchanged", () => {
  for (const prompt of ["!", " ! ", "?", "#", "@", "~"]) {
    expect(transform(prompt)).toBe(undefined);
  }
});

test("does not map a dot when the user attaches an image", () => {
  const image = {
    type: "image",
    data: "ignored",
    mimeType: "image/png",
  } satisfies NonNullable<Images>[number];

  for (const prompt of [".", " . ", "\n.\n"]) {
    expect(transform(prompt, [image])).toBe(undefined);
  }
});

test("does not modify the system prompt for an unmapped message", () => {
  expect(transform("Keep going")).toBe(undefined);
  expect(transform("!")).toBe(undefined);
});
