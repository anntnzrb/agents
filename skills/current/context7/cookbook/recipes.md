# Context7 Recipes

Practical recipes for common documentation querying, skill management, and agent configuration tasks.

## Table of Contents

- [Recipe 1: Querying React Hook documentation](#recipe-1-querying-react-hook-documentation)
- [Recipe 2: Querying Next.js Server Actions](#recipe-2-querying-nextjs-server-actions)
- [Recipe 3: Querying Prisma relation queries](#recipe-3-querying-prisma-relation-queries)
- [Recipe 4: Querying Effect platform services](#recipe-4-querying-effect-platform-services)
- [Recipe 5: Scripting and extracting code snippets with jq](#recipe-5-scripting-and-extracting-code-snippets-with-jq)
- [Recipe 6: Installing and searching agent skills](#recipe-6-installing-and-searching-agent-skills)
- [Recipe 7: Configuring Context7 MCP for Claude Code](#recipe-7-configuring-context7-mcp-for-claude-code)

---

## Recipe 1: Querying React Hook documentation

Search the React index and fetch docs for the `useId` hook:

```bash
# 1. Resolve library ID
bun x ctx7@latest library "React" "useId accessibility identifier" --json

# 2. Query documentation
bun x ctx7@latest docs /reactjs/react.dev "How to generate unique form IDs with useId"
```

---

## Recipe 2: Querying Next.js Server Actions

Search Next.js App Router documentation for Server Actions form validation:

```bash
# 1. Resolve library ID
bun x ctx7@latest library "Next.js" "Server Actions form state validation" --json

# 2. Query documentation
bun x ctx7@latest docs /vercel/next.js "How to validate forms in Server Actions with useActionState"
```

---

## Recipe 3: Querying Prisma relation queries

Look up Prisma relation filters and cascade deletion:

```bash
# 1. Resolve library ID
bun x ctx7@latest library "Prisma" "define one-to-many relations with cascade delete" --json

# 2. Query documentation
bun x ctx7@latest docs /prisma/prisma "How to configure onDelete Cascade on relations"
```

---

## Recipe 4: Querying Effect platform services

Look up Effect platform FileSystem and Path service usages:

```bash
# 1. Resolve library ID
bun x ctx7@latest library "Effect" "FileSystem and Path services in Effect" --json

# 2. Query documentation
bun x ctx7@latest docs /effect-ts/effect "How to read files using FileSystem.FileSystem service"
```

---

## Recipe 5: Scripting and extracting code snippets with jq

Extract only code blocks from a documentation query using `jq`:

```bash
bun x ctx7@latest docs /reactjs/react.dev "useEffect cleanup with abort controller" --json \
  | jq -r '.codeSnippets[].codeList[] | select(.language == "js" or .language == "ts" or .language == "javascript") | .code'
```

---

## Recipe 6: Installing and searching agent skills

Search and install skills from the Context7 skills registry:

```bash
# Search registry
bun x ctx7@latest skills search "react testing"

# Suggest skills for current project dependencies
bun x ctx7@latest skills suggest

# Install specific skill from repo
bun x ctx7@latest skills install /anthropics/skills
```

---

## Recipe 7: Configuring Context7 MCP for Claude Code

Configure the Context7 MCP server for Claude Code non-interactively with an existing API key:

```bash
bun x ctx7@latest setup --mcp --claude --api-key "$CONTEXT7_API_KEY" --yes
```
