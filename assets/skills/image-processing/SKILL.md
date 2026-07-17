---
name: image-processing
description: "Process web images with Pillow: resize, crop, trim, convert, optimize, thumbnail, or OG card."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Image Processing

Generate a task-specific Pillow script under `<temp-dir>`. This skill does not bundle a CLI.

```text
uv run --with Pillow <temp-dir>/image-task.py
```

## Safety

- Inspect source dimensions, mode, format, and animation first.
- NEVER overwrite originals without explicit user intent.
- Write transformed files to explicit output paths.
- Preserve animation only when the requested format supports it.
- Test batch logic on one representative file first.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Pillow setup, format choice, and implementation patterns | `references/pillow-patterns.md` | Before writing the task-specific script |

## Workflow

1. Resolve input and output paths with `pathlib.Path`.
2. Inspect images with `Image.open()` before transformation.
3. Select the smallest matching pattern from `references/pillow-patterns.md`.
4. Write a task-specific script under `<temp-dir>`.
5. Run it through the documented `uv` command.
6. Re-open outputs and verify dimensions, mode, and format.
