import { expect, test } from "bun:test";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import { isRetryableAssistantError } from "@earendil-works/pi-ai";
import { markTransientStreamError } from "./retry.ts";

const failed = (errorMessage: string, provider = "cliproxy"): AssistantMessage =>
  ({ role: "assistant", provider, stopReason: "error", errorMessage }) as AssistantMessage;

test("gateway stream drops become errors Pi's retry policy accepts", () => {
  for (const drop of [
    "read tcp 10.0.0.1:443: use of closed network connection",
    "stream disconnected before completion: stream closed before response.completed",
    "invalid SSE data JSON",
  ]) {
    expect(isRetryableAssistantError(failed(drop))).toBe(false);
    const marked = markTransientStreamError(failed(drop));
    expect(marked).toBeDefined();
    expect(isRetryableAssistantError(marked!)).toBe(true);
  }
});

test("other errors, other providers, and successful turns pass through unchanged", () => {
  expect(markTransientStreamError(failed("invalid api key"))).toBeUndefined();
  expect(markTransientStreamError(failed("invalid SSE data JSON", "openai"))).toBeUndefined();
  expect(markTransientStreamError({ ...failed("invalid SSE data JSON"), stopReason: "stop" })).toBeUndefined();
  // Already retryable: no double prefix.
  expect(markTransientStreamError(failed("503 service unavailable"))).toBeUndefined();
});
