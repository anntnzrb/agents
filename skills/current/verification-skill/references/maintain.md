# Maintain a verification skill

A feature map goes stale the moment the app changes. This pass keeps a `verify-<app>` skill and its feature map accurate. The unit of rigor is the feature, not every sentence: cover every feature file from source and exercise every feature live, without checking every bullet in a terminal.

## Outcomes

Pick one and say which:

- **clean:** every feature got source and live coverage, and nothing needs to change. No branch, no commit.
- **changed:** one change set ships proven doc, harness, or map corrections.
- **blocked:** coverage could not finish, or a proven fix could not ship safely. Say exactly what blocked it.

## Edit scope

Edit only the verification skill's own directory: its `SKILL.md`, `features/`, and any harness scripts it owns. Never edit product code during a run. When the app no longer does what the map describes, it is either doc drift (fix the map) or a product regression (report it, and do not hide it in the docs).

## Pass

0. **Locate the target.** Find the project-local skill whose body has Launch and Drive sections and a feature map, usually `.agents/skills/verify-*/`. With several candidates, ask which one. With none, stop and point at `create` mode instead of inventing a target.

1. **Index hygiene.** Read the feature map README and list its sibling files. Fix missing, extra, duplicate, or dead entries. Keep this light and do not generate an inventory.

2. **Source wave.** Give each feature file one read-only reader. Run the readers as concurrent subagents when the harness supports them, otherwise one after another. Each reader explains "how does this user-facing feature work?" from source, flags likely doc drift with citations, and returns one concise live-verification recipe. Readers never drive the app and never edit files. Return shape: feature summary, source entry points, likely drift or none, one recipe.

3. **Reconcile.** Confirm every feature file has a returned summary. Merge overlapping recipes into as few app states as practical. Spot-check cited drift, and do not re-prove clean claims. Sweep recent changes for user-facing surfaces missing from the map. Call a surface missing only with a concrete source path.

4. **Live pass.** Required even when the source looks clean. The coordinator does all the driving. Follow the verification skill's own launch model: one long-lived instance driven serially for servers and UIs, or a fresh isolated session per drive for short-lived CLIs. The skill's Launch section decides, not this file. Exercise every feature at least once, and hold three invariants for the whole pass, whatever fails:
   - Never drive an instance you have not health-checked since it last did something surprising. Run doctor before the first drive, on each fresh session where sessions are the unit, and again after any failed drive. When doctor cannot see the failure (a stuck UI state on a healthy process), reset to a known state or relaunch.
   - Evidence captured so far survives every cleanup. Check it at its named location. Do not assume it.
   - Nothing a drive started outlives its use. Clean up residue from failed iterations whether the session is stuck, exited, or shared. For a shared instance, clean the residue, not the instance.

   A doctor failure caused by skill drift is drift. Fix it within edit scope and retry once, restarting only what the fix invalidated, before you call the pass `blocked`. A feature that cannot be reached is `verified-unreachable` only with the concrete prerequisite (auth, entitlement, OS, external state) and the route attempted. If the map omits that prerequisite, that is drift. Drive every harness fix from triage live again before it ships. Run final teardown after the last drive of the run, including those re-proofs, so nothing outlives the run. Evidence stays, as the skill specifies.

5. **Triage.**
   - A wrong or missing user-POV description is doc drift. Fix it.
   - Working behavior the harness cannot drive is a harness gap. Fix it. A harness fix follows the same helpers rule as generation: scripts are executable and the skill body documents their invocation.
   - App behavior that is actually broken is a product gap. Record it for the user and keep it out of this change set.

6. **Ship or stop.** For `changed`, ship one change set of proven corrections, and re-read every changed file first. For `clean` or `blocked`, change nothing, and report the outcome and the coverage honestly.

Keep concise run notes (features covered, unreachable prerequisites, confirmed drift, outcome) in a scratch location. Do not commit them.
