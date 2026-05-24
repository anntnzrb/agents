# Packaging Details

Read this file when the user wants an installable `.skill` artifact, packaging validation, or package handoff details.

## Entry point

Cross-platform command form:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. NEVER rely on shell sourcing, executable bits, or shebang dispatch.

## Validation and package commands

```bash
uv run --script <skill-dir>/scripts/cli.py quick-validate <path-to-skill-folder>
uv run --script <skill-creator-path>/scripts/cli.py package <path/to/skill-folder>
uv run --script <skill-dir>/scripts/cli.py package <path-to-skill-folder>
```

## Package and present

If the `present_files` tool is unavailable, skip presentation. If it is available, package the skill and present the `.skill` file:

```bash
uv run --script <skill-creator-path>/scripts/cli.py package <path/to/skill-folder>
```

Tell the user the resulting `.skill` file path so they can install it.
