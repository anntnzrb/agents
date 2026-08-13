# autommit

`/autommit` runs an unattended local commit agent using the model configured for the OMP `commit` role.

## Model selection

Re-evaluate the role before changing its model; provider catalogs, free tiers, quotas, and benchmark results expire quickly.

1. Confirm the exact provider/model selector is available with `omp models <provider> --json`.
2. Confirm the account's current quota and billing behavior with `omp usage`. Treat promotional access, signup credits, and paid balances as non-free unless the provider explicitly lists zero inference cost.
3. Use `skill://artificial-analysis-live` and refresh its live snapshot. For this tool-driven repository workflow, prioritize TerminalBench v2.1, then Automation Bench and the Coding Index. Do not select from the general Intelligence Index alone.
4. Use `skills/current/deepswe-live/SKILL.md`, fetch the current supported release, and compare published `pass_at_1`, confidence intervals, agent steps, and output tokens. Preserve model, reasoning effort, harness, and configuration identity.
5. Require benchmark evidence for the exact checkpoint. Do not transfer results from a paid checkpoint to a changing `:free`, `-free`, router, stealth, or `latest` alias.
6. Verify tool calling, structured output, context capacity, latency, privacy terms, retention policy, and rate limits against official provider documentation.
7. Prefer a genuinely free model when its task-relevant evidence is competitive. Otherwise choose the lowest-cost paid model that materially improves end-to-end reliability.
8. Smoke-test the candidate on representative clean, mixed, split, and malformed diffs before making it the default.

The durable configuration is `tools/omp/agent/config.yml`. Run the repository sync entrypoint after changing it so the generated OMP home receives the update.
