from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import AnalysisResult

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".wav", ".ogg", ".m4a"}


def validate_audio_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"audio file not found: {path}")
    if resolved.suffix.lower() not in SUPPORTED_EXTENSIONS:
        suffixes = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(
            f"unsupported audio format '{resolved.suffix}'. expected one of: {suffixes}"
        )
    return resolved


def ensure_out_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def cache_key_for(
    audio_path: Path, segment_start_s: float, segment_duration_s: float | None
) -> str:
    stat = audio_path.stat()
    duration_bit = "full" if segment_duration_s is None else f"{segment_duration_s:.6f}"
    material = (
        f"{audio_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|"
        f"{segment_start_s:.6f}|{duration_bit}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def cache_path_for(
    out_dir: Path,
    audio_path: Path,
    segment_start_s: float,
    segment_duration_s: float | None,
) -> Path:
    key = cache_key_for(audio_path, segment_start_s, segment_duration_s)
    stem = audio_path.stem.replace(" ", "_")
    return out_dir / f"{stem}.{key}.analysis.json"


def save_analysis(path: Path, analysis: AnalysisResult) -> None:
    payload = analysis.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_analysis(path: Path) -> AnalysisResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("analysis json must be an object")
    return AnalysisResult.from_dict(payload)
