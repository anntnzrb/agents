"""Unit tests for autommit direct runner."""

from __future__ import annotations

import unittest

from autommit.runner import build_parser, parse_model_string


class RunnerUnitTests(unittest.TestCase):
    """Test model string parsing and CLI flag handling."""

    def test_parse_model_string(self) -> None:
        p1 = parse_model_string("big-pickle")
        self.assertIsNone(p1.provider)
        self.assertEqual(p1.model_id, "big-pickle")
        self.assertIsNone(p1.effort)

        p2 = parse_model_string("opencode/muse-spark-1.3-contributor:high")
        self.assertEqual(p2.provider, "opencode")
        self.assertEqual(p2.model_id, "muse-spark-1.3-contributor")
        self.assertEqual(p2.effort, "high")

        p3 = parse_model_string("ozen/mimo-v2.5:max")
        self.assertEqual(p3.provider, "ozen")
        self.assertEqual(p3.model_id, "mimo-v2.5")
        self.assertEqual(p3.effort, "max")

        p4 = parse_model_string("deepseek-v4:xhigh")
        self.assertIsNone(p4.provider)
        self.assertEqual(p4.model_id, "deepseek-v4")
        self.assertEqual(p4.effort, "xhigh")

    def test_build_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--ogo", "--model", "muse-spark-1.3-contributor"])
        self.assertTrue(args.ogo)
        self.assertFalse(args.ozen)
        self.assertEqual(args.model, "muse-spark-1.3-contributor")

        args_zen = parser.parse_args(["--ozen"])
        self.assertTrue(args_zen.ozen)


if __name__ == "__main__":
    _ = unittest.main()
