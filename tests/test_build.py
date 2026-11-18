#!/usr/bin/env python3
"""Unit tests for the pure helpers in tools/build_data.py.

Run:  python tests/test_build.py      (no dependencies; doesn't need the Lahman data)
"""
import math
import os
import sys
import unittest
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import build_data as B  # noqa: E402


def fake_player(pid, name, debut, years, fr_games):
    """A minimal player record shaped like the pipeline's."""
    first, last = name.split(" ", 1)
    fr_years = defaultdict(set)
    for fr, (y0, y1) in years.items():
        fr_years[fr].update(range(y0, y1 + 1))
    all_years = set().union(*fr_years.values())
    return {
        "id": pid, "name": name, "base_name": name, "first": first, "last": last,
        "mlb_debut": debut, "y0": min(all_years), "y1": max(all_years),
        "fr_G": Counter(fr_games), "fr_years": fr_years, "G": sum(fr_games.values()),
    }


class Encoding(unittest.TestCase):
    def decode(self, s):
        idx = {c: i for i, c in enumerate(B.B64)}
        return [(idx[s[i]] << 12) | (idx[s[i + 1]] << 6) | idx[s[i + 2]] for i in range(0, len(s), 3)]

    def test_answers_round_trip(self):
        values = [0, 7, 8, 4095, 4096, 186_000 * 1 + 5, 64 ** 3 - 1]
        packed = B.encode_answers(values)
        self.assertEqual(len(packed), 3 * len(values))
        self.assertEqual(self.decode(packed), values)
        self.assertTrue(set(packed) <= set(B.B64))

    def test_answers_reject_out_of_range(self):
        with self.assertRaises(ValueError):
            B.encode_answers([64 ** 3])
        with self.assertRaises(ValueError):
            B.encode_answers([-1])

    def test_spans(self):
        p = fake_player("x", "Johnny Damon", 1995, {"KCR": (1995, 2000), "BOS": (2002, 2005), "NYY": (2006, 2009)},
                        {"KCR": 803, "BOS": 597, "NYY": 582})
        s = B.encode_spans(p)
        self.assertEqual(len(s), 15)
        idx = {c: i for i, c in enumerate(B.B64)}
        out = []
        for i in range(0, len(s), 5):
            fr = B.FR_ORDER[idx[s[i]]]
            y0 = 1800 + ((idx[s[i + 1]] << 6) | idx[s[i + 2]])
            y1 = 1800 + ((idx[s[i + 3]] << 6) | idx[s[i + 4]])
            out.append((fr, y0, y1))
        self.assertEqual(out, [("KCR", 1995, 2000), ("BOS", 2002, 2005), ("NYY", 2006, 2009)])

    def test_spans_skip_defunct_franchises(self):
        p = fake_player("y", "Old Timer", 1884, {"BL2": (1884, 1885), "LAD": (1886, 1887)}, {"BL2": 50, "LAD": 60})
        self.assertEqual(len(B.encode_spans(p)), 5)


class Association(unittest.TestCase):
    def test_assoc_share_bounds_and_order(self):
        self.assertAlmostEqual(B.assoc_share(0), 0.15)
        self.assertAlmostEqual(B.assoc_share(1), 1.0)
        self.assertAlmostEqual(B.assoc_share(5), 1.0)  # capped
        xs = [B.assoc_share(s / 20) for s in range(21)]
        self.assertEqual(xs, sorted(xs))

    def test_brief_stint_costs_more_than_tau(self):
        # A 1% stint should cost a famous player well over one e-fold of pick share.
        penalty = B.ASSOC_GAMMA * math.log(B.assoc_share(0.01))
        self.assertLess(penalty, -2.5)

    def test_season_bonus_caps(self):
        self.assertEqual(B.season_bonus(1), 1.0)
        self.assertAlmostEqual(B.season_bonus(3), 1.2)
        self.assertEqual(B.season_bonus(40), 1.5)

    def test_recent_bonus(self):
        self.assertEqual(B.recent_bonus([1990, 2001]), 1.0)
        self.assertGreater(B.recent_bonus([1990, B.RECENT_YEAR]), 1.0)
        self.assertEqual(B.recent_bonus([]), 1.0)


class Names(unittest.TestCase):
    def test_parse_icons(self):
        self.assertEqual(B.parse_icons("Babe Ruth:1914, Ken Griffey:1989,\nCal Raleigh:2021"),
                         [("Babe Ruth", 1914), ("Ken Griffey", 1989), ("Cal Raleigh", 2021)])

    def test_match_icon_prefers_exact_debut(self):
        P = {
            "jr": fake_player("jr", "Ken Griffey", 1989, {"SEA": (1989, 1999)}, {"SEA": 1500}),
            "sr": fake_player("sr", "Ken Griffey", 1973, {"CIN": (1973, 1981)}, {"CIN": 1200}),
        }
        self.assertEqual([p["id"] for p in B.match_icon(P, "Ken Griffey", 1989)], ["jr"])
        self.assertEqual([p["id"] for p in B.match_icon(P, "Ken Griffey", 1973)], ["sr"])

    def test_match_icon_falls_back_to_career_span(self):
        # Negro Leagues stars have no MLB debut date; match on the years they played.
        P = {"g": fake_player("g", "Josh Gibson", None, {"HG": (1930, 1946)}, {"HG": 500})}
        self.assertEqual([p["id"] for p in B.match_icon(P, "Josh Gibson", 1930)], ["g"])

    def test_match_icon_ignores_accents(self):
        P = {"a": fake_player("a", "Ronald Acuña", 2018, {"ATL": (2018, 2025)}, {"ATL": 800})}
        self.assertEqual(len(B.match_icon(P, "Ronald Acuna", 2018)), 1)

    def test_curated_lists_parse(self):
        for text in (B.ICONS_S, B.ICONS_A, B.TOO_CUTE_NAMES):
            for name, yr in B.parse_icons(text):
                self.assertTrue(1871 <= yr <= 2026, (name, yr))
                self.assertIn(" ", name)
        for name, yr, suffix in B.SUFFIXES:
            self.assertIn(suffix, ("Jr.", "Sr.", "II"))


class Config(unittest.TestCase):
    def test_tiers_increase(self):
        pts = [t[2] for t in B.TIERS]
        self.assertEqual(pts, [10, 15, 30, 60, 85, 100])
        self.assertGreater(B.SHARE_BUNT, B.SHARE_SINGLE)
        self.assertGreater(B.SHARE_SINGLE, B.SHARE_DOUBLE)
        self.assertGreater(B.SHARE_DOUBLE, B.SHARE_TRIPLE)

    def test_franchises_are_the_30_current_clubs(self):
        self.assertEqual(len(B.FRANCHISES), 30)
        self.assertLessEqual(len(B.FRANCHISES), 64)  # one base64 character per franchise in spans

    def test_word_lists_are_capitalized_words(self):
        for key, (_, _, words) in B.WORD_LISTS.items():
            for w in words:
                self.assertTrue(w[:1].isupper(), (key, w))


if __name__ == "__main__":
    unittest.main(verbosity=1)
