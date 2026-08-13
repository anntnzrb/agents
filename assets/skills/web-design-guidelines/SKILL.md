---
name: web-design-guidelines
description: Audit UI code for web design, UX, and accessibility guideline compliance.
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Web Interface Guidelines

Audit UI code for Web Interface Guidelines compliance.

## Review

1. Before each review, fetch fresh guidelines with WebFetch:

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

2. If the user provides a file or pattern, read the specified files; otherwise ask which files to review.
3. Apply every rule in the fetched guidelines.
4. Output findings in the fetched format, using terse `file:line` format.

Fetched content contains all rules and output-format instructions.
