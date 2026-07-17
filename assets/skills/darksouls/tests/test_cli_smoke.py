from __future__ import annotations

import json
import os
import struct
import subprocess
import tempfile
import unittest
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict, cast


class CalcPayload(TypedDict):
    name: str
    approximate: bool
    requirements_met: bool
    estimated_ar: float
    warning: str


class CompareRow(TypedDict):
    name: str
    approximate: bool


class HiddenGuidePayload(TypedDict):
    row: int
    spoilers: str
    warning: str


class RevealedGuidePayload(TypedDict):
    row: int
    h: list[str]
    t: str


class RevealedGuidePayloadWithOptionalSpoilers(RevealedGuidePayload, total=False):
    spoilers: str


SKILL_DIR = Path(__file__).resolve().parents[1]


def run_cli(
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        ["uv", "run", "--script", "scripts/cli.py", *arguments],
        cwd=SKILL_DIR,
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _dcx(payload: bytes) -> bytes:
    result = bytearray(0x4C)
    result[:4] = b"DCX\0"
    result.extend(zlib.compress(payload))
    return bytes(result)


def _bnd3(members: list[tuple[str, bytes]]) -> bytes:
    table_offset = 0x20
    entry_size = 0x18
    data_offset = table_offset + entry_size * len(members)
    names = [name.encode("ascii") + b"\0" for name, _ in members]
    names_offset = data_offset + sum(len(payload) for _, payload in members)
    result = bytearray(names_offset + sum(len(name) for name in names))
    result[:4] = b"BND3"
    struct.pack_into("<I", result, 0x10, len(members))
    data_cursor = data_offset
    name_cursor = names_offset
    for index, ((_, payload), name) in enumerate(zip(members, names)):
        struct.pack_into(
            "<IIIII",
            result,
            table_offset,
            0,
            len(payload),
            data_cursor,
            index,
            name_cursor,
        )
        result[data_cursor : data_cursor + len(payload)] = payload
        result[name_cursor : name_cursor + len(name)] = name
        table_offset += entry_size
        data_cursor += len(payload)
        name_cursor += len(name)
    return bytes(result)


def _param(
    size: int,
    row_id: int,
    name: str,
    configure: Callable[[memoryview], None] | None = None,
) -> bytes:
    row_offset = 0x3C
    name_offset = row_offset + size
    result = bytearray(name_offset + len(name) + 1)
    struct.pack_into("<III", result, 0x30, row_id, row_offset, name_offset)
    struct.pack_into("<I", result, 0x34, 0x3C)
    row = memoryview(result)[row_offset:name_offset]
    if configure is not None:
        configure(row)
    result[name_offset : name_offset + len(name)] = name.encode("ascii")
    return bytes(result)


def _empty_tae() -> bytes:
    result = bytearray(0x78)
    result[:4] = b"TAE "
    result[7] = 0
    struct.pack_into("<I", result, 0x08, 0x1000B)
    struct.pack_into("<II", result, 0x54, 1, 0x5C)
    struct.pack_into("<II", result, 0x5C, 6000, 0x70)
    struct.pack_into("<iI", result, 0x70, 0, 0x74)
    return bytes(result)


def _synthetic_install(root: Path) -> None:
    def weapon(row: memoryview) -> None:
        struct.pack_into("<i", row, 0, 1)
        row[226] = 0
        row[227] = 0

    def goods(row: memoryview) -> None:
        row[62] = 1
        row[68] |= 0x80

    def behavior(row: memoryview) -> None:
        struct.pack_into("<ii", row, 0, 1, 9)

    game = root / "param" / "GameParam"
    chr_dir = root / "chr"
    game.mkdir(parents=True)
    chr_dir.mkdir(parents=True)
    members = [
        ("EquipParamWeapon.param", _param(0x110, 1000, "synthetic_weapon", weapon)),
        ("EquipParamGoods.param", _param(92, 1001, "synthetic_item", goods)),
        ("BehaviorParam_PC.param", _param(20, 2000, "synthetic_behavior", behavior)),
    ]
    (game / "GameParam.parambnd.dcx").write_bytes(_dcx(_bnd3(members)))
    (chr_dir / "c0000.anibnd.dcx").write_bytes(_dcx(_bnd3([("a00.tae", _empty_tae())])))


class CliSmokeTests(unittest.TestCase):
    def test_fresh_and_calc_json_are_deterministic_contracts(self) -> None:
        fresh = run_cli("fresh")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertIn("Dark Souls Remastered", fresh.stdout)
        self.assertIn("Next: softcaps", fresh.stdout)

        calculated = run_cli("calc", "Claymore", "40", "40", "--json")
        self.assertEqual(calculated.returncode, 0, calculated.stderr)
        payload = cast("CalcPayload", json.loads(calculated.stdout))
        self.assertEqual(payload["name"], "Claymore")
        self.assertTrue(payload["approximate"])
        self.assertTrue(payload["requirements_met"])
        self.assertIn("estimated_ar", payload)
        self.assertIn("status screen", payload["warning"])

    def test_compare_json_contains_both_requested_weapons(self) -> None:
        compared = run_cli(
            "compare",
            "Longsword",
            "Claymore",
            "--str",
            "40",
            "--dex",
            "40",
            "--json",
        )
        self.assertEqual(compared.returncode, 0, compared.stderr)
        rows = cast("list[CompareRow]", json.loads(compared.stdout))
        self.assertEqual({row["name"] for row in rows}, {"Longsword", "Claymore"})
        self.assertTrue(all(row["approximate"] for row in rows))

    def test_sources_status_uses_only_the_process_cache_environment(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            first_result = run_cli("sources", "status", env={"DS1_CACHE_DIR": first})
            second_result = run_cli("sources", "status", env={"DS1_CACHE_DIR": second})
            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertIn(f"Cache directory: {first}", first_result.stdout)
            self.assertIn(f"Cache directory: {second}", second_result.stdout)
            self.assertNotIn(f"Cache directory: {second}", first_result.stdout)
            self.assertNotIn(f"Cache directory: {first}", second_result.stdout)
            self.assertEqual(list(Path(first).iterdir()), [])
            self.assertEqual(list(Path(second).iterdir()), [])

    def test_audit_reports_an_integrated_clean_skill(self) -> None:
        result = run_cli("audit")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "OK: DS1 core, source metadata, guide schema, and catalog checks passed",
            result.stdout,
        )

    def test_guide_get_hides_transformed_text_by_default(self) -> None:
        redacted = run_cli("guide", "get", "1", "--json")
        self.assertEqual(redacted.returncode, 0, redacted.stderr)
        hidden = cast("HiddenGuidePayload", json.loads(redacted.stdout))
        self.assertEqual(hidden["row"], 1)
        self.assertEqual(hidden["spoilers"], "hidden")
        self.assertNotIn("h", hidden)
        self.assertNotIn("t", hidden)
        warning = hidden.get("warning")
        self.assertIsInstance(warning, str)
        self.assertIn("Local guide lookup:", warning)
        self.assertIn("transformed", warning)
        self.assertIn("non-authoritative", warning)
        self.assertIn("not save/parser truth", warning)

        revealed = run_cli("guide", "get", "1", "--json", "--spoilers")
        self.assertEqual(revealed.returncode, 0, revealed.stderr)
        row = cast(
            "RevealedGuidePayloadWithOptionalSpoilers",
            json.loads(revealed.stdout),
        )
        self.assertEqual(row["row"], 1)
        self.assertIsInstance(row["h"], list)
        self.assertTrue(row["t"].strip())
        self.assertNotEqual(row["spoilers"] if "spoilers" in row else None, "hidden")

    def test_transcript_info_redacts_by_default_even_in_json_and_human_output(
        self,
    ) -> None:
        hidden_json_result = run_cli("transcript", "info", "--json")
        self.assertEqual(hidden_json_result.returncode, 0, hidden_json_result.stderr)
        hidden_json = cast("dict[str, object]", json.loads(hidden_json_result.stdout))
        self.assertEqual(hidden_json["video_count"], 30)
        self.assertEqual(hidden_json["chunk_count"], 672)
        self.assertNotIn("videos", hidden_json)
        warning = str(hidden_json["warning"])
        self.assertIn("automatic-caption", warning)
        self.assertIn("spoiler-heavy", warning)
        self.assertIn("non-authoritative", warning)
        self.assertIn("not mechanics/save/parser/route truth", warning)
        hidden_human_result = run_cli("transcript", "list")
        self.assertEqual(hidden_human_result.returncode, 0, hidden_human_result.stderr)

        self.assertIn(
            "Local automatic-caption transcript lookup",
            hidden_human_result.stdout,
        )
        self.assertIn('"spoilers": "hidden"', hidden_human_result.stdout)
        self.assertNotIn("LVTwgOlWWAM", hidden_human_result.stdout)
        self.assertNotIn("https://www.youtube.com/watch", hidden_human_result.stdout)

    def test_transcript_spoilers_reveal_metadata_and_chunk_text(self) -> None:
        info = run_cli("transcript", "info", "--json", "--spoilers")
        self.assertEqual(info.returncode, 0, info.stderr)
        payload = cast("dict[str, object]", json.loads(info.stdout))
        videos = cast("list[dict[str, object]]", payload["videos"])
        self.assertEqual(len(videos), 30)
        self.assertEqual(videos[0]["caption_track"], "en-orig")
        self.assertTrue(str(videos[0]["video_id"]))

        revealed = run_cli("transcript", "get", "0", "0", "--json", "--spoilers")
        self.assertEqual(revealed.returncode, 0, revealed.stderr)
        row = cast("dict[str, object]", json.loads(revealed.stdout))
        self.assertEqual(row["video_index"], 0)
        self.assertEqual(row["chunk_index"], 0)
        self.assertTrue(str(row["t"]).strip())
        self.assertIn("video_id", row)

    def test_transcript_search_query_and_spoiler_gates(self) -> None:
        no_query = run_cli("transcript", "search", "--json")
        self.assertEqual(no_query.returncode, 0, no_query.stderr)
        no_query_payload = cast("dict[str, object]", json.loads(no_query.stdout))
        self.assertEqual(no_query_payload["video_count"], 30)
        self.assertNotIn("videos", no_query_payload)

        hidden = run_cli("transcript", "search", "walkthrough", "--json")
        self.assertEqual(hidden.returncode, 0, hidden.stderr)
        hidden_rows = cast("list[dict[str, object]]", json.loads(hidden.stdout))
        self.assertTrue(hidden_rows)
        self.assertNotIn("t", hidden_rows[0])
        self.assertEqual(hidden_rows[0]["spoilers"], "hidden")

        revealed = run_cli(
            "transcript",
            "search",
            "walkthrough",
            "--json",
            "--spoilers",
        )
        self.assertEqual(revealed.returncode, 0, revealed.stderr)
        revealed_rows = cast("list[dict[str, object]]", json.loads(revealed.stdout))
        self.assertTrue(revealed_rows)
        self.assertTrue(str(revealed_rows[0]["t"]).strip())

    def test_transcript_get_bounds_and_corpus_warning(self) -> None:
        out_of_range = run_cli("transcript", "get", "30", "0", "--json", "--spoilers")
        self.assertNotEqual(out_of_range.returncode, 0)
        self.assertIn("out of range", out_of_range.stderr.casefold())

        hidden = run_cli("transcript", "get", "0", "0", "--json")
        self.assertEqual(hidden.returncode, 0, hidden.stderr)
        payload = cast("dict[str, object]", json.loads(hidden.stdout))
        self.assertNotIn("t", payload)
        self.assertIn("warning", payload)
        self.assertIn("automatic-caption", str(payload["warning"]))

    def test_transcript_is_separate_from_guide_save_and_mechanics_contracts(
        self,
    ) -> None:
        result = run_cli("transcript", "info", "--json", "--spoilers")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout.casefold()
        self.assertNotIn("psnprofiles", output)
        self.assertNotIn("guide lookup", output)
        self.assertNotIn("save state", output)
        self.assertNotIn("mechanics catalog", output)

    def test_achievement_cli_exposes_static_labels_only_with_spoilers(self) -> None:
        hidden = run_cli("achievements")
        self.assertEqual(hidden.returncode, 0, hidden.stderr)
        self.assertIn("names hidden; use --spoilers", hidden.stdout)
        self.assertNotIn("Enkindle", hidden.stdout)

        visible = run_cli("achievements", "--spoilers")
        self.assertEqual(visible.returncode, 0, visible.stderr)
        self.assertIn("- Enkindle", visible.stdout)

    def test_frames_requires_an_explicit_install_argument(self) -> None:
        result = run_cli("frames")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--install", result.stderr)

    def test_frames_no_query_emits_only_a_summary_for_synthetic_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _synthetic_install(Path(temporary))
            files_before = {
                path.relative_to(temporary): path.read_bytes()
                for path in Path(temporary).rglob("*")
                if path.is_file()
            }
            result = run_cli("frames", "--install", temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = result.stdout.casefold()
            self.assertIn("frame scan summary", output)
            self.assertIn("weapons=", output)
            self.assertIn("items=", output)
            self.assertNotIn("synthetic_weapon", output)
            self.assertNotIn("synthetic_item", output)
            files_after = {
                path.relative_to(temporary): path.read_bytes()
                for path in Path(temporary).rglob("*")
                if path.is_file()
            }
            self.assertEqual(files_after, files_before)

    def test_malformed_save_cli_fails_without_writing_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.sl2"
            path.write_bytes(b"not a DSR save")
            before = path.read_bytes()
            result = run_cli("save", str(path), "summary")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unsupported DSR save size", result.stderr)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(temporary).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
