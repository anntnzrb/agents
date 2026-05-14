# Hide Disabled Skills Extension

## Purpose

Temporary upstream-parity shim for OMP skill frontmatter:

```yaml
disable-model-invocation: true
```

It keeps matching skills manually available while removing them from the model-facing `# Skills` system-prompt section.

## Files

- `index.ts` — scans user/project `SKILL.md` frontmatter, builds the disabled skill-name set, and filters `before_agent_start` system prompt blocks.
- `tsconfig.json` — strict TypeScript config matching sibling extension layout.

## Invariants

- Prompt-only filtering.
- No tools.
- No commands.
- No package dependencies.
- No skill load/discovery mutation.
- Preserve manual `/skill:<name>` and `skill://<name>` semantics.
- Keep skill markdown frontmatter as the source of truth.
- Remove this extension when OMP core supports upstream `disable-model-invocation` behavior.

## Stop Rules

- Do not use config allowlists/denylists for skill names.
- Do not mark skills `enabled: false`; that breaks manual invocation.
- Do not hide loaded/active skill registry state; only filter model prompt exposure.
