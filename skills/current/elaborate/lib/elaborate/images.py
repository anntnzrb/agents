# Copyright (c) 2026
"""Shared image marker syntax and EPUB core image media types."""

import re
from pathlib import PurePosixPath

from .data import InputError

MARKER = re.compile(r"(?<!\\)\{image (images/[^\s{}|]+) \| ((?:\\[{}]|[^{}\n])*)\}")
MEDIA = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
IMAGE_PATH_PARTS = 2


def image_media(path: str) -> str:
    """Validate an image resource's extension at the input boundary."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in MEDIA:
        raise InputError(f"Unsupported image resource: {path}")
    return MEDIA[suffix]


def image_path(path: str) -> str:
    """Require a marker path directly beneath the work's images directory."""
    parts = PurePosixPath(path).parts
    if (
        len(parts) != IMAGE_PATH_PARTS
        or parts[0] != "images"
        or parts[1] in (".", "..")
        or "\\" in path
    ):
        raise InputError(f"Invalid image marker path: {path}")
    _ = image_media(path)
    return path
