---
name: pstack-principles
description: "Apply before design, refactor, debug, or delegation: smallest change, correct types, verify real artifacts, root causes."
license: MIT
---

# Pstack Principles

Twenty-one engineering principles from pstack (Lauren Tan, MIT). One bundled skill, not twenty-one, to protect the skill-inventory metadata budget.

**Rules of use:**

- Match the task to rows whose When column fits. Read the referenced file in full before applying. Applying from the index line alone is not allowed.
- When you report, name each principle that shaped a decision and the specific choice it changed. A citation with no decision behind it means you skipped the leaf file.
- If principles conflict, the smaller change wins unless a verification principle says otherwise.
- Ported from https://github.com/cursor/plugins/tree/main/pstack (MIT). Cross-references point to local files.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Laziness Protocol rule | [references/principle-laziness-protocol.md](references/principle-laziness-protocol.md) | Refactoring, sizing a diff, or tempted to add abstractions, layers, or signal threading |
| Foundational Thinking rule | [references/principle-foundational-thinking.md](references/principle-foundational-thinking.md) | Before writing logic: core types and data structures, scaffold-vs-feature sequencing, what concurrent actors share |
| Redesign from First Principles rule | [references/principle-redesign-from-first-principles.md](references/principle-redesign-from-first-principles.md) | Integrating a new requirement into an existing design |
| Subtract Before You Add rule | [references/principle-subtract-before-you-add.md](references/principle-subtract-before-you-add.md) | Sequencing an addition, refactor, or rewrite |
| Minimize Reader Load rule | [references/principle-minimize-reader-load.md](references/principle-minimize-reader-load.md) | Reviewing or shaping code that is hard to trace |
| Outcome-Oriented Execution rule | [references/principle-outcome-oriented-execution.md](references/principle-outcome-oriented-execution.md) | Planned rewrites and migrations with explicit phase boundaries |
| Experience First rule | [references/principle-experience-first.md](references/principle-experience-first.md) | Product, UX, or feature-scope tradeoffs |
| Exhaust the Design Space rule | [references/principle-exhaust-the-design-space.md](references/principle-exhaust-the-design-space.md) | A novel interaction or architectural decision with no precedent |
| Build the Lever rule | [references/principle-build-the-lever.md](references/principle-build-the-lever.md) | Any non-trivial work: edits, migrations, analyses, checks |
| Model the Domain rule | [references/principle-model-the-domain.md](references/principle-model-the-domain.md) | Writing stateful logic, or code that branches a lot or repeats a shape assumption across files |
| Boundary Discipline rule | [references/principle-boundary-discipline.md](references/principle-boundary-discipline.md) | Wiring validation, error handling, or framework adapters |
| Type System Discipline rule | [references/principle-type-system-discipline.md](references/principle-type-system-discipline.md) | Designing types or a signature in any typed language |
| Make Operations Idempotent rule | [references/principle-make-operations-idempotent.md](references/principle-make-operations-idempotent.md) | Designing commands, lifecycle steps, or loops that run amid crashes and retries |
| Migrate Callers Then Delete Legacy APIs rule | [references/principle-migrate-callers-then-delete-legacy-apis.md](references/principle-migrate-callers-then-delete-legacy-apis.md) | Introducing a new internal API while old callers exist |
| Separate Before Serializing Shared State rule | [references/principle-separate-before-serializing-shared-state.md](references/principle-separate-before-serializing-shared-state.md) | Concurrent actors might write the same file, branch, key, or object |
| Prove It Works rule | [references/principle-prove-it-works.md](references/principle-prove-it-works.md) | After a task, before declaring done |
| Fix Root Causes rule | [references/principle-fix-root-causes.md](references/principle-fix-root-causes.md) | Debugging: trace each symptom to its root cause |
| Sequence Work into Verifiable Units rule | [references/principle-sequence-verifiable-units.md](references/principle-sequence-verifiable-units.md) | Multi-step work and how you stack commits and PRs |
| Guard the Context Window rule | [references/principle-guard-the-context-window.md](references/principle-guard-the-context-window.md) | Context fills up: large outputs, long files, repeated reads, fan-out planning |
| Never Block on the Human rule | [references/principle-never-block-on-the-human.md](references/principle-never-block-on-the-human.md) | Tempted to ask "should I do X?" on reversible work |
| Encode Lessons in Structure rule | [references/principle-encode-lessons-in-structure.md](references/principle-encode-lessons-in-structure.md) | You catch yourself writing the same instruction a second time |
