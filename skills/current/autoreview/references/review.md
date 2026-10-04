# Review rubric

Read before reviewing a bundle. Report concrete, actionable problems introduced by the selected change.

## Decide what qualifies

- Identify a violated invariant, failing input, unsafe operation, or demonstrable regression. Explain the trigger and impact.
- Verify the diagnosis in the reviewed source state and relevant callers or tests. If evidence is insufficient, omit the finding rather than invent a dependency or assumption.
- Cite the smallest useful physical location in a changed file. Label an index-only defect with `state: "INDEX"`.
- Report one root cause per finding. Avoid duplicate symptoms and unrelated redesigns.
- Treat suspected real credentials as P0 without reproducing their values. Placeholders and test fixtures are not credentials.

## Assign priority

| Priority | Definition |
| --- | --- |
| P0 | Immediate blocker to normal operation or safety: data loss, exploitable exposure, or unavoidable startup failure |
| P1 | Severe defect on a common supported path, such as incorrect results or a major regression |
| P2 | Concrete defect with a narrower trigger, or a demonstrated performance regression or material test gap |
| P3 | Small actionable correctness or maintainability problem with a specific consequence |

Choose priority from demonstrated impact, not from alarming wording. State any required precondition in the body.

## Assign category

- `bug`: incorrect behavior or violated invariant.
- `security`: unauthorized access, credential exposure, or unsafe trust boundary.
- `regression`: supported behavior broken by the change.
- `test_gap`: a specific uncovered behavior whose failure risk is explained.
- `maintainability`: a concrete maintenance hazard, not personal style preference.

## Omit noise

- Do not report pre-existing defects unless the change makes them actionable in a new way.
- Do not report formatting, naming preferences, generic missing tests, speculative breakage, or intentional behavior supported by the task.
- Do not assert historical blame without a parent-relative patch.
- Do not treat a valid JSON report or an empty filtered list as proof that the patch is correct.

Write a short title and a body that connects the source to the failure and an actionable correction.
Calibrate confidence to evidence. Report only claims you verified, regardless of the numeric confidence.
