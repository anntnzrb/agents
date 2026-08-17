import type {
  BeforeAgentStartEvent,
  BeforeAgentStartEventResult,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";

type TransformEvent = Pick<BeforeAgentStartEvent, "images" | "prompt" | "systemPrompt">;

interface TransformMapping {
  readonly systemPromptSuffix: string;
}

const TRANSFORM_MAPPINGS: ReadonlyMap<string, TransformMapping> = new Map([
  [
    ".",
    {
      systemPromptSuffix: `<system-notice>
MUST resume the most recent intent and complete unfinished work.
If interrupted mid-step, resume where stopped.
NEVER pause to summarize progress, re-confirm the plan, or ask whether to proceed.
</system-notice>`,
    },
  ],
]);

export function applyTransform(
  event: TransformEvent,
): BeforeAgentStartEventResult | undefined {
  if ((event.images?.length ?? 0) > 0) {
    return;
  }

  const mapping = TRANSFORM_MAPPINGS.get(event.prompt.trim());
  if (!mapping) {
    return;
  }

  return {
    systemPrompt: `${event.systemPrompt}\n\n${mapping.systemPromptSuffix}`,
  };
}

const tmap: ExtensionFactory = (pi) => {
  pi.on("before_agent_start", applyTransform);
};

export default tmap;
