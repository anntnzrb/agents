from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import librosa
import numpy as np
from numpy.typing import NDArray

from .models import (
    SCHEMA_VERSION,
    AnalysisResult,
    BeatSummary,
    EnergyDynamics,
    FFProbeMetadata,
    KeyEstimate,
    NumericStats,
    SectionHint,
    SpectralStats,
)

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
)
_MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
)


def analyze_audio(
    audio_path: Path,
    *,
    segment_start_s: float = 0.0,
    segment_duration_s: float | None = None,
    plots: bool = False,
    plot_dir: Path | None = None,
) -> AnalysisResult:
    if segment_start_s < 0:
        raise ValueError("segment_start_s must be >= 0")
    if segment_duration_s is not None and segment_duration_s <= 0:
        raise ValueError("segment_duration_s must be > 0 when provided")

    y, sample_rate, load_notes = _load_audio_segment(
        audio_path,
        segment_start_s=segment_start_s,
        segment_duration_s=segment_duration_s,
    )
    if y.size == 0:
        raise ValueError("loaded audio segment is empty")

    analysis_duration_s = float(librosa.get_duration(y=y, sr=sample_rate))
    metadata = _probe_metadata(audio_path)

    tempo_raw, beat_frames = librosa.beat.beat_track(y=y, sr=sample_rate)
    tempo_bpm = float(np.asarray(tempo_raw).reshape(-1)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sample_rate)

    chroma = _compute_chroma(y, sample_rate)
    key_estimate = _estimate_key(chroma)

    centroid = librosa.feature.spectral_centroid(y=y, sr=sample_rate)[0]
    bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sample_rate)[0]
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sample_rate)[0]
    flatness = librosa.feature.spectral_flatness(y=y)[0]
    spectral = SpectralStats(
        centroid=_stats(centroid),
        bandwidth=_stats(bandwidth),
        rolloff=_stats(rolloff),
        flatness=_stats(flatness),
    )

    rms = librosa.feature.rms(y=y)[0]
    p05 = float(np.percentile(rms, 5))
    p25 = float(np.percentile(rms, 25))
    p75 = float(np.percentile(rms, 75))
    p95 = float(np.percentile(rms, 95))
    energy = EnergyDynamics(
        rms=_stats(rms),
        dynamic_range=max(0.0, p95 - p05),
        low_energy_ratio=float(np.mean(rms <= p25)),
        high_energy_ratio=float(np.mean(rms >= p75)),
    )

    sections = _section_hints(y, sample_rate, analysis_duration_s)
    notes = _tool_notes()
    notes.extend(load_notes)
    plot_files: list[str] = []
    if plots:
        plot_files, plot_notes = _render_plots(y, sample_rate, plot_dir)
        notes.extend(plot_notes)

    beats = BeatSummary(
        tempo_bpm=tempo_bpm,
        beat_count=int(beat_times.shape[0]),
        first_beat_s=None if beat_times.shape[0] == 0 else float(beat_times[0]),
        last_beat_s=None if beat_times.shape[0] == 0 else float(beat_times[-1]),
    )

    return AnalysisResult(
        schema_version=SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        file_path=audio_path.as_posix(),
        segment_start_s=segment_start_s,
        segment_duration_s=segment_duration_s,
        analysis_duration_s=analysis_duration_s,
        sample_rate_hz=int(sample_rate),
        metadata=metadata,
        key=key_estimate,
        beats=beats,
        spectral=spectral,
        energy=energy,
        section_hints=sections,
        notes=notes,
        plot_files=plot_files,
    )


def _load_audio_segment(
    audio_path: Path,
    *,
    segment_start_s: float,
    segment_duration_s: float | None,
) -> tuple[NDArray[np.float64], int, list[str]]:
    try:
        y, sample_rate = librosa.load(
            audio_path.as_posix(),
            sr=None,
            mono=True,
            offset=segment_start_s,
            duration=segment_duration_s,
        )
        return np.asarray(y, dtype=np.float64), int(sample_rate), []
    except Exception as exc:  # noqa: BLE001
        librosa_error = exc

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        temp_wav = Path(tmp.name)

    command = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-ss",
        f"{segment_start_s:.6f}",
        "-i",
        audio_path.as_posix(),
    ]
    if segment_duration_s is not None:
        command.extend(["-t", f"{segment_duration_s:.6f}"])
    command.extend(["-ac", "1", "-vn", "-sn", "-dn", temp_wav.as_posix()])

    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
        y, sample_rate = librosa.load(temp_wav.as_posix(), sr=None, mono=True)
        note = (
            "audio load fallback: used ffmpeg transcoding after librosa.load failed "
            f"({type(librosa_error).__name__})"
        )
        return np.asarray(y, dtype=np.float64), int(sample_rate), [note]
    except FileNotFoundError as exc:
        raise RuntimeError(
            "librosa.load failed and ffmpeg is unavailable for fallback",
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(
            f"librosa.load failed and ffmpeg fallback failed{detail}",
        ) from exc
    finally:
        try:
            temp_wav.unlink(missing_ok=True)
        except OSError:
            pass


def _compute_chroma(y: NDArray[np.float64], sample_rate: int) -> NDArray[np.float64]:
    try:
        return np.asarray(
            librosa.feature.chroma_cqt(y=y, sr=sample_rate),
            dtype=np.float64,
        )
    except Exception:
        return np.asarray(
            librosa.feature.chroma_stft(y=y, sr=sample_rate),
            dtype=np.float64,
        )


def _estimate_key(chroma: NDArray[np.float64]) -> KeyEstimate:
    chroma_profile = np.mean(chroma, axis=1, dtype=np.float64)
    chroma_profile = np.maximum(chroma_profile, 0.0)
    total = float(np.sum(chroma_profile))
    if total > 0:
        chroma_profile = chroma_profile / total

    normalized_chroma = _normalized_profile(chroma_profile)
    if np.allclose(normalized_chroma, 0.0):
        return KeyEstimate(
            key="C",
            mode="major",
            confidence=0.0,
            chroma_profile=[float(v) for v in chroma_profile.tolist()],
        )

    major_profile = _normalized_profile(_MAJOR_PROFILE)
    minor_profile = _normalized_profile(_MINOR_PROFILE)

    candidates: list[tuple[float, str, int]] = []
    for shift in range(12):
        major_score = float(np.dot(normalized_chroma, np.roll(major_profile, shift)))
        minor_score = float(np.dot(normalized_chroma, np.roll(minor_profile, shift)))
        candidates.append((major_score, "major", shift))
        candidates.append((minor_score, "minor", shift))

    scores = np.asarray([item[0] for item in candidates], dtype=np.float64)
    ranked = np.argsort(scores)[::-1]
    best_index = int(ranked[0])
    _, best_mode, best_shift = candidates[best_index]
    confidence = _score_confidence(scores, best_index)

    return KeyEstimate(
        key=_NOTE_NAMES[best_shift],
        mode=best_mode,
        confidence=confidence,
        chroma_profile=[float(v) for v in chroma_profile.tolist()],
    )


def _normalized_profile(values: NDArray[np.float64]) -> NDArray[np.float64]:
    centered = np.asarray(values, dtype=np.float64) - float(np.mean(values))
    norm = float(np.linalg.norm(centered))
    if norm <= 1e-12:
        return np.zeros_like(centered, dtype=np.float64)
    return centered / norm


def _score_confidence(scores: NDArray[np.float64], best_index: int) -> float:
    if scores.size == 0:
        return 0.0
    shifted = scores - float(np.max(scores))
    temperature = 0.15
    weights = np.exp(shifted / temperature)
    total = float(np.sum(weights))
    if total <= 0.0 or not np.isfinite(total):
        return 0.0
    return float(max(0.0, min(1.0, weights[best_index] / total)))


def _stats(values: NDArray[np.float64]) -> NumericStats:
    if values.size == 0:
        return NumericStats(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return NumericStats(
        mean=float(np.mean(values)),
        std=float(np.std(values)),
        minimum=float(np.min(values)),
        maximum=float(np.max(values)),
        p10=float(np.percentile(values, 10)),
        p90=float(np.percentile(values, 90)),
    )


def _section_hints(
    y: NDArray[np.float64],
    sample_rate: int,
    duration_s: float,
) -> list[SectionHint]:
    onset_env = librosa.onset.onset_strength(y=y, sr=sample_rate)
    onset_times = librosa.times_like(onset_env, sr=sample_rate)
    onset_peaks = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sample_rate,
        units="time",
        backtrack=False,
        normalize=True,
    )

    boundaries = [0.0]
    min_gap = max(8.0, duration_s / 8.0)
    for value in onset_peaks:
        t = float(value)
        if t <= 0.0 or t >= duration_s:
            continue
        if t - boundaries[-1] >= min_gap:
            boundaries.append(t)
        if len(boundaries) >= 8:
            break
    if duration_s - boundaries[-1] >= 2.0:
        boundaries.append(duration_s)
    else:
        boundaries[-1] = duration_s

    if len(boundaries) < 2:
        return []

    section_labels = ["intro", "verse", "chorus", "verse", "chorus", "bridge", "outro"]
    strengths: list[float] = []
    sections: list[tuple[float, float, str]] = []
    for index in range(len(boundaries) - 1):
        start = boundaries[index]
        end = boundaries[index + 1]
        label = section_labels[min(index, len(section_labels) - 1)]
        sections.append((start, end, label))
        mask = (onset_times >= start) & (onset_times < end)
        strength = float(np.mean(onset_env[mask])) if np.any(mask) else 0.0
        strengths.append(strength)

    max_strength = max(strengths) if strengths else 1.0
    if max_strength <= 0:
        max_strength = 1.0

    return [
        SectionHint(
            start_s=start,
            end_s=end,
            label=label,
            confidence=float(max(0.05, min(1.0, strength / max_strength))),
        )
        for (start, end, label), strength in zip(sections, strengths, strict=True)
    ]


def _probe_metadata(audio_path: Path) -> FFProbeMetadata:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-print_format",
        "json",
        audio_path.as_posix(),
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return FFProbeMetadata(
            container=None,
            codec=None,
            sample_rate_hz=None,
            channels=None,
            bit_rate=None,
            duration_s=None,
            tags={},
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {}

    format_obj = payload.get("format", {}) if isinstance(payload, dict) else {}
    streams = payload.get("streams", []) if isinstance(payload, dict) else []
    audio_stream: dict[str, Any] | None = None
    if isinstance(streams, list):
        for stream in streams:
            if isinstance(stream, dict) and stream.get("codec_type") == "audio":
                audio_stream = stream
                break
    if audio_stream is None:
        audio_stream = {}

    tags_raw = format_obj.get("tags", {}) if isinstance(format_obj, dict) else {}
    tags = (
        {str(k): str(v) for k, v in tags_raw.items()}
        if isinstance(tags_raw, dict)
        else {}
    )

    return FFProbeMetadata(
        container=_maybe_str(format_obj.get("format_name")),
        codec=_maybe_str(audio_stream.get("codec_name")),
        sample_rate_hz=_maybe_int(audio_stream.get("sample_rate")),
        channels=_maybe_int(audio_stream.get("channels")),
        bit_rate=_maybe_int(format_obj.get("bit_rate")),
        duration_s=_maybe_float(format_obj.get("duration")),
        tags=tags,
    )


def _tool_notes() -> list[str]:
    notes: list[str] = []
    ffmpeg_version = _read_version_line("ffmpeg")
    ffprobe_version = _read_version_line("ffprobe")
    if ffmpeg_version is not None:
        notes.append(ffmpeg_version)
    if ffprobe_version is not None:
        notes.append(ffprobe_version)
    return notes


def _read_version_line(tool: str) -> str | None:
    try:
        proc = subprocess.run(
            [tool, "-version"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    line = proc.stdout.splitlines()[0].strip() if proc.stdout else ""
    return None if not line else line


def _render_plots(
    y: NDArray[np.float64],
    sample_rate: int,
    plot_dir: Path | None,
) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    if plot_dir is None:
        return [], ["plots requested but no plot_dir provided"]

    try:
        import matplotlib.pyplot as plt
    except Exception:
        return [], ["plots requested but matplotlib is unavailable"]

    plot_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []

    time_axis = np.linspace(0.0, len(y) / sample_rate, num=len(y), endpoint=False)
    waveform_path = plot_dir / "waveform.png"
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(time_axis, y, linewidth=0.6)
    ax.set_title("Waveform")
    ax.set_xlabel("Seconds")
    ax.set_ylabel("Amplitude")
    fig.tight_layout()
    fig.savefig(waveform_path)
    plt.close(fig)
    files.append(waveform_path.as_posix())

    spectrogram_path = plot_dir / "spectrogram.png"
    fig, ax = plt.subplots(figsize=(10, 4))
    spectrum = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    db = librosa.amplitude_to_db(spectrum, ref=np.max)
    img = ax.imshow(db, aspect="auto", origin="lower", cmap="magma")
    ax.set_title("Spectrogram (dB)")
    ax.set_xlabel("Frame")
    ax.set_ylabel("Frequency bin")
    fig.colorbar(img, ax=ax, format="%+2.0f dB")
    fig.tight_layout()
    fig.savefig(spectrogram_path)
    plt.close(fig)
    files.append(spectrogram_path.as_posix())

    chroma_path = plot_dir / "chroma.png"
    fig, ax = plt.subplots(figsize=(10, 3))
    chroma = _compute_chroma(y, sample_rate)
    img = ax.imshow(chroma, aspect="auto", origin="lower", cmap="viridis")
    ax.set_title("Chroma")
    ax.set_xlabel("Frame")
    ax.set_ylabel("Pitch class")
    fig.colorbar(img, ax=ax)
    fig.tight_layout()
    fig.savefig(chroma_path)
    plt.close(fig)
    files.append(chroma_path.as_posix())

    notes.append(f"wrote {len(files)} plot files")
    return files, notes


def _maybe_int(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _maybe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _maybe_str(raw: Any) -> str | None:
    if raw is None:
        return None
    return str(raw)
