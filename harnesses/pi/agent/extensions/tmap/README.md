# Pi transform mapping extension

`tmap` means **transform mapping**. It maps a short, image-free user input string to a run-local system-prompt suffix. Surrounding whitespace is ignored when matching a key.

Mappings live in the typed `TRANSFORM_MAPPINGS` map in `index.ts`. Add a table entry to define another system-level transform; do not add another event-handler branch. Unmapped input, including `!`, passes through unchanged.

The only current mapping is `.`. Pi keeps the period as the real user turn that starts the agent loop. The extension does not rewrite or hide that message. Instead, Pi's `before_agent_start` event adds a system-priority instruction to resume the most recent intent without another plan or confirmation.

This design uses Pi's provider-independent extension API. The exported `applyTransform()` function derives its input and output from Pi's `BeforeAgentStartEvent` and `BeforeAgentStartEventResult` types. The extension factory uses Pi's `ExtensionFactory` type. It does not mutate provider payloads or add hidden custom messages, which Pi would serialize as user messages rather than system instructions.
