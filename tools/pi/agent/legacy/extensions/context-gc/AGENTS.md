# Context GC Extension

## Purpose
Silent always-on context garbage-collector for Pi sessions:
- batch large tool-result output after agent work completes
- compact noisy tool output once it is stale
- remove compacted raw `toolResult` messages from future provider context
- preserve exact originals in non-context session custom entries for recovery

## File map
- `index.ts`: Pi event/tool wiring; minimal mutable runtime state
- `logic.ts`: pure capture, threshold, compact, serialization helpers
- `indexer.ts`: session-backed tool-result index and recovery formatting
- `summarizer.ts`: deterministic compact summary generation; no model-call tax
- `index.test.ts`: pure behavior tests

## Navigation
Start with `index.ts`, then `logic.ts` for behavior invariants.

## Policy
No modes. No enable/disable flag. No settings file. No UI cockpit.
If this extension is loaded, it applies its fixed policy.
