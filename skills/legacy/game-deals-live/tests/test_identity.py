"""Identity parsing and conservative matching tests."""

from __future__ import annotations

import unittest

from game_deals.identity import choose_candidate, steam_identity, title_score


class IdentityTests(unittest.TestCase):
    def test_extracts_all_supported_steam_id_types(self) -> None:
        self.assertEqual(
            steam_identity("https://store.steampowered.com/app/220/Half_Life_2/"),
            {"type": "app", "id": "220"},
        )
        self.assertEqual(steam_identity("sub: 123"), {"type": "sub", "id": "123"})
        self.assertEqual(steam_identity("bundle/456"), {"type": "bundle", "id": "456"})

    def test_matching_handles_edition_noise_but_rejects_unrelated(self) -> None:
        self.assertLess(title_score("Control Ultimate Edition", "Control"), 0.88)
        self.assertLess(title_score("Control Game of the Year Edition", "Control"), 0.88)
        match, scored = choose_candidate(
            "Half-Life 2",
            [{"title": "Portal 2"}, {"title": "Half-Life 2"}],
        )
        self.assertEqual(match["title"], "Half-Life 2")
        self.assertEqual(scored[0]["match_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
