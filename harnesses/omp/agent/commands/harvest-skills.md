---
description: Merge ~/.omp/agent/managed-skills into SSOT skills, then empty it
---
workflowz

Consolidate ~/.omp/agent/managed-skills/ into my SSOT skills (~/.config/agents/skills/current/), then empty that directory.

1. Read every managed SKILL.md and docs/skills.md.
2. For each managed skill, find the SSOT skill(s) it overlaps with.
3. Keep only content that's reusable, harness-agnostic, and not already in the target skill. Drop hostnames, IPs, UUIDs, personal names, private URLs, machine-specific paths, and opinionated preferences.
4. Merge what's left into the existing SSOT skills. Don't create any new skills during this pass.
5. Run the docs/skills.md gates on every changed skill.
6. Check the full diff for leaked environment details, and confirm every CLI flag or subcommand you added against the tool's --help.
7. Empty the managed-skills directory. You don't need to ask first.
8. Don't sync or commit.
9. Report one row per managed skill (adopted, partial, or discarded, with where it went or why it was dropped), the useful content that had no SSOT home, and the checks you ran.
10. Once all of that is done, go through the leftover content and suggest a new skill for each group that's worth one. Ask me which ones to create.

Execution:
- Do steps 1-2 yourself. Split the work into slices that don't share files: each slice is a set of managed skills plus the SSOT skills it owns, and no two slices touch the same SSOT skill.
- Push every slice into one named pool of task workers (not scouts). Each worker does steps 3-4 for its slice and edits only the skills it owns. Workers don't run gates, delete anything, sync, or commit.
- Wait for the pool to finish, then read all the results together instead of one at a time.
- Do steps 5-10 yourself, once, across everything that changed.
