---
name: how
description: "Use when the user asks how something works, wants a walkthrough before changes, or requests design critique."
license: AGPL-3.0-or-later
---

# How

Explore the codebase to answer "how does X work?" questions. Produce clear architectural explanations at the level of a senior engineer onboarding onto a subsystem. Enough to build a working mental model, not annotated source code.

Two modes:

1. **Explain** (default). Explore the codebase and produce a clear explanation.
2. **Critique.** Explain first, then spawn independent critics to identify architectural issues.

Adapted from pstack (Lauren Tan, MIT): model-pinned Cursor subagents replaced with plain read-only subagents.

## Explain Mode

### Step 1. Understand the Question and Assess Complexity

Parse what the user is asking about:

- "How does the rate limiter work?", a subsystem
- "How do we handle billing for on-demand usage?", a feature flow
- "How is the auth service structured?", an architectural overview
- "Walk me through what happens when a user submits a form", a runtime trace

Identify the scope. If ambiguous, state your best-guess interpretation before exploring. Don't ask. Let the user redirect if you're off.

**Assess complexity to decide the approach:**

- **Simple** (a single module, a small utility, a narrow question like "how does function X work"): skip explorer agents; explore and explain in a single pass. Go to Step 2b.
- **Complex** (a subsystem spanning multiple files/services, a cross-cutting feature, a full architectural overview): spawn parallel explorer agents first, then synthesize. Go to Step 2a.

When in doubt, lean simple. You can always spawn explorers if you hit a wall.

### Step 2a. Explore (complex questions only)

Decompose the question into 2-4 parallel exploration angles, each a distinct slice of the subsystem so explorers don't duplicate work. Example split for "how does the rate limiter work?":

- Explorer 1: data model and state management
- Explorer 2: request path and enforcement
- Explorer 3: configuration and metrics infrastructure

The right decomposition depends on the question. Use your judgment. Narrow questions: 2 explorers is fine. Broad subsystems: up to 4.

Spawn all explorers in a single message with `subagent_type: explore` (read-only). Each explorer gets the same base instructions plus a specific angle naming its slice. Each explorer should:

- Start broad: Glob for relevant directories, Grep for key types/interfaces/class names
- Follow the thread: from an entry point, trace the call chain (callers, callees, data flow, type definitions)
- Read the actual code, don't guess from file names
- Stop when it can describe the full path from input to output (or trigger to effect) without hand-waving any step
- Note things that are surprising, non-obvious, or that a newcomer would get wrong

Each explorer returns structured findings: components found, flow traced, files read, anything non-obvious. Overlap between explorers is fine; you reconcile it.

Then proceed to Step 3.

### Step 2b. Direct Explain (simple questions)

Spawn a single read-only subagent (`subagent_type: explore`) that explores and explains in one pass. It does its own exploration (Glob, Grep, Read) and writes the explanation directly in the output format below. Same structure, just no explorer findings as input.

Proceed to Step 4.

### Step 3. Synthesize (complex questions only)

Once all explorers return, write one coherent explanation from their findings (output format below). Reconcile overlapping findings, resolve contradictions, and weave the slices into a unified picture. Keep summaries in the main thread, not raw payloads.

### Step 4. Present

Present the explanation to the user. The explanation is the product.

### Output Format

Follow this structure, adapted to the question. Not every section is needed for every question.

**Overview.** 1-2 paragraphs. What it is, what it does, why it exists. Enough to decide whether to keep reading.

**Key Concepts.** The important types, services, or abstractions. Brief definition of each. Not exhaustive, just the ones needed to understand the rest.

**How It Works.** The core of the explanation. Walk through the flow: what triggers it, what happens step by step, where data goes, the decision points. Prose, not pseudocode. Reference specific files and functions so the reader can go look, but don't dump code blocks unless a snippet is genuinely necessary.

**Where Things Live.** A brief map of the relevant files/directories. Not every file, just the ones needed to start working in this area.

**Gotchas.** Non-obvious or surprising things that would trip someone up. Historical context that explains why something looks weird. Known sharp edges.

## Critique Mode

Triggered when the user asks for architectural issues, problems, or improvements, not just understanding.

### Step 1. Explain First

Run the full explain flow above. You must understand the architecture before critiquing it.

### Step 2. Spawn Critics

After the explanation is complete, spawn 2-3 independent critics in parallel (`subagent_type: general`, read-only). Each critic gets:

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
