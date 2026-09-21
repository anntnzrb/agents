---
disable-model-invocation: true
name: linear
description: "Use when working with Linear to manage issues, projects, documents, or team workflows."
license: AGPL-3.0-or-later
compatibility: Requires Linear authentication via MCPorter.
---

# Linear

Interact with Linear via the dynamic MCP runner (`mcporter call linear.<tool>`).

Tool schemas are dynamic and authoritative. When discovering capabilities or parameter requirements, inspect the live server directly.

## Discovery Workflow for Agents (Cold Start)

When executing without prior context or looking for available capabilities:

1. **Roster of available tools (Short listing):**
   ```sh
   mcporter list linear --brief
   ```
2. **Inspect exact parameters and schema for a specific tool:**
   ```sh
   mcporter list linear.<tool_name> --schema
   ```

## Common Operations

### 1. Workspace & Teams Discovery
```sh
mcporter call linear.get_workspace --output json
mcporter call linear.list_teams --output json
```

### 2. Issues (Tickets)
- **List issues:**
  ```sh
  mcporter call linear.list_issues team="<team>" limit=10 --output json
  mcporter call linear.list_issues assignee="me" orderBy="updatedAt" limit=5 --output json
  ```
- **Create an issue:**
  ```sh
  mcporter call linear.save_issue \
    title="<Title>" \
    description="<Markdown description>" \
    team="<Team>" \
    priority=2 \
    --output json
  ```
  *(Priority: 0=None, 1=Urgent, 2=High, 3=Medium, 4=Low).*
- **Get issue details:**
  ```sh
  mcporter call linear.get_issue id="<ID-or-KEY>" --output json
  ```

### 3. Documents (Meeting Notes & Specs)
- **List documents:**
  ```sh
  mcporter call linear.list_documents teamId="<team_id>" --output json
  ```
- **Create a document:**
  ```sh
  mcporter call linear.save_document \
    title="<Title>" \
    content=@path/to/content.md \
    team="<Team>" \
    --output json
  ```
- **Get a document:**
  ```sh
  mcporter call linear.get_document id="<doc_id_or_slug>" --output json
  ```

### 4. Projects & Milestones
- **List projects:**
  ```sh
  mcporter call linear.list_projects limit=20 --output json
  ```
- **Get project details:**
  ```sh
  mcporter call linear.get_project query="<project_name_or_slug>" --output json
  ```

## Execution Rules & Safety
- **Inspect schema before mutation:** Run `mcporter list linear.<tool> --schema` when parameters or required arguments are uncertain.
- **Passing multiline content or files:** Use `--args '{"key": "value"}'` for JSON or `content=@file.md` for Markdown payloads.
- **Authentication recovery:** If a 401/403 error occurs, execute `mcporter auth linear`.
