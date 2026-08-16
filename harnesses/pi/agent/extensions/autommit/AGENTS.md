# Autommit Pi Extension

This extension provides the `/autommit` command in Pi by delegating Git state management and transactions directly to the SSOT `autommit` Python CLI.

- `index.ts` owns the command registration, model completion prompts, and execution of the `autommit` CLI pipeline (`prepare` -> `completeJson` -> `validate-plan` -> `apply`).
- Model interactions use Pi's active session model and thinking level.
- All Git operations, validation, and transactions are owned by the deterministic Python CLI.
