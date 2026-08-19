---
name: skill-work-gate
description: "Load the SSOT skill gate before mutations, then run its final gate after the edit batch"
condition: "(?:\"path\"\\s*:\\s*\")?(?:skills/(?:current|legacy)|[^\"\\s]+/skills)/[^\"\\s]+(?:SKILL\\.md|scripts/cli\\.py|\\.env\\.example|tests/[^\"\\s]+)"
scope: ["tool:write", "tool:edit"]
---

This is skill work. On the **first matched mutation in the task**, pause and load `docs/skills.md`; if it is already loaded, continue without reloading or repeating this guidance. Batch the authorized edits, then run every mandatory gate from that SSOT **once after the batch**. If a gate fails, edit and rerun only the relevant gate until clean. Use `skills/` as the SSOT and repository-relative or dynamically resolved paths.
