---
description: Prefer AST tools for structural code search and mechanical rewrites
condition:
  - "\\b(?:[Ff]ind|[Ss]earch|[Ll]ocate|[Ll]ist|[Rr]eplace|[Rr]ewrite|[Rr]efactor|[Cc]odemod|[Ee]dit)\\b.{0,160}\\b(?:usages?|call sites?|declarations?|imports?|exports?|decorators?|routes?|components?|hooks?|functions?|methods?|classes?|interfaces?|types?|structs?|enums?|impls?|traits?)\\b|\\b(?:[Uu]sages?|[Cc]all sites?|[Dd]eclarations?|[Ii]mports?|[Ee]xports?|[Dd]ecorators?|[Rr]outes?|[Cc]omponents?|[Hh]ooks?|[Cc]odemods?|[Rr]efactors?)\\b"
scope:
  - text
  - thinking
  - tool:grep
  - tool:edit
interruptMode: never
---

For syntax-shaped code work, use `ast_grep` before `grep`; for broad mechanical rewrites, use `ast_edit`. Use `grep`/`edit` for exact text, literals, comments, docs, config, or small local edits. If AST fails suspiciously, simplify once before falling back.
