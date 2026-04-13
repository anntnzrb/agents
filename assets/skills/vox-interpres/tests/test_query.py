from vox_interpres.models import (
    AnalysisResult,
    BeatSummary,
    EnergyDynamics,
    FFProbeMetadata,
    KeyEstimate,
    NumericStats,
    SectionHint,
    SpectralStats,
)
from vox_interpres.query import answer_question, classify_intent


def _stats(value: float) -> NumericStats:
    return NumericStats(value, 0.1, value - 0.5, value + 0.5, value - 0.2, value + 0.2)


def _analysis() -> AnalysisResult:
    return AnalysisResult(
        schema_version=1,
        generated_at="2026-01-01T00:00:00Z",
        file_path="/tmp/demo.mp3",
        segment_start_s=0.0,
        segment_duration_s=None,
        analysis_duration_s=120.0,
        sample_rate_hz=44100,
        metadata=FFProbeMetadata(
            container="mp3",
            codec="mp3",
            sample_rate_hz=44100,
            channels=2,
            bit_rate=192000,
            duration_s=120.0,
            tags={"artist": "test"},
        ),
        key=KeyEstimate(key="A", mode="minor", confidence=0.72, chroma_profile=[0.1] * 12),
        beats=BeatSummary(tempo_bpm=128.0, beat_count=250, first_beat_s=0.3, last_beat_s=119.5),
        spectral=SpectralStats(
            centroid=_stats(2100.0),
            bandwidth=_stats(1200.0),
            rolloff=_stats(4000.0),
            flatness=_stats(0.23),
        ),
        energy=EnergyDynamics(
            rms=_stats(0.17),
            dynamic_range=0.4,
            low_energy_ratio=0.25,
            high_energy_ratio=0.22,
        ),
        section_hints=[SectionHint(start_s=0.0, end_s=30.0, label="intro", confidence=0.9)],
        notes=[],
        plot_files=[],
    )


def test_classify_intent_deterministic_keywords() -> None:
    assert classify_intent("what key is this in?") == "key"
    assert classify_intent("tempo bpm?") == "tempo"
    assert classify_intent("give me metadata codec") == "metadata"


def test_answer_mentions_tempo_and_key() -> None:
    analysis = _analysis()
    tempo = answer_question(analysis, "tempo?")
    key = answer_question(analysis, "what key?")

    assert tempo.intent == "tempo"
    assert "128.0" in tempo.text
    assert key.intent == "key"
    assert "A minor" in key.text


def test_multi_intent_question_combines_tempo_and_key() -> None:
    analysis = _analysis()
    answer = answer_question(analysis, "tempo and key?")

    assert answer.intent == "tempo"
    assert "Tempo ~128.0 BPM" in answer.text
    assert "Estimated key: A minor" in answer.text
