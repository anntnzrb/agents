# Cleanup Playbook

Read this before planning, modifying, or reviewing an AI-slop cleanup.

## Safety invariant

Lock behavior with green, relevant regression tests before removing a line. A checklist is not a
substitute for an observable test. If baseline validation is broken, stop and report it.

## Determine scope

Use an explicit caller file list when supplied. Otherwise derive changed files from the branch
against its default branch's merge-base, for example:

```text
git diff $(git merge-base <default-branch> HEAD)..HEAD --name-only
```

Remove deleted, binary, generated, vendored, and lock files from the list. Do not edit a file
outside scope; record an out-of-scope concern under deferred risks.

## Lock behavior

For each source file, identify observable exports, handlers, commands, or externally used classes.
Locate existing coverage using repository conventions. Before editing weakly covered behavior, add
the narrowest regression test that asserts output, effects, or errors—not implementation details.
Run relevant tests and require green. Prompts, `SKILL.md`, rules, and other prose have no behavioral
seam: do not add phrase, word-count, or text-pinning tests unless a machine consumes that value.

## Deletion ladder and plan

Evaluate each changed unit in this order:

1. **Delete entirely** — the behavior is dead, speculative, or unnecessary
2. **Reuse** — existing repository code already does the work
3. **Use platform, standard library, or installed dependency** — replace a hand-rolled duplicate
4. **Simplify in place** — only if it must remain

For a bug fix involving a shared function, inspect its callers. Prefer one root-cause repair at the
shared seam over duplicated caller guards.

Write a plan before edits for every file: ladder result, categories, safest-to-riskiest order, and
risk. If deliberately retaining a bounded shortcut, leave a `debt:` comment with its ceiling and
upgrade trigger, and report it as deferred risk.

## Categories

### 1. Obvious comments

Remove comments that restate code, trivial docstrings, section dividers, commented-out code, and
vague TODOs/notes. Keep WHY: business rules, edge cases, workarounds, ticket links, regex or
algorithm explanations, and BDD markers such as `given`, `when`, and `then`.

### 2. Over-defensive code

Remove duplicate null/type/default checks, impossible exception handling, obsolete compatibility
shims, and broad catches only when redundancy is proven. Keep boundary validation for user input,
external APIs, I/O, and nullable persisted values. Preserve a top-level CLI or HTTP boundary
catch-all only when it logs explicitly and re-raises unknown failure.

Before deleting a boundary guard or error handler, add an adversarial malformed-input regression
that fails without it. Without that proof, the guard stays. Narrow broad exception handling to
known exceptions; re-raise unknown ones.

### 3. Excessive complexity

Simplify nesting deeper than three levels, nested ternaries, booleans with four or more predicates,
parameter lists over five without a value object, multi-purpose functions over roughly 50 lines,
and clever one-liners that hide intent. Prefer guard clauses and explicit conditionals. For variant
discrimination, use the language's exhaustive matching idiom where it is established in the repo.
Replace vague `object` annotations with a protocol/interface, type parameter, or explicit union.

Keep established local patterns and intentional performance-critical idioms. Boolean/range tests
are not variant chains.

### 4. Needless abstraction

Remove pass-through wrappers, single-use helpers, speculative indirection, one-implementer
interfaces without a testability seam, and factories that only call constructors. Keep real seams:
testing, multiple implementations, or framework-required boundaries.

### 5. Boundary violations

Flag wrong-layer imports, mixed responsibilities, hidden private-state coupling, and side effects
inside pure-named functions. Keep established pragmatic patterns. If layer intent is unclear,
flag it for human judgment rather than refactoring blindly.

### 6. Dead code

Remove unused imports, unreferenced private code, unreachable branches, stale flags, and debug
leftovers. Keep reflection, dynamic dispatch, string-looked-up code, and intentional rollback
paths after verifying their role.

### 7. Duplication

Consolidate copy-pasted branches, redundant helpers, and repeated magic sequences only when their
intent is genuinely shared. Leave incidental lookalikes separate; premature shared abstractions
are fresh slop wearing a fake moustache.

### 8. Performance equivalences

Apply only obvious semantic equivalences: set lookup instead of repeated list scans, hoisting
unchanged loop work, avoiding single-use intermediate collections, joining strings, batching
redundant calls, avoiding needless copies, or caching a stable loop length. Do not change a subtle
algorithm or micro-optimize without a benchmark. If equivalence needs proof, skip it.

### 9. Missing behavior coverage

Add only the narrowest test for behavior introduced or exposed by changed source. Never add
deletion-only, tautological, implementation-mirroring, constant-pinning, or prose-pinning tests.

### 10. Oversized modules

Treat source files over 250 pure lines—non-blank, non-comment—as an architectural concern. Before
splitting, identify distinct responsibilities and show the user a concept-based split plan. Name
new modules for their responsibility, not `utils`, `helpers`, `common`, or numbered fragments.
Keep package initializers as re-exports only. Then rerun size measurement, tests, type checks, and
lint. A genuinely self-contained source file may opt out only with a first-five-lines `SIZE_OK`
marker and a reason. Never game the count with comments, blanks, or build-output excuses.

## Quality gates and critical review

Run applicable project-native gates and record commands plus observed results:

| Gate | Pass condition |
| --- | --- |
| Regression and unit/integration tests | Green; pre-existing failures identified, not introduced |
| Lint | No new errors |
| Type checking | No new errors |
| Static or security scan | No new findings, or `N/A` when no scanner is configured |

Then verify: functional logic and boundary error handling remain; types/imports/public APIs remain
valid; return values, effects, exceptions, and edge cases stay locked; removals are genuinely slop;
there are no dead references or accidental abstractions; and performance changes are obviously
equivalent.

When a gate fails, identify the specific hunk, restore only that hunk, make a safe targeted repair
if possible, then rerun the failed gate and re-review that file. After three failed attempts on the
same file, stop and report the file, attempts, failure output, and hypothesis.

## Report template

```text
AI SLOP REMOVAL REPORT
Scope: <explicit list | branch diff>
Files: <paths>
Behavior lock: <existing coverage, tests added, baseline result>
Cleanup plan: <file: ladder → categories → risk>
Per-file results: <change → replacement; why safe; skipped concern and reason>
Quality gates: <command/result or N/A with reason>
Critical review: <safety, behavior, quality>
Issues fixed: <none | issue → fix>
Net impact: <LOC, dependencies, files>
Deferred risks: <none | concern and debt marker>
Final status: <clean | issues fixed | requires attention>
```

## Failure patterns

Never skip behavior locking, bundle unrelated refactors, disguise an algorithm change as an
optimization, silently skip gates, delete WHY comments, or edit outside scope. When uncertain,
preserve the code and report the concern.
