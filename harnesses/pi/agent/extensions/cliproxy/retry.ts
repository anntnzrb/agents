import { type AssistantMessage, isRetryableAssistantError } from "@earendil-works/pi-ai";

// Gateway errors Pi's retry policy does not recognize. Pi handles stream disconnects itself.
const TRANSIENT_STREAM_ERROR =
	/\bclosed network connection\b|\binvalid SSE data JSON\b/i;
// "network error" is one of the patterns Pi's retry policy already treats as transient.
const RETRYABLE_PREFIX = "network error:";

/** Return the turn with a retryable error message, or undefined when it needs no change. */
export function markTransientStreamError(message: AssistantMessage): AssistantMessage | undefined {
	if (message.provider !== "cliproxy" || message.stopReason !== "error" || !message.errorMessage) return undefined;
	if (isRetryableAssistantError(message) || !TRANSIENT_STREAM_ERROR.test(message.errorMessage)) return undefined;
	return { ...message, errorMessage: `${RETRYABLE_PREFIX} ${message.errorMessage}` };
}
