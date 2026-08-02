---
name: skill-work-gate
description: "Load the SSOT skill gate before mutations, then run its final gate after the edit batch"
condition: "(?:\"path\"\\s*:\\s*\")?(?:assets/skills|[^\"\\s]+/skills)/[^\"\\s]+(?:SKILL\\.md|scripts/cli\\.py|\\.env\\.example|tests/[^\"\\s]+)"
scope: ["tool:write", "tool:edit"]
---

This is skill work. On the **first matched mutation in the task**, pause and load `assets/skills/AGENTS.md`; if it is already loaded, continue without reloading or repeating this guidance. Batch the authorized edits, then run every mandatory gate from that SSOT **once after the batch**. If a gate fails, edit and rerun only the relevant gate until clean. Use `assets/skills/` as the SSOT and repository-relative or dynamically resolved paths.
