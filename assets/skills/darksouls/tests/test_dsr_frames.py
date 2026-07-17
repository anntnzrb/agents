from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ds1_frames as frames  # noqa: E402


class DsrFrameParserTests(unittest.TestCase):
    @staticmethod
    def _dcx(payload: bytes) -> bytes:
        import zlib

        result = bytearray(0x4C)
        result[:4] = b"DCX\x00"
        result[0x10:0x14] = b"DCS\x00"
        result[0x20:0x24] = b"DCP\x00"
        result.extend(zlib.compress(payload))
        return bytes(result)

    @staticmethod
    def _bnd3(*payloads: bytes) -> bytes:
        table_offset = 0x20
        entry_size = 0x18
        data_offset = table_offset + entry_size * len(payloads)
        names = [
            f"synthetic-{index}".encode("ascii") + b"\0"
            for index in range(len(payloads))
        ]
        names_offset = data_offset + sum(len(payload) for payload in payloads)
        result = bytearray(names_offset + sum(len(name) for name in names))
        result[:4] = b"BND3"
        struct.pack_into("<I", result, 0x10, len(payloads))
        cursor = data_offset
        name_cursor = names_offset
        for index, (payload, name) in enumerate(zip(payloads, names)):
            struct.pack_into(
                "<IIIII",
                result,
                table_offset,
                0,
                len(payload),
                cursor,
                index,
                name_cursor,
            )
            result[cursor : cursor + len(payload)] = payload
            result[name_cursor : name_cursor + len(name)] = name
            table_offset += entry_size
            cursor += len(payload)
            name_cursor += len(name)
        return bytes(result)

    @staticmethod
    def _tae_one_event(start: float, end: float) -> bytes:
        # Minimal TAE v0x1000B header with one animation and one type-1 event.
        result = bytearray(0xBC)
        result[:4] = b"TAE "
        result[7] = 0
        struct.pack_into("<I", result, 0x08, 0x1000B)
        struct.pack_into("<I", result, 0x54, 1)
        struct.pack_into("<I", result, 0x58, 0x5C)
        struct.pack_into("<II", result, 0x5C, 3000, 0x70)
        struct.pack_into("<iI", result, 0x70, 1, 0x80)
        struct.pack_into("<III", result, 0x80, 0xA0, 0xA4, 0xA8)
        struct.pack_into("<ff", result, 0xA0, start, end)
        struct.pack_into("<iiiii", result, 0xA8, 1, 0, 7, 8, 9)
        return bytes(result)

    def test_dcx_and_bnd3_bounds_are_checked_before_decompression_or_table_read(
        self,
    ) -> None:
        payload = self._bnd3(b"TAE\x00")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.dcx"
            path.write_bytes(self._dcx(payload))
            members = frames._read_dcx_bnd3(path)
            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].data, b"TAE\x00")
            path.write_bytes(b"DCX\x00" + b"\0" * 20)
            with self.assertRaises(frames.FrameFormatError):
                frames._read_dcx_bnd3(path)
            path.write_bytes(self._dcx(b"BND3" + b"\0" * 8))
            with self.assertRaises(frames.FrameFormatError):
                frames._read_dcx_bnd3(path)

    def test_tae_preserves_float32_windows_and_derived_30fps_frames(self) -> None:
        # Values deliberately cannot be represented exactly as decimal binary
        # floats; assertions use the decoded float32 value, not rounded input.
        payload = self._tae_one_event(0.10000000149, 0.33333334327)
        animations = frames._read_tae(payload)
        self.assertEqual(len(animations), 1)
        self.assertEqual(animations[0].animation_id, 3000)
        self.assertEqual(len(animations[0].events), 1)
        event = animations[0].events[0]
        start = struct.unpack("<f", struct.pack("<f", 0.10000000149))[0]
        end = struct.unpack("<f", struct.pack("<f", 0.33333334327))[0]
        self.assertEqual(event.start_seconds, start)
        self.assertEqual(event.end_seconds, end)
        self.assertEqual(event.start_frame, round(start * 30))
        self.assertEqual(event.end_frame, round(end * 30))
        with self.assertRaises(frames.FrameFormatError):
            frames._read_tae(payload[:0x70])


class DsrFrameSelectionTests(unittest.TestCase):
    def _scan(self) -> frames.ScanResult:
        weapon = {
            "kind": "weapon",
            "name": "Synthetic Sword",
            "timing": {"label": "weapon.confirmed_event1_join", "start_frame": 3},
        }
        item = {
            "kind": "item",
            "name": "Synthetic Flask",
            "timing": {"label": "goods.category_representative_only", "start_frame": 9},
        }
        return cast(
            "frames.ScanResult",
            SimpleNamespace(
                schema_version="dsr-frame-scan.v1",
                frame_rate=30,
                weapons=(weapon,),
                goods=(item,),
                items=(item,),
                summary={"weapons": 1, "items": 1},
                issues=(),
                provenance=(),
                sources={"synthetic": "synthetic"},
            ),
        )

    def test_no_query_hides_names_but_query_and_spoilers_reveal_selected_records(
        self,
    ) -> None:
        scan = self._scan()
        hidden = frames.to_jsonable(
            frames.select_frame_records(
                scan,
                kind="all",
                query=None,
                spoilers=False,
                limit=50,
            ),
        )
        text = repr(hidden)
        self.assertNotIn("Synthetic Sword", text)
        self.assertNotIn("Synthetic Flask", text)

        selected = frames.to_jsonable(
            frames.select_frame_records(
                scan,
                kind="weapon",
                query="sword",
                spoilers=False,
                limit=50,
            ),
        )
        self.assertIn("Synthetic Sword", repr(selected))
        revealed = frames.to_jsonable(
            frames.select_frame_records(
                scan,
                kind="all",
                query=None,
                spoilers=True,
                limit=50,
            ),
        )
        self.assertIn("Synthetic Sword", repr(revealed))
        self.assertIn("Synthetic Flask", repr(revealed))

    def test_exact_normalized_query_precedes_substring_collisions(self) -> None:
        exact = {
            "kind": "weapon",
            "id": "weapon_100",
            "name": "Dagger",
            "timing": {"label": "weapon.synthetic_exact", "start_frame": 1},
        }
        suffix = {
            "kind": "weapon",
            "id": "weapon_101",
            "name": "Dagger Long",
            "timing": {"label": "weapon.synthetic_suffix", "start_frame": 2},
        }
        prefix = {
            "kind": "weapon",
            "id": "weapon_102",
            "name": "Dark Dagger",
            "timing": {"label": "weapon.synthetic_prefix", "start_frame": 3},
        }
        scan = frames.ScanResult(
            "dsr-frame-scan.v1",
            30,
            {"weapons": 3, "items": 0},
            (exact, suffix, prefix),
            (),
            {"synthetic": "synthetic"},
        )

        selected = frames.to_jsonable(
            frames.select_frame_records(
                scan,
                kind="weapon",
                query="DAGGER",
                spoilers=False,
                limit=50,
            ),
        )
        exact_records = cast("list[dict[str, object]]", selected["records"])
        self.assertEqual([record["name"] for record in exact_records], ["Dagger"])

        fallback = frames.to_jsonable(
            frames.select_frame_records(
                scan,
                kind="weapon",
                query="dag",
                spoilers=False,
                limit=50,
            ),
        )
        fallback_records = cast("list[dict[str, object]]", fallback["records"])
        self.assertEqual(
            [record["name"] for record in fallback_records],
            ["Dagger", "Dagger Long", "Dark Dagger"],
        )

    def test_kind_query_and_limit_are_validated_and_applied(self) -> None:
        scan = self._scan()
        limited = frames.select_frame_records(
            scan,
            kind="all",
            query="synthetic",
            spoilers=True,
            limit=1,
        )
        payload = frames.to_jsonable(limited)
        records = cast("list[object]", payload.get("records", []))
        self.assertEqual(len(records), 1)
        with self.assertRaises(frames.FrameQueryError):
            frames.select_frame_records(
                scan,
                kind="armor",
                query=None,
                spoilers=True,
                limit=50,
            )
        with self.assertRaises(frames.FrameQueryError):
            frames.select_frame_records(
                scan,
                kind="all",
                query=None,
                spoilers=False,
                limit=-1,
            )
        with self.assertRaises(frames.FrameQueryError):
            frames.select_frame_records(
                scan,
                kind="all",
                query="missing",
                spoilers=False,
                limit=50,
            )


class DsrFrameInstallTests(unittest.TestCase):
    def test_missing_and_malformed_install_raise_typed_errors_without_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            with self.assertRaises(frames.FrameInstallError):
                frames.scan_install(missing)
            game_path = Path(temporary) / "param" / "GameParam"
            anim_path = Path(temporary) / "chr"
            game_path.mkdir(parents=True)
            anim_path.mkdir(parents=True)
            archive = game_path / "GameParam.parambnd.dcx"
            archive.write_bytes(b"DCX\x00" + b"bad")
            (anim_path / "c0000.anibnd.dcx").write_bytes(b"placeholder")
            before = archive.read_bytes()
            mtime = archive.stat().st_mtime_ns
            with self.assertRaises(frames.FrameFormatError):
                frames.scan_install(temporary)
            self.assertEqual(archive.read_bytes(), before)
            self.assertEqual(archive.stat().st_mtime_ns, mtime)

    def test_json_schema_is_stable_for_an_explicit_synthetic_scan(self) -> None:
        scan = frames.ScanResult(
            "dsr-frame-scan.v1",
            30,
            {"weapon_roots": 0, "usable_goods": 0},
            (),
            (),
            {"game_param": "param/GameParam/GameParam.parambnd.dcx"},
        )
        payload = frames.to_jsonable(
            frames.select_frame_records(
                scan,
                kind="all",
                query=None,
                spoilers=False,
                limit=50,
            ),
        )
        self.assertEqual(payload.get("schema_version"), "dsr-frame-scan.v1")
        self.assertNotIn("source_path", repr(payload))
        self.assertNotIn("raw", repr(payload).casefold())


if __name__ == "__main__":
    unittest.main()
