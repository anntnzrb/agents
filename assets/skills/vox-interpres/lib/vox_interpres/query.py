from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import AnalysisResult, SectionHint

Intent = Literal[
    "summary",
    "tempo",
    "key",
    "beats",
    "duration",
    "energy",
    "spectral",
    "sections",
    "metadata",
]

_INTENT_RULES: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    ("tempo", ("tempo", "bpm", "rhythm", "speed")),
    ("key", ("key", "scale", "mode", "tonic")),
    ("beats", ("beat", "downbeat", "pulse")),
    ("duration", ("duration", "length", "how long", "runtime", "time")),
    ("energy", ("energy", "loud", "dynamic", "intense", "quiet")),
    ("spectral", ("spectral", "brightness", "timbre", "centroid", "rolloff")),
    (
        "sections",
        ("section", "structure", "verse", "chorus", "bridge", "intro", "outro"),
    ),
    (
        "metadata",
        (
            "metadata",
            "codec",
            "sample rate",
            "bitrate",
            "container",
            "channels",
            "ffprobe",
        ),
    ),
)


@dataclass(slots=True, frozen=True)
class Answer:
    intent: Intent
    text: str


def classify_intents(question: str) -> list[Intent]:
    q = question.casefold()
    intents: list[Intent] = []
    for intent, tokens in _INTENT_RULES:
        if any(token in q for token in tokens):
            intents.append(intent)
    return intents or ["summary"]


def classify_intent(question: str) -> Intent:
    return classify_intents(question)[0]


def answer_question(analysis: AnalysisResult, question: str) -> Answer:
    intents = classify_intents(question)
    parts = [_answer_for_intent(analysis, intent) for intent in intents]
    return Answer(intent=intents[0], text=" ".join(parts))


def _answer_for_intent(analysis: AnalysisResult, intent: Intent) -> str:
    if intent == "tempo":
        return (
            f"Tempo ~{analysis.beats.tempo_bpm:.1f} BPM; "
            f"detected beats: {analysis.beats.beat_count}."
        )
    if intent == "key":
        return (
            f"Estimated key: {analysis.key.key} {analysis.key.mode}; "
            f"confidence {analysis.key.confidence:.2f}."
        )
    if intent == "beats":
        first = (
            "n/a"
            if analysis.beats.first_beat_s is None
            else f"{analysis.beats.first_beat_s:.2f}s"
        )
        last = (
            "n/a"
            if analysis.beats.last_beat_s is None
            else f"{analysis.beats.last_beat_s:.2f}s"
        )
        return (
            f"Beat grid: {analysis.beats.beat_count} beats, first at {first}, "
            f"last at {last}, tempo {analysis.beats.tempo_bpm:.1f} BPM."
        )
    if intent == "duration":
        segment = (
            "full track"
            if analysis.segment_duration_s is None
            else f"segment {analysis.segment_duration_s:.2f}s"
        )
        return (
            f"Analyzed {segment} from {analysis.segment_start_s:.2f}s; "
            f"effective duration {analysis.analysis_duration_s:.2f}s."
        )
    if intent == "energy":
        return (
            f"Energy dynamics: RMS mean {analysis.energy.rms.mean:.4f}, "
            f"dynamic range {analysis.energy.dynamic_range:.4f}, "
            f"low/high energy ratio {analysis.energy.low_energy_ratio:.2f}/{analysis.energy.high_energy_ratio:.2f}."
        )
    if intent == "spectral":
        return (
            f"Spectral centroid mean {analysis.spectral.centroid.mean:.1f} Hz, "
            f"rolloff mean {analysis.spectral.rolloff.mean:.1f} Hz, "
            f"flatness mean {analysis.spectral.flatness.mean:.4f}."
        )
    if intent == "sections":
        return _sections_summary(analysis.section_hints)
    if intent == "metadata":
        md = analysis.metadata
        return (
            f"Metadata: container={md.container or 'unknown'}, codec={md.codec or 'unknown'}, "
            f"sample_rate={md.sample_rate_hz or 'unknown'} Hz, channels={md.channels or 'unknown'}, "
            f"bitrate={md.bit_rate or 'unknown'} bps."
        )
    return (
        f"{analysis.file_path}: {analysis.analysis_duration_s:.2f}s analyzed, "
        f"tempo {analysis.beats.tempo_bpm:.1f} BPM, key {analysis.key.key} {analysis.key.mode}, "
        f"sections {len(analysis.section_hints)}."
    )


def _sections_summary(sections: list[SectionHint]) -> str:
    if not sections:
        return "No section hints detected."
    preview = "; ".join(
        f"{section.label}@{section.start_s:.1f}-{section.end_s:.1f}s({section.confidence:.2f})"
        for section in sections[:6]
    )
    return f"Section hints ({len(sections)}): {preview}."
