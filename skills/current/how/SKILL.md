---
name: how
description: "Use when explaining how a subsystem works, tracing runtime code flow, or critiquing design, not for git history."
license: AGPL-3.0-or-later
---

# How

Explore the codebase to answer "how does X work?" questions. Produce clear architectural explanations at the level of a senior engineer onboarding onto a subsystem. Enough to build a working mental model, not annotated source code.

Two modes:

1. **Explain** (default). Explore the codebase and produce a clear explanation.
2. **Critique.** Explain first, then spawn independent critics to identify architectural issues.

Adapted from pstack (Lauren Tan, MIT): model-pinned Cursor subagents replaced with plain read-only subagents.

## Explain mode

### 1. Assess complexity

If the scope is ambiguous, state your interpretation and explore. The user can redirect.

- **Simple** (a single module, a small utility, or a narrow function question): explore and explain in one pass. Use a dedicated read-only subagent when supported, or work directly. Go to step 4.
- **Complex** (a subsystem spanning files or services, a cross-cutting feature, or an architectural overview): go to step 2.

When in doubt, take the simple path.

### 2. Explore (complex only)

Decompose the question into 2 to 4 angles, each a distinct slice of the subsystem. Spawn read-only explorers in parallel when supported; otherwise run the passes sequentially. Give each explorer its angle and these instructions:

- Use `rg --files` to find relevant files and `rg` to locate types, interfaces, and entry points.
- Trace callers, callees, data flow, and type definitions from an entry point.
- Read the actual code. Do not guess from file names.
- Stop when you can describe every step from input to output, or trigger to effect.
- Return the components, flow, files read, and facts a newcomer could miss.

### 3. Synthesize (complex only)

Once all explorers return, reconcile overlaps and contradictions into one explanation. Keep summaries in the main thread, not raw payloads.

### 4. Present

Present the explanation using the sections below. Drop any section that does not help answer the question.

### Output format

**Overview.** 1-2 paragraphs on what the subsystem does and why it exists.

**Key concepts.** Define the types, services, or abstractions needed to understand the flow.

**How it works.** Explain the trigger, each step, data movement, and decision points. Cite files and functions. Include code only when a snippet is essential.

**Where things live.** Map the files and directories a reader needs to start exploring.

**Gotchas.** Explain surprising behavior, relevant historical context, and known pitfalls.


## Critique Mode

Triggered when the user asks for architectural issues, problems, or improvements, not just understanding.

### Step 1. Explain First

Run the explain flow above. You must understand the architecture before critiquing it.

### Step 2. Spawn Critics

After the explanation is complete, spawn 2-3 independent read-only critics in parallel when supported; otherwise run the critique passes sequentially yourself. Each critic gets:

1. The explanation from Step 1 (so they don't re-explore)
2. The relevant file paths (so they can read the actual code)
3. The rubric below

Rubric, one lens per critic where possible:

- Coupling and hidden dependencies: what breaks when one module changes
- Invariants and illegal states: which combinations are possible that shouldn't be
- Boundary leaks: validation or transformation logic living outside the boundary it belongs at
- Testability and observability: what can't be verified or watched
- Ownership and naming: files, packages, and layers that fight their stated responsibility

### Step 3. Lead Judgment

You're a pragmatic lead, not an aggregator. Categorize findings:

- **Act on.** Architectural problems worth fixing now
- **Consider.** Real concerns, but the cost/benefit is unclear
- **Noted.** Valid observations, low priority
- **Dismissed.** Wrong, missing context, or style preference

Present the explanation first (from Step 1), then the critique verdict below it. The explanation should stand on its own; someone who just wants to understand the system shouldn't wade through critique.
