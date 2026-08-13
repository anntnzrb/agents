# Reference Guide

## Data structures
Need → structure:
- Fast key lookup → hash map/dictionary; ordered traversal → sorted array/tree.
- Fast min/max extraction → heap/priority queue; FIFO → queue/deque; LIFO → stack.
- Membership testing → set; occurrence counts → counter/frequency map.
- Disjoint sets/union-find → Union-Find; coordinate storage → tuple as hash-map key.

Space-time: more memory → precompute lookup tables; less memory → compute on demand; immutable data → safe memoization.

## Optimization
Early termination: return when answer found; skip unnecessary iterations; prune branches that cannot improve the result.
Avoid redundant work: memoize expensive calls; precompute static data outside loops; use sets for O(1) membership instead of O(n) list scanning.
Numeric: integer division → divide and round down; modulo → cyclic patterns; bit operations → binary representations; XOR → parity/toggle operations.

## Avoid / prefer
Don't:
- Guess and submit without testing examples.
- Over-engineer before a working solution.
- Copy-paste between parts; extract functions instead.
- Assume input format without verification.
- Ignore Part 2 implications when designing Part 1.
- Optimize prematurely before correctness.
- Use mutable global state; it makes debugging hard.

Do:
- Read the full problem before coding.
- Start with examples as test cases.
- Print intermediate state while debugging.
- Keep solutions simple until complexity is needed.
- Refactor between parts if Part 2 requires changes.

## Part 2
Patterns:
- Scale up (10 → 1,000,000) → optimize algorithm.
- Add dimensions (2D grid → 3D) → generalize coordinates.
- Reverse ("Find X" → "Given X, find Y") → adapt the solution.
- Many iterations (1000 → 1 billion) → cycle detection.
- Add constraints → refactor logic.
- Combine operations (chain transforms) → compose functions.

Preparation: write Part 1 for extensibility; use parameters instead of hardcoded values; separate parsing from logic; don't delete Part 1 code—you may need to reference it.

## When stuck
1. Re-read the problem; something is likely misunderstood.
2. Check off-by-one errors in ranges/indices.
3. Verify coordinate-system consistency.
4. Print each step's state and compare with the example walkthrough.
5. Try smaller/simpler input to isolate the issue.
6. Consider whether the algorithm choice is fundamentally wrong.

## Workflow

```
[ ] Parse problem statement carefully
[ ] Identify problem category (graph, DP, simulation, etc.)
[ ] Extract example input/output pairs
[ ] Design solution approach before coding
[ ] Implement with clear, testable functions
[ ] Test against ALL examples
[ ] Debug systematically if tests fail
[ ] Run on actual input
[ ] Verify answer format matches expected type
[ ] Adapt for Part 2
```

## Code quality
- Descriptive variable names, not single letters except loop indices.
- Functions do one thing.
- Comments explain _why_, not _what_.
- Assertions document assumptions.
- Consistent formatting throughout.
