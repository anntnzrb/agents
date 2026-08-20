# Pillow Patterns

Read before writing a task-specific Pillow script.

## Prerequisites

Pillow required for generated scripts:

```text
uv run --with Pillow <script.py>
```

Project-local dependency: `uv add Pillow`.

Without Pillow:

|Alternative|Platform|Install|Best for|
|---|---|---|---|
|`sips`|macOS (built-in)|None|Resize, convert (no trim/OG)|
|`sharp`|Node.js|`npm install sharp`|Full feature set, high performance|
|`ffmpeg`|Cross-platform|`brew install ffmpeg`|Resize, convert|

## Output Format Guide

|Use case|Format|Why|
|---|---|---|
|Photos, hero images|WebP|Best compression, wide browser support|
|Logos, icons (need transparency)|PNG|Lossless, supports alpha|
|Fallback for older browsers|JPG|Universal support|
|Thumbnails|WebP or JPG|Small file size priority|
|OG cards|PNG|Social platforms handle PNG best|

## Core Patterns

### Save with Format-Specific Quality

Use format-specific save parameters; JPG does not support transparency, so composite RGBA onto white first.

```python
from pathlib import Path

from PIL import Image

def save_image(img, output_path, quality=None):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {}
    ext = output.suffix.lower().lstrip(".")

    if ext == "webp":
        kwargs = {"quality": quality or 85, "method": 6}
    elif ext in ("jpg", "jpeg"):
        kwargs = {"quality": quality or 90, "optimize": True}
        # RGBA → RGB: composite onto white background
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
    elif ext == "png":
        kwargs = {"optimize": True}

    img.save(output, **kwargs)
```

### Resize with Aspect Ratio

When only one dimension is given, derive the other from aspect ratio; use `Image.LANCZOS` for high-quality downscaling.

```python
def resize_image(img, width=None, height=None):
    if width and height:
        return img.resize((width, height), Image.LANCZOS)
    elif width:
        ratio = width / img.width
        return img.resize((width, int(img.height * ratio)), Image.LANCZOS)
    elif height:
        ratio = height / img.height
        return img.resize((int(img.width * ratio), height), Image.LANCZOS)
    return img
```

### Trim Whitespace (Auto-Crop)

For logos/icons, convert to RGBA, use `getbbox()` for content bounds, and crop when bounds exist.

```python
img = Image.open(input_path)
if img.mode != "RGBA":
    img = img.convert("RGBA")
bbox = img.getbbox()  # Bounding box of non-zero pixels
if bbox:
    img = img.crop(bbox)
```

### Thumbnail

Fit within `(size, size)` while maintaining aspect ratio:

```python
img.thumbnail((size, size), Image.LANCZOS)
```

### Optimise for Web

Resize and compress in one step; WebP gives best compression. Typical settings: width 1920, quality 85.

### Cross-Platform Font Discovery

Try OS-specific font paths, fall back to Pillow’s default; Linux can discover fonts dynamically with `fc-list`.

```python
from pathlib import Path

from PIL import ImageFont

def get_font(size):
    font_paths = [
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSText.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        # Windows
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in font_paths:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()
```

### OG Card Generation (1200x630)

Composite text over an image or solid color, add a semi-transparent readability overlay, and center text horizontally.

```python
from PIL import Image, ImageDraw, ImageFont

width, height = 1200, 630

# Background: image or solid colour
if background_path:
    img = Image.open(background_path).resize((width, height), Image.LANCZOS)
else:
    img = Image.new("RGB", (width, height), bg_color or "#1a1a2e")

# Semi-transparent overlay for text readability
overlay = Image.new("RGBA", (width, height), (0, 0, 0, 128))
img = img.convert("RGBA")
img = Image.alpha_composite(img, overlay)

draw = ImageDraw.Draw(img)
font_title = get_font(48)
font_sub = get_font(24)

# Centre title
if title:
    bbox = draw.textbbox((0, 0), title, font=font_title)
    tw = bbox[2] - bbox[0]
    draw.text(((width - tw) // 2, height // 2 - 60), title, fill="white", font=font_title)

img = img.convert("RGB")
```
