import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const GUIDANCE = `Choose the search tool by intent, then keep commands focused and non-interactive:
- Meaning or behavior, unknown wording/location: use the semantic find tool first, including for code, docs, logs, and session transcripts. Known literal or identifier: use rg. Exact counts or structured analysis: use jq or a script after discovery.
- Known text: prefer rg -n over grep; add -F for literals, use -l for filenames only, or -q for existence.
- Repository paths: rg --files -g 'PATTERN'. General filesystem discovery: fd when available; retain find for predicates and actions.
- rg and fd skip hidden and ignored files by default. Include them explicitly when needed; incomplete searches do not prove absence.
- Syntax-shaped code search: prefer ast-grep over regex; scope to a path and language. Invalid patterns are query failures, not no matches.
- JSON inspection: prefer jq over regex or bespoke scripts.
- Narrow paths, globs, and output first. Bound large results; rg -m caps matches per file, not total output.
- Chain dependent commands with && so failure stops the chain.
- Fall back when unavailable or unsuitable. Use Python for transformations, not merely file dumps.
These are preferences, not bans. Preserve existing read, semantic search, editing, and codemode guidance.`;

export default function pharos(pi: ExtensionAPI) {
  pi.on("before_agent_start", (event) => {
    if (event.systemPromptOptions.selectedTools.includes("bash")) {
      event.systemPromptOptions.sections.pharos = GUIDANCE;
    } else {
      delete event.systemPromptOptions.sections.pharos;
    }
  });
}
