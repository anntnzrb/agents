---
disable-model-invocation: true
name: image-manipulation-image-magick
description: "Use when ImageMagick is requested for image resizing, conversion, batch edits, thumbnails, or metadata inspection."
license: AGPL-3.0-or-later
compatibility: Requires ImageMagick installed and available as `magick` on PATH. Cross-platform examples provided for PowerShell (Windows) and Bash (Linux/macOS).
metadata:
  author: anntnzrb
---

# Image Manipulation with ImageMagick

This skill enables image processing and manipulation tasks using ImageMagick
across Windows, Linux, and macOS systems.

## When to Use This Skill

Use this skill when you need to:

- Resize images (single or batch)
- Get image dimensions and metadata
- Convert between image formats
- Create thumbnails
- Process wallpapers for different screen sizes
- Batch process multiple images with specific criteria

## Prerequisites

- ImageMagick installed on the system
- **Windows**: PowerShell with ImageMagick available as `magick` (or at `C:\Program Files\ImageMagick-*\magick.exe`)
- **Linux/macOS**: Bash with ImageMagick installed via package manager (`apt`, `brew`, etc.)

## Core Capabilities

### 1. Image Information

- Get image dimensions (width x height)
- Retrieve detailed metadata (format, color space, etc.)
- Identify image format

### 2. Image Resizing

- Resize single images
- Batch resize multiple images
- Create thumbnails with specific dimensions
- Maintain aspect ratios

### 3. Batch Processing

- Process images based on dimensions
- Filter and process specific file types
- Apply transformations to multiple files

## Operating Workflow

1. Resolve `magick` before using it
   - PowerShell: store the executable in `$magick` and invoke with `& $magick`
   - Bash: require `command -v magick` before processing
2. Inspect first: use `magick identify -format "%wx%h" "path/to/image.jpg"` for dimensions or `magick identify -verbose "path/to/image.jpg"` for full metadata
3. Transform with quoted paths and explicit outputs:
   - Resize: `magick "input.jpg" -resize 427x240 "output.jpg"`
   - Thumbnail: `magick "$img" -resize 427x240 "thumbnails/thumb_$filename"`
   - Exact resize only when intended: `-resize 427x240!`
   - Minimum-fill resize only when intended: `-resize 427x240^`
4. Batch with platform-native loops:
   - PowerShell: `Get-ChildItem "path/to/images/*" | ForEach-Object { ... }`
   - Bash: `for img in path/to/images/*; do ...; done`
5. Filter by dimensions when processing only matching source images:
   - PowerShell: `$dimensions = & $magick identify -format "%w,%h" $_.FullName`
   - Bash: `dimensions=$(magick identify -format "%w,%h" "$img")`

Detailed command examples and reusable snippets live in `references/command-examples.md`.

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Platform-specific commands and batch loops|`references/command-examples.md`|Building PowerShell or Bash operations|

## Safety Constraints

1. **Always quote file paths** that may contain spaces
2. **Do not overwrite originals by accident**: write to an output directory or distinct filename unless the user explicitly requests in-place edits
3. **Use PowerShell call syntax**: invoke a stored executable path with `& $magick`
4. **Verify dimensions before expensive or conditional batch work** to avoid unnecessary processing
5. **Choose resize semantics deliberately**: plain `WxH` preserves aspect ratio within the box, `WxH!` distorts to exact dimensions, and `WxH^` fills at least the target dimensions
6. **Expect memory pressure on large batches**; process files iteratively and avoid loading unrelated images

## Validation Guidance

- Confirm ImageMagick is available before generating commands
- Run `identify` on representative input before and after transformations when dimensions, format, color space, or metadata matter
- For batch commands, validate on one file first, then apply the same command shape in the loop
- Check output files exist and dimensions match the requested behavior
- On older Linux systems with ImageMagick 6.x, `convert` may be needed instead of `magick`; prefer `magick` when available

## Limitations

- Large batch operations may be memory-intensive
- Some complex operations may require additional ImageMagick delegates
- On older Linux systems, use `convert` instead of `magick` (ImageMagick 6.x vs 7.x)
