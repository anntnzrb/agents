---
name: java-oop-assignment
description: Complete Java OOP/FOP assignments from PDF specifications with minimal compliant code.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Java OOP Assignment Solver

## Philosophy

**KISS + YAGNI**: Write the minimum code to pass. Less code = less to review = fewer bugs.

## Workflow

### Phase 1: Understand

1. **Read the PDF** - Extract all requirements, class diagrams, method signatures
2. **Explore codebase** - Find existing templates, enums, helper classes marked `@DoNotTouch`
3. **Identify tasks** - List each numbered requirement (H6.1, H6.2, etc.)

### Phase 2: Plan

Create a todo list with:

- Files to CREATE (interfaces, enums, classes)
- Files to MODIFY (implement methods, add `implements`)
- Implementation order (dependencies first)

### Phase 3: Implement

For each task:

1. **Interfaces/Enums first** - No dependencies
2. **Abstract classes** - Base functionality
3. **Concrete classes** - Extend/implement
4. **Modify existing** - Add interface implementations, fill in `TODO` methods
5. **Remove crash() calls** - Replace `crash("H6.X")` with actual implementation

### Phase 4: Verify

1. Resolve `<gradle-wrapper>` for the current platform.
2. Build: `<gradle-wrapper> compileJava`.
3. Run a provided playground: `<gradle-wrapper> run`.
4. Check output matches PDF examples.

## Implementation Rules

### Minimal Code

- No extra comments unless logic is unclear
- No extra validation unless specified
- No helper methods unless reused 3+ times
- Match exact signatures from PDF (visibility, types, names)
- Parse external input once at its boundary; use the assignment’s domain types instead of strings or loose flags when confusion would be a bug.
- Make specified failure behavior explicit and preserve useful context; do not swallow exceptions or add unrequested recovery paths.
- Keep ownership and mutation clear: initialize required state in constructors and avoid sharing mutable state without an assignment requirement.
- Test observable examples and meaningful edge or failure cases; do not pin private helper structure.

### PDF Reading Tips

- **Class diagrams**: Solid arrow = extends, dashed arrow = implements
- **"protected"**: Accessible to subclasses
- **"private final"**: Immutable, set in constructor
- **Mandatory requirements** in boxes: Must follow exactly

### Modern Java Idioms

Use the following for code conciseness, elegance and brevity.

- **Switch expressions** (`->`) - returns value, no break needed, fewer lines
- **Pattern matching instanceof** - cast + variable binding in one check
- **var** - type inference for locals, less redundancy
- **Ternary operator** - one-liner conditionals over if-else blocks
- **Math.min/max** - bounds checking without branching
- **Records** - immutable data classes in one line (if allowed)
- **Text blocks** (`"""`) - multi-line strings without concatenation

### Gradle Notes

- If the build reports a Java-version error, select JDK 21 for the current shell and run `<gradle-wrapper> build`.
- `@StudentImplementationRequired("H6.X")` marks methods to implement
- Remove `crash("H6.X")` calls when implementing

## Checklist

- [ ] All `TODO` comments addressed
- [ ] All `crash()` calls removed
- [ ] All interfaces/classes from diagram created
- [ ] Build succeeds
- [ ] Run output matches PDF examples (if playground provided)
