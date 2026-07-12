#!/usr/bin/env -S uv run --script
"""Build the local, spoiler-gated DSR Dadbod transcript corpus.

The input is a user-local JSON export of English ``en-orig`` automatic captions.
Only deterministic, normalized word chunks and provenance metadata are written;
the source JSON is never copied, moved, or removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import TypedDict, cast

EXPECTED_SOURCE_SHA256 = (
    "99bfdb067225d0290c66520ec468f04a50643d541b8a9c37344c274eadbfd5f3"
)
DEFAULT_SOURCE = Path("C:/Users/Nil/Documents/ds3/dsr-dadbod-transcripts.json")
DEFAULT_OUTDIR = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "guides"
    / "dsr_dadbod_transcripts"
)
TARGET_CHARS = 1400
MAX_CHARS = 1800
MIN_CHARS = 80


class TranscriptRecord(TypedDict):
    playlist_index: int
    video_id: str
    url: str
    caption_track: str
    cue_count: int
    transcript: str


RECORD_KEYS = {
    "playlist_index",
    "video_id",
    "url",
    "caption_track",
    "cue_count",
    "transcript",
}
SOURCE_KEYS = {"playlist_url", "extractor", "caption_policy"}
TOP_LEVEL_KEYS = {"source", "extracted_at", "video_count", "transcripts"}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def normalize(text: str) -> str:
    """Apply only NFKC normalization and Unicode whitespace collapsing."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _require_string(record: dict[str, object], key: str, label: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{label}.{key} must be a string")
    return value


def validate_source(
    payload: object,
) -> tuple[dict[str, object], list[TranscriptRecord]]:
    """Validate the supplied export schema and its 1-based playlist order."""
    top = _require_mapping(payload, "source JSON")
    if set(top) != TOP_LEVEL_KEYS:
        raise ValueError(
            "source JSON keys must be exactly " + ", ".join(sorted(TOP_LEVEL_KEYS))
        )
    source = _require_mapping(top["source"], "source")
    if set(source) != SOURCE_KEYS:
        raise ValueError(
            "source metadata keys must be exactly " + ", ".join(sorted(SOURCE_KEYS))
        )
    for key in SOURCE_KEYS:
        _require_string(source, key, "source")
    _require_string(top, "extracted_at", "source JSON")

    count = top["video_count"]
    if type(count) is not int or count < 1:
        raise ValueError("video_count must be a positive integer")
    raw_transcripts = top["transcripts"]
    if not isinstance(raw_transcripts, list):
        raise ValueError("transcripts must be an array")
    if len(raw_transcripts) != count:
        raise ValueError("video_count must equal transcripts length")

    records: list[TranscriptRecord] = []
    for expected_index, raw in enumerate(raw_transcripts, start=1):
        item = _require_mapping(raw, f"transcripts[{expected_index - 1}]")
        if set(item) != RECORD_KEYS:
            raise ValueError(
                f"transcripts[{expected_index - 1}] keys must be exactly "
                + ", ".join(sorted(RECORD_KEYS))
            )
        playlist_index = item.get("playlist_index")
        if type(playlist_index) is not int or playlist_index != expected_index:
            raise ValueError(
                f"transcripts[{expected_index - 1}].playlist_index must be {expected_index}"
            )
        video_id = _require_string(
            item, "video_id", f"transcripts[{expected_index - 1}]"
        )
        url = _require_string(item, "url", f"transcripts[{expected_index - 1}]")
        caption_track = _require_string(
            item, "caption_track", f"transcripts[{expected_index - 1}]"
        )
        if not video_id or not url or caption_track != "en-orig":
            raise ValueError(
                f"transcripts[{expected_index - 1}] has invalid video_id/url/caption_track"
            )
        cue_count = item.get("cue_count")
        if type(cue_count) is not int or cue_count < 0:
            raise ValueError(
                f"transcripts[{expected_index - 1}].cue_count must be a non-negative integer"
            )
        transcript = _require_string(
            item, "transcript", f"transcripts[{expected_index - 1}]"
        )
        if not transcript.strip():
            raise ValueError(f"transcripts[{expected_index - 1}].transcript is empty")
        records.append(
            {
                "playlist_index": playlist_index,
                "video_id": video_id,
                "url": url,
                "caption_track": caption_track,
                "cue_count": cue_count,
                "transcript": transcript,
            }
        )
    return source, records


def chunk_words(text: str) -> list[str]:
    """Pack words to the target, merging a short final chunk when safe."""
    words = text.split(" ")
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        word_length = len(word)
        if word_length > MAX_CHARS:
            raise ValueError("a single word exceeds the maximum chunk size")
        candidate_length = (
            word_length if not current else current_length + 1 + word_length
        )
        if current and candidate_length > TARGET_CHARS:
            chunks.append(" ".join(current))
            current = [word]
            current_length = word_length
        else:
            current.append(word)
            current_length = candidate_length
    if current:
        chunks.append(" ".join(current))

    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHARS:
        combined = f"{chunks[-2]} {chunks[-1]}"
        if len(combined) > MAX_CHARS:
            raise ValueError("short final chunk cannot be merged within maximum size")
        chunks[-2:] = [combined]
    if not chunks or any(not MIN_CHARS <= len(chunk) <= MAX_CHARS for chunk in chunks):
        raise ValueError("chunk bounds violated")
    return chunks


def transform(
    source_path: Path, outdir: Path
) -> tuple[dict[str, object], list[dict[str, object]]]:
    raw_bytes = source_path.read_bytes()
    source_sha256 = _sha256_bytes(raw_bytes)
    if source_sha256 != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            f"source SHA-256 mismatch: expected {EXPECTED_SOURCE_SHA256}, got {source_sha256}"
        )
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"source JSON is not valid UTF-8 JSON: {exc}") from exc
    source_metadata, records = validate_source(payload)

    rows: list[dict[str, object]] = []
    videos: list[dict[str, object]] = []
    for video_index, record in enumerate(records):
        raw_transcript_sha256 = _sha256_text(record["transcript"])
        normalized = normalize(record["transcript"])
        normalized_transcript_sha256 = _sha256_text(normalized)
        chunks = chunk_words(normalized)
        reconstructed = " ".join(chunks)
        if reconstructed != normalized:
            raise ValueError(f"video {video_index} failed exact chunk reconstruction")
        for chunk_index, text in enumerate(chunks):
            rows.append(
                {
                    "video_index": video_index,
                    "chunk_index": chunk_index,
                    "playlist_index": record["playlist_index"],
                    "video_id": record["video_id"],
                    "url": record["url"],
                    "caption_track": record["caption_track"],
                    "cue_count": record["cue_count"],
                    "source_sha256": source_sha256,
                    "transcript_sha256": raw_transcript_sha256,
                    "raw_transcript_sha256": raw_transcript_sha256,
                    "normalized_transcript_sha256": normalized_transcript_sha256,
                    "h": [f"Video {video_index + 1:03d}"],
                    "k": "transcript",
                    "t": text,
                }
            )
        videos.append(
            {
                "video_index": video_index,
                "playlist_index": record["playlist_index"],
                "video_id": record["video_id"],
                "url": record["url"],
                "caption_track": record["caption_track"],
                "cue_count": record["cue_count"],
                "chunk_count": len(chunks),
                "raw_transcript_sha256": raw_transcript_sha256,
                "transcript_sha256": raw_transcript_sha256,
                "normalized_transcript_sha256": normalized_transcript_sha256,
                "normalized_char_count": len(normalized),
                "reconstructed_char_count": len(reconstructed),
            }
        )

    lengths = [len(cast(str, row["t"])) for row in rows]
    manifest: dict[str, object] = {
        "title": "Dark Souls Remastered Dadbod walkthrough transcripts",
        "format": "dsr-dadbod-transcript-chunks-v1",
        "chunk_count": len(rows),
        "video_count": len(records),
        "source_json_name": source_path.name,
        "source_sha256": source_sha256,
        "source_json_sha256": source_sha256,
        "source_type": "user-provided English en-orig automatic captions",
        "source_json_tracked": False,
        "tracked_artifact": True,
        "copyable": False,
        "usage": [
            "local transcript lookup",
            "transformed, provenance-labeled answers only",
        ],
        "constraints": [
            "WARNING: local automatic captions; spoiler-heavy; non-authoritative; not mechanics/save/parser/route truth.",
            "Automatic captions may be inaccurate; verify all claims against authoritative sources or game data.",
            "Source rights are unknown and the raw source JSON is not copied into resources.",
            "Keep this corpus separate from the PSNProfiles guide corpus.",
        ],
        "provenance": {
            "playlist_url": source_metadata["playlist_url"],
            "extractor": source_metadata["extractor"],
            "caption_policy": source_metadata["caption_policy"],
            "extracted_at": payload["extracted_at"]
            if isinstance(payload, dict)
            else None,
            "boundary": "Only NFKC-normalized, whitespace-collapsed transcript chunks and provenance metadata are stored; source JSON remains user-local.",
            "citation": "Each row preserves its source video URL, exact video ID, en-orig track, and cue count.",
        },
        "preprocessing": {
            "unicode_normalization": "NFKC",
            "whitespace": "Collapse every Unicode whitespace run to one ASCII space, then trim.",
            "word_chunked": True,
            "target_chunk_chars": TARGET_CHARS,
            "max_chunk_chars": MAX_CHARS,
            "min_chunk_chars": MIN_CHARS,
            "no_cross_video_chunks": True,
            "join_separator": " ",
            "row_schema": {
                "video_index": "0-based video index",
                "chunk_index": "0-based chunk index within video",
                "h": "generic video heading",
                "k": "transcript",
                "t": "normalized transcript chunk",
                "source_sha256": "raw source JSON SHA-256",
                "transcript_sha256": "raw transcript UTF-8 SHA-256",
            },
        },
        "normalized_reconstruction": {
            "exact": True,
            "proof": "For every video, joining its ordered t fields with one ASCII space equals the normalized transcript byte-for-byte.",
            "video_proofs": [
                {
                    "video_index": video["video_index"],
                    "chunk_count": video["chunk_count"],
                    "normalized_transcript_sha256": video[
                        "normalized_transcript_sha256"
                    ],
                    "normalized_char_count": video["normalized_char_count"],
                    "reconstructed_char_count": video["reconstructed_char_count"],
                    "exact": True,
                }
                for video in videos
            ],
        },
        "extraction": {
            "total_normalized_chars": sum(
                cast(int, video["normalized_char_count"]) for video in videos
            ),
            "min_chunk_chars": min(lengths),
            "max_chunk_chars": max(lengths),
            "chunk_count": len(rows),
        },
        "videos": videos,
    }
    return manifest, rows


def write_outputs(
    outdir: Path, manifest: dict[str, object], rows: list[dict[str, object]]
) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    chunks_path = outdir / "dsr-dadbod-transcripts.chunks.jsonl"
    manifest_path = outdir / "dsr-dadbod-transcripts.manifest.json"
    chunks_text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    chunks_path.write_text(chunks_text, encoding="utf-8", newline="\n")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the local DSR Dadbod transcript corpus from user-provided JSON."
    )
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("outdir", nargs="?", type=Path, default=DEFAULT_OUTDIR)
    args = parser.parse_args(argv)
    source_path = args.source.expanduser().resolve()
    if not source_path.is_file() or source_path.suffix.lower() != ".json":
        parser.error(f"source not found or not JSON: {source_path}")
    try:
        manifest, rows = transform(source_path, args.outdir.expanduser().resolve())
        write_outputs(args.outdir.expanduser().resolve(), manifest, rows)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    extraction = cast(dict[str, object], manifest["extraction"])
    print(
        json.dumps(
            {
                "videos": manifest["video_count"],
                "chunks": manifest["chunk_count"],
                "source_sha256": manifest["source_sha256"],
                "min_chunk_chars": extraction["min_chunk_chars"],
                "max_chunk_chars": extraction["max_chunk_chars"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
