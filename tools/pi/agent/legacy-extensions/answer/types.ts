/**
 * Shared types for the answer extension.
 */

import type { ExtensionContext } from "@mariozechner/pi-coding-agent";

/** Structured output format for question extraction. */
export interface ExtractedQuestion {
  question: string;
  context?: string;
}

/** Extraction response shape. */
export interface ExtractionResult {
  questions: ExtractedQuestion[];
}

export type ActiveModel = NonNullable<ExtensionContext["model"]>;
