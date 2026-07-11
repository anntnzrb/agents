from __future__ import annotations

import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
EVALS_PATH = SKILL_DIR / "evals" / "evals.json"


class EvalSuiteSchemaTests(unittest.TestCase):
    def test_eval_suite_has_formal_schema_and_broad_coverage(self) -> None:
        payload = json.loads(EVALS_PATH.read_text(encoding="utf-8"))

        self.assertIsInstance(payload, dict)
        self.assertEqual(set(payload), {"skill_name", "evals"})
        self.assertIsInstance(payload["skill_name"], str)
        self.assertTrue(payload["skill_name"].strip())
        self.assertEqual(payload["skill_name"], "darksouls")

        evals = payload["evals"]
        self.assertIsInstance(evals, list)
        self.assertEqual(len(evals), 160)

        required_keys = {"id", "prompt", "expected_output", "expectations"}
        allowed_keys = required_keys | {"files"}
        ids: list[int] = []
        record_text: dict[int, str] = {}

        for index, record in enumerate(evals, start=1):
            self.assertIsInstance(record, dict, f"eval record {index}")
            self.assertTrue(required_keys <= set(record), f"eval record {index}")
            self.assertTrue(set(record) <= allowed_keys, f"eval record {index}")

            record_id = record["id"]
            self.assertIs(type(record_id), int, f"eval record {index} id")
            ids.append(record_id)

            for field in ("prompt", "expected_output"):
                self.assertIsInstance(record[field], str, f"eval {record_id} {field}")
                self.assertTrue(record[field].strip(), f"eval {record_id} {field}")

            expectations = record["expectations"]
            self.assertIsInstance(expectations, list, f"eval {record_id} expectations")
            self.assertGreaterEqual(
                len(expectations), 3, f"eval {record_id} expectations"
            )
            self.assertLessEqual(len(expectations), 5, f"eval {record_id} expectations")
            for expectation in expectations:
                self.assertIsInstance(expectation, str, f"eval {record_id} expectation")
                self.assertTrue(expectation.strip(), f"eval {record_id} expectation")

            if "files" in record:
                files = record["files"]
                self.assertIsInstance(files, list, f"eval {record_id} files")
                for file_path in files:
                    self.assertIsInstance(file_path, str, f"eval {record_id} file")
                    self.assertTrue(file_path.strip(), f"eval {record_id} file")

            record_text[record_id] = " ".join(
                [record["prompt"], record["expected_output"], *expectations]
            ).casefold()

        self.assertEqual(sorted(ids), list(range(1, 161)))

        # These are semantic marker families, not exact prose snapshots. Requiring
        # several records per family protects the suite from losing a whole domain.
        coverage_markers = {
            "mechanics": (
                "softcap",
                "soul-cost",
                "equip-load",
                "origins",
                "build ",
                "upgrade path",
                "scaling",
                "attunement",
            ),
            "catalog": (
                "catalog",
                "weapons",
                "rings",
                "goods",
                "farm",
                "estus",
                "calc",
            ),
            "spoiler": ("spoiler", "blind", "--spoilers", "future"),
            "guide": ("guide", "corpus", "psnprofiles", "chunk"),
            "save": ("save", "read-only", "inventory", "bonfire", "boss progress"),
            "sources": (
                "sources status",
                "sources refresh",
                "source key",
                "source-cache",
                "live research",
            ),
            "json/error": (
                "json",
                "nonzero",
                "unknown command",
                "parser error",
                "validation error",
                "invalid flag",
                "rejected",
            ),
            "adversarial conflict": (
                "conflict",
                "conflicting",
                "instead of guessing",
                "unknown rather than",
                "disagrees",
                "higher priority",
                "cannot establish",
            ),
        }
        for category, markers in coverage_markers.items():
            matching_ids = [
                record_id
                for record_id, text in record_text.items()
                if any(marker in text for marker in markers)
            ]
            self.assertGreaterEqual(
                len(matching_ids),
                5,
                f"coverage category {category!r} has too few records: {matching_ids}",
            )

        # Keep audited contract boundaries represented by semantic marker families,
        # rather than matching entire sentences whose wording may evolve.
        audited_marker_families: dict[int, tuple[tuple[str, ...], ...]] = {
            56: (("achievements",), ("missable",), ("--spoilers",)),
            86: (("dsr-guide-corpus",), ("dsr_plat_guide",)),
            90: (
                ("calc",),
                ("moonblade",),
                ("--json",),
                ("nonzero", "non-zero"),
                ("json error object", "json error", "error schema", "documented json"),
            ),
            105: (("areas",), ("route",), ("bosses",)),
            108: (("upgrade",), ("normal",), ("unique",), ("dragon",)),
            110: (("health",), ("estus",), ("stamina",), ("equip load",)),
            114: (("shield",), ("armor",), ("equip-load",)),
            116: (("equip-load --endurance",), ("armor",)),
            120: (("upgrade",), ("normal",), ("unique",), ("dragon",)),
            123: (("build pyromancer",), ("softcaps",)),
            125: (("goods",),),
            128: (("build cleric",), ("build pyromancer",), ("softcaps",)),
            129: (("equip-load",), ("armor",)),
            130: (("goods",),),
            131: (
                ("achievements",),
                ("ownership",),
                ("unsupported",),
                ("static", "checklist"),
                ("spoiler-safe", "redact", "redaction", "without --spoilers"),
            ),
            132: (
                ("achievements --missable",),
                ("ownership",),
                ("unsupported",),
                ("count-only",),
                ("spoiler-safe", "redact", "redaction", "without --spoilers"),
            ),
            133: (("achievements",), ("ownership",)),
            135: (("route --defeated",),),
            143: (("sources status",), ("backup",), ("offline",)),
            145: (("softcaps",), ("build",), ("equip-load",)),
            147: (("build",), ("softcaps",), ("equip-load",)),
            148: (("areas",), ("route",), ("farm",)),
            159: (
                ("inventory",),
                ("progress",),
                ("--json",),
                ("unsupported",),
                ("malformed", "path"),
                ("ignores", "path"),
                ("ignore", "path"),
                ("does not read", "path"),
                ("does not inspect", "path"),
                ("does not validate", "path"),
                ("json object", "machine-readable"),
                ("nonzero", "plain"),
                (
                    "no structured json error schema",
                    "no json error schema",
                    "plain cli error",
                ),
            ),
        }
        for record_id, families in audited_marker_families.items():
            text = record_text[record_id]
            for alternatives in families:
                self.assertTrue(
                    any(marker in text for marker in alternatives),
                    f"eval {record_id} missing audited marker family {alternatives!r}",
                )

        # Exact route, armor, weakness, and acquisition claims must be sourced or
        # explicitly unknown; current claims additionally need URL/key and date.
        provenance_families: dict[int, tuple[tuple[str, ...], ...]] = {
            105: (
                ("source-cache", "route"),
                ("live research", "route"),
                ("source-backed", "route"),
                ("unknown", "route"),
            ),
            108: (
                ("source-cache", "location"),
                ("live research", "location"),
                ("source-backed", "location"),
                ("unknown", "location"),
            ),
            110: (
                ("source-cache", "route"),
                ("live research", "route"),
                ("source-backed", "route"),
                ("unknown", "route"),
            ),
            114: (
                ("shield", "source"),
                ("shield", "unknown"),
                ("armor", "source"),
                ("armor", "unknown"),
            ),
            116: (
                ("source-cache", "armor"),
                ("live research", "armor"),
                ("source-backed", "armor"),
                ("unknown", "armor"),
            ),
            120: (
                ("source-cache", "material"),
                ("live research", "material"),
                ("source-backed", "material"),
                ("unknown", "material"),
            ),
            123: (
                ("source-cache", "location"),
                ("live research", "location"),
                ("source-backed", "location"),
                ("unknown", "location"),
            ),
            125: (
                ("source-cache", "acquisition"),
                ("live research", "acquisition"),
                ("source-backed", "acquisition"),
                ("unknown", "acquisition"),
            ),
            128: (
                ("source-cache", "acquisition"),
                ("live research", "acquisition"),
                ("source-backed", "acquisition"),
                ("unknown", "acquisition"),
            ),
            129: (
                ("source-cache", "armor"),
                ("live research", "armor"),
                ("source-backed", "armor"),
                ("unknown", "armor"),
            ),
            130: (
                ("source-cache", "location"),
                ("live research", "location"),
                ("source-backed", "location"),
                ("unknown", "location"),
            ),
            133: (
                ("source url", "checked date"),
                ("source key", "checked date"),
                ("unknown", "route"),
                ("unverifiable", "route"),
            ),
            135: (
                ("source url", "checked date"),
                ("source key", "checked date"),
                ("unknown", "route"),
                ("unverifiable", "route"),
            ),
            143: (
                ("source url", "checked date"),
                ("source key", "checked date"),
                ("unknown", "compatibility"),
                ("unverifiable", "compatibility"),
                ("unknown", "loader"),
                ("unverifiable", "loader"),
            ),
            145: (
                ("source url", "checked date"),
                ("source key", "checked date"),
                ("unknown", "location"),
                ("unverifiable", "location"),
                ("unknown", "route"),
                ("unverifiable", "route"),
            ),
            147: (
                ("source url", "checked date"),
                ("source key", "checked date"),
                ("unknown", "activity"),
                ("unverifiable", "activity"),
                ("unknown", "matchmaking"),
                ("unverifiable", "matchmaking"),
            ),
            148: (
                ("source url", "checked date"),
                ("source key", "checked date"),
                ("unknown", "location"),
                ("unverifiable", "location"),
                ("unknown", "route"),
                ("unverifiable", "route"),
            ),
        }
        for record_id, families in provenance_families.items():
            text = record_text[record_id]
            self.assertTrue(
                any(
                    all(marker in text for marker in alternatives)
                    for alternatives in families
                ),
                f"eval {record_id} missing source/unknown provenance {families!r}",
            )

        self.assertNotIn("equip-load --load", record_text[116])

        # Each ten-record persona block must retain role-bearing records. These
        # marker families detect the six clusters without prose snapshots.
        persona_clusters: dict[str, tuple[range, tuple[str, ...]]] = {
            "newcomers": (
                range(101, 111),
                ("new player", "newcomer", "first-time", "first time", "beginner"),
            ),
            "melee": (
                range(111, 121),
                ("melee", "shield", "no-shield", "roll", "weapon"),
            ),
            "casters": (
                range(121, 131),
                ("sorcery", "caster", "miracle", "pyromancy", "cleric"),
            ),
            "completionists": (
                range(131, 141),
                ("platinum", "completionist", "achievement", "missable", "checklist"),
            ),
            "online/technical": (
                range(141, 151),
                (
                    "co-op",
                    "pvp",
                    "mod",
                    "online",
                    "offline-only",
                    "controller",
                    "accessibility",
                    "no-hit",
                    "challenge run",
                    "technical",
                ),
            ),
            "returning": (
                range(151, 161),
                ("returning", "resume", "backup", "migrated", "old save", "years away"),
            ),
        }
        for cluster, (cluster_ids, role_markers) in persona_clusters.items():
            matching_ids = [
                record_id
                for record_id in cluster_ids
                if any(marker in record_text[record_id] for marker in role_markers)
            ]
            self.assertGreaterEqual(
                len(matching_ids),
                5,
                f"persona cluster {cluster!r} has too few role records: {matching_ids}",
            )


if __name__ == "__main__":
    unittest.main()
