from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1


@dataclass(slots=True, frozen=True)
class NumericStats:
    mean: float
    std: float
    minimum: float
    maximum: float
    p10: float
    p90: float

    def to_dict(self) -> dict[str, float]:
        return {
            "mean": self.mean,
            "std": self.std,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "p10": self.p10,
            "p90": self.p90,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> NumericStats:
        return cls(
            mean=_as_float(payload, "mean"),
            std=_as_float(payload, "std"),
            minimum=_as_float(payload, "minimum"),
            maximum=_as_float(payload, "maximum"),
            p10=_as_float(payload, "p10"),
            p90=_as_float(payload, "p90"),
        )


@dataclass(slots=True, frozen=True)
class FFProbeMetadata:
    container: str | None
    codec: str | None
    sample_rate_hz: int | None
    channels: int | None
    bit_rate: int | None
    duration_s: float | None
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "container": self.container,
            "codec": self.codec,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "bit_rate": self.bit_rate,
            "duration_s": self.duration_s,
            "tags": dict(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FFProbeMetadata:
        tags_raw = payload.get("tags", {})
        if not isinstance(tags_raw, dict):
            raise ValueError("metadata.tags must be an object")
        tags: dict[str, str] = {str(k): str(v) for k, v in tags_raw.items()}
        return cls(
            container=_as_optional_str(payload, "container"),
            codec=_as_optional_str(payload, "codec"),
            sample_rate_hz=_as_optional_int(payload, "sample_rate_hz"),
            channels=_as_optional_int(payload, "channels"),
            bit_rate=_as_optional_int(payload, "bit_rate"),
            duration_s=_as_optional_float(payload, "duration_s"),
            tags=tags,
        )


@dataclass(slots=True, frozen=True)
class KeyEstimate:
    key: str
    mode: str
    confidence: float
    chroma_profile: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "mode": self.mode,
            "confidence": self.confidence,
            "chroma_profile": list(self.chroma_profile),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KeyEstimate:
        chroma = payload.get("chroma_profile", [])
        if not isinstance(chroma, list):
            raise ValueError("key.chroma_profile must be a list")
        chroma_profile = [float(x) for x in chroma]
        return cls(
            key=_as_str(payload, "key"),
            mode=_as_str(payload, "mode"),
            confidence=_as_float(payload, "confidence"),
            chroma_profile=chroma_profile,
        )


@dataclass(slots=True, frozen=True)
class BeatSummary:
    tempo_bpm: float
    beat_count: int
    first_beat_s: float | None
    last_beat_s: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tempo_bpm": self.tempo_bpm,
            "beat_count": self.beat_count,
            "first_beat_s": self.first_beat_s,
            "last_beat_s": self.last_beat_s,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BeatSummary:
        return cls(
            tempo_bpm=_as_float(payload, "tempo_bpm"),
            beat_count=_as_int(payload, "beat_count"),
            first_beat_s=_as_optional_float(payload, "first_beat_s"),
            last_beat_s=_as_optional_float(payload, "last_beat_s"),
        )


@dataclass(slots=True, frozen=True)
class SpectralStats:
    centroid: NumericStats
    bandwidth: NumericStats
    rolloff: NumericStats
    flatness: NumericStats

    def to_dict(self) -> dict[str, Any]:
        return {
            "centroid": self.centroid.to_dict(),
            "bandwidth": self.bandwidth.to_dict(),
            "rolloff": self.rolloff.to_dict(),
            "flatness": self.flatness.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SpectralStats:
        return cls(
            centroid=NumericStats.from_dict(_as_dict(payload, "centroid")),
            bandwidth=NumericStats.from_dict(_as_dict(payload, "bandwidth")),
            rolloff=NumericStats.from_dict(_as_dict(payload, "rolloff")),
            flatness=NumericStats.from_dict(_as_dict(payload, "flatness")),
        )


@dataclass(slots=True, frozen=True)
class EnergyDynamics:
    rms: NumericStats
    dynamic_range: float
    low_energy_ratio: float
    high_energy_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rms": self.rms.to_dict(),
            "dynamic_range": self.dynamic_range,
            "low_energy_ratio": self.low_energy_ratio,
            "high_energy_ratio": self.high_energy_ratio,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EnergyDynamics:
        return cls(
            rms=NumericStats.from_dict(_as_dict(payload, "rms")),
            dynamic_range=_as_float(payload, "dynamic_range"),
            low_energy_ratio=_as_float(payload, "low_energy_ratio"),
            high_energy_ratio=_as_float(payload, "high_energy_ratio"),
        )


@dataclass(slots=True, frozen=True)
class SectionHint:
    start_s: float
    end_s: float
    label: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_s": self.start_s,
            "end_s": self.end_s,
            "label": self.label,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SectionHint:
        return cls(
            start_s=_as_float(payload, "start_s"),
            end_s=_as_float(payload, "end_s"),
            label=_as_str(payload, "label"),
            confidence=_as_float(payload, "confidence"),
        )


@dataclass(slots=True, frozen=True)
class AnalysisResult:
    schema_version: int
    generated_at: str
    file_path: str
    segment_start_s: float
    segment_duration_s: float | None
    analysis_duration_s: float
    sample_rate_hz: int
    metadata: FFProbeMetadata
    key: KeyEstimate
    beats: BeatSummary
    spectral: SpectralStats
    energy: EnergyDynamics
    section_hints: list[SectionHint]
    notes: list[str] = field(default_factory=list)
    plot_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "file_path": self.file_path,
            "segment_start_s": self.segment_start_s,
            "segment_duration_s": self.segment_duration_s,
            "analysis_duration_s": self.analysis_duration_s,
            "sample_rate_hz": self.sample_rate_hz,
            "metadata": self.metadata.to_dict(),
            "key": self.key.to_dict(),
            "beats": self.beats.to_dict(),
            "spectral": self.spectral.to_dict(),
            "energy": self.energy.to_dict(),
            "section_hints": [section.to_dict() for section in self.section_hints],
            "notes": list(self.notes),
            "plot_files": list(self.plot_files),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AnalysisResult:
        sections_raw = payload.get("section_hints", [])
        if not isinstance(sections_raw, list):
            raise ValueError("section_hints must be a list")
        notes_raw = payload.get("notes", [])
        if not isinstance(notes_raw, list):
            raise ValueError("notes must be a list")
        plots_raw = payload.get("plot_files", [])
        if not isinstance(plots_raw, list):
            raise ValueError("plot_files must be a list")

        return cls(
            schema_version=_as_int(payload, "schema_version"),
            generated_at=_as_str(payload, "generated_at"),
            file_path=_as_str(payload, "file_path"),
            segment_start_s=_as_float(payload, "segment_start_s"),
            segment_duration_s=_as_optional_float(payload, "segment_duration_s"),
            analysis_duration_s=_as_float(payload, "analysis_duration_s"),
            sample_rate_hz=_as_int(payload, "sample_rate_hz"),
            metadata=FFProbeMetadata.from_dict(_as_dict(payload, "metadata")),
            key=KeyEstimate.from_dict(_as_dict(payload, "key")),
            beats=BeatSummary.from_dict(_as_dict(payload, "beats")),
            spectral=SpectralStats.from_dict(_as_dict(payload, "spectral")),
            energy=EnergyDynamics.from_dict(_as_dict(payload, "energy")),
            section_hints=[
                SectionHint.from_dict(item)
                for item in sections_raw
                if isinstance(item, dict)
            ],
            notes=[str(x) for x in notes_raw],
            plot_files=[str(x) for x in plots_raw],
        )


def _as_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _as_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _as_optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _as_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _as_optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer or null")
    return value


def _as_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    return float(value)


def _as_optional_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric or null")
    return float(value)
