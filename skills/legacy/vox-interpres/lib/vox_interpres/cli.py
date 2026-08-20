from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .io import (
    cache_path_for,
    ensure_out_dir,
    load_analysis,
    save_analysis,
    validate_audio_path,
)
from .query import answer_question


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vox-interpres",
        description="Analyze songs and answer questions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze",
        help="Extract audio features and store analysis cache.",
    )
    _add_common_analysis_args(analyze)
    analyze.add_argument(
        "--json",
        action="store_true",
        help="Print analysis JSON to stdout.",
    )

    ask = subparsers.add_parser(
        "ask",
        help="Answer one natural-language question over analysis.",
    )
    _add_common_analysis_args(ask)
    ask.add_argument("question", help="Question to answer.")

    chat = subparsers.add_parser("chat", help="REPL chat over one loaded analysis.")
    _add_common_analysis_args(chat)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    try:
        if args.command == "analyze":
            return _cmd_analyze(args)
        if args.command == "ask":
            return _cmd_ask(args)
        if args.command == "chat":
            return _cmd_chat(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("error: unknown command", file=sys.stderr)
    return 1


def _add_common_analysis_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "audio",
        type=Path,
        help="Audio file (.mp3/.flac/.wav/.ogg/.m4a).",
    )
    parser.add_argument(
        "--segment-start",
        type=float,
        default=0.0,
        help="Start offset in seconds.",
    )
    parser.add_argument(
        "--segment-duration",
        type=float,
        default=None,
        help="Segment duration in seconds.",
    )
    parser.add_argument(
        "--plots",
        action="store_true",
        help="Write waveform/spectrogram/chroma plots.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / ".cache" / "vox-interpres",
        help="Cache/output directory.",
    )
    parser.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use analysis cache if present (use --no-cache to disable).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cache and recompute analysis.",
    )


def _cmd_analyze(args: argparse.Namespace) -> int:
    analysis, cache_path, was_cached = _load_or_build_analysis(args)
    if args.json:
        print(json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False))
    else:
        status = "cache hit" if was_cached else "computed"
        print(f"[{status}] {cache_path}")
        print(
            f"tempo={analysis.beats.tempo_bpm:.1f} bpm | "
            f"key={analysis.key.key} {analysis.key.mode} | "
            f"duration={analysis.analysis_duration_s:.2f}s",
        )
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    analysis, _, _ = _load_or_build_analysis(args)
    answer = answer_question(analysis, args.question)
    print(answer.text)
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    analysis, _, _ = _load_or_build_analysis(args)
    print(
        "chat ready. ask about tempo/key/energy/sections/metadata. type 'exit' to quit.",
    )
    while True:
        try:
            question = input("ask> ").strip()
        except EOFError:
            print()
            return 0
        if not question:
            continue
        if question.casefold() in {"exit", "quit", ":q"}:
            return 0
        answer = answer_question(analysis, question)
        print(answer.text)


def _load_or_build_analysis(args: argparse.Namespace):
    audio_path = validate_audio_path(Path(args.audio))
    out_dir = ensure_out_dir(Path(args.out_dir))
    cache_path = cache_path_for(
        out_dir,
        audio_path,
        float(args.segment_start),
        args.segment_duration,
    )

    use_cache = bool(args.cache) and not bool(args.refresh)
    if use_cache and cache_path.exists():
        return load_analysis(cache_path), cache_path, True

    from .analyze import analyze_audio

    plot_dir = out_dir / "plots" / cache_path.stem if args.plots else None
    analysis = analyze_audio(
        audio_path,
        segment_start_s=float(args.segment_start),
        segment_duration_s=args.segment_duration,
        plots=bool(args.plots),
        plot_dir=plot_dir,
    )
    if args.cache:
        save_analysis(cache_path, analysis)
    return analysis, cache_path, False


if __name__ == "__main__":
    raise SystemExit(main())
