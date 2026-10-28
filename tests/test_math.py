"""数学引擎的单元测试。运行: python -m unittest discover -s tests -v"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from pokercoach import cards, odds, ranges
from pokercoach.equity import category_name, equity, equity_multi, evaluate


class TestCards(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(cards.parse_card("Ah"), cards.parse_card("ah"))
        self.assertEqual(cards.parse_card("10h"), cards.parse_card("Th"))
        self.assertEqual(len(cards.parse_cards("Kh7h2c")), 3)
        self.assertEqual(cards.parse_cards("Ah, Kh"), cards.parse_cards("AhKh"))
        self.assertNotEqual(cards.parse_card("Ah"), cards.parse_card("As"))

    def test_bad(self):
        with self.assertRaises(cards.CardError):
            cards.parse_card("Zz")
        with self.assertRaises(cards.CardError):
            cards.parse_cards("AhK")


class TestRanges(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(len(ranges.parse_range("AA")), 6)
        self.assertEqual(len(ranges.parse_range("AKs")), 4)
        self.assertEqual(len(ranges.parse_range("AKo")), 12)
        self.assertEqual(len(ranges.parse_range("AK")), 16)
        self.assertEqual(len(ranges.parse_range("TT+")), 30)
        self.assertEqual(len(ranges.parse_range("ATs+")), 16)
        self.assertEqual(len(ranges.parse_range("22-55")), 24)
        self.assertEqual(len(ranges.parse_range("T9s-54s")), 24)
        self.assertEqual(len(ranges.parse_range("AKs,AKs")), 4)
        self.assertEqual(ranges.combo_count("AKs:0.5"), 2.0)

    def test_plus_is_fixed_top_card(self):
        names = {"".join(sorted([cards.card_str(a)[0], cards.card_str(b)[0]], key=lambda r: -cards.RANKS.index(r)))
                 for a, b, _ in ranges.parse_range("K9s+")}
        self.assertEqual(names, {"K9", "KT", "KJ", "KQ"})

    def test_specific(self):
        combos = ranges.parse_range("AhKh")
        self.assertEqual(len(combos), 1)
        self.assertEqual(combos[0][0], min(cards.parse_card("Ah"), cards.parse_card("Kh")))
        self.assertEqual(combos[0][1], max(cards.parse_card("Ah"), cards.parse_card("Kh")))

    def test_blocked(self):
        blocked = ranges.remove_blocked(ranges.parse_range("AKs"), [cards.parse_card("Ah")])
        self.assertEqual(len(blocked), 3)


class TestEvaluate(unittest.TestCase):
    def _cat(self, *hand):
        arr = np.array([[cards.parse_card(c) for c in hand]], dtype=np.int16)
        return category_name(evaluate(arr)[0])

    def test_categories(self):
        self.assertEqual(self._cat("Ah", "Kh", "Qh", "Jh", "Th"), "同花顺")
        self.assertEqual(self._cat("Ah", "Ad", "Ac", "As", "Kh"), "四条")
        self.assertEqual(self._cat("Ah", "Ad", "Ac", "Kh", "Ks"), "葫芦")
        self.assertEqual(self._cat("Ah", "Kh", "9h", "5h", "2h"), "同花")
        self.assertEqual(self._cat("9h", "8d", "7c", "6s", "5h"), "顺子")
        self.assertEqual(self._cat("Ah", "2d", "3c", "4s", "5h"), "顺子")  # 轮子
        self.assertEqual(self._cat("Ah", "Ad", "Ac", "Kh", "Qs"), "三条")
        self.assertEqual(self._cat("Ah", "Ad", "Kc", "Kh", "Qs"), "两对")
        self.assertEqual(self._cat("Ah", "Ad", "Kc", "Qh", "9s"), "一对")
        self.assertEqual(self._cat("Ah", "Kd", "Qc", "9h", "7s"), "高牌")

    def test_ordering(self):
        hands = [
            ("Ah", "Kh", "Qh", "Jh", "Th"),  # 皇家同花顺
            ("9h", "8h", "7h", "6h", "5h"),  # 同花顺
            ("Ah", "Ad", "Ac", "As", "Kh"),  # 四条
            ("Ah", "Ad", "Ac", "Kh", "Ks"),  # 葫芦
            ("Ah", "Kh", "9h", "5h", "2h"),  # 同花
            ("9h", "8d", "7c", "6s", "5h"),  # 顺子
        ]
        arr = np.array([[cards.parse_card(c) for c in h] for h in hands], dtype=np.int16)
        scores = evaluate(arr)
        self.assertTrue(np.all(np.diff(scores) < 0), "牌型严格递减")

    def test_kicker_matters(self):
        a = evaluate(np.array([[cards.parse_card(c) for c in ("Ah", "Ad", "Kc", "Qh", "9s")]], np.int16))
        b = evaluate(np.array([[cards.parse_card(c) for c in ("As", "Ac", "Kh", "Qd", "8s")]], np.int16))
        self.assertGreater(a[0], b[0])

    def test_seven_cards(self):
        arr = np.array([[cards.parse_card(c) for c in ("Ah", "Kh", "Qh", "Jh", "Th", "2c", "3d")]], np.int16)
        self.assertEqual(category_name(evaluate(arr)[0]), "同花顺")
        arr = np.array([[cards.parse_card(c) for c in ("Ah", "Ad", "Ac", "As", "Kh", "Kd", "2c")]], np.int16)
        self.assertEqual(category_name(evaluate(arr)[0]), "四条")
        arr = np.array([[cards.parse_card(c) for c in ("Ah", "Ad", "Ac", "Kh", "Ks", "2c", "3d")]], np.int16)
        self.assertEqual(category_name(evaluate(arr)[0]), "葫芦")


class TestEquity(unittest.TestCase):
    def test_aa_vs_kk(self):
        r = equity("AhAd", "KhKd", n_samples=40000)
        self.assertFalse(r.exact)
        self.assertAlmostEqual(r.equity, 0.819, delta=0.01)

    def test_ak_vs_22(self):
        r = equity("AhKh", "2c2d", n_samples=40000)
        self.assertAlmostEqual(r.equity, 0.498, delta=0.02)

    def test_river_exact(self):
        r = equity("AhAc", "KdKc", "Qh7h2c9d3s")
        self.assertTrue(r.exact)
        self.assertEqual(r.equity, 1.0)

    def test_flop_exact_with_range(self):
        r = equity("AhKh", "QQ+,AKs", "Qh7h2c")
        self.assertTrue(r.exact)
        self.assertGreater(r.equity, 0.3)
        self.assertLess(r.equity, 0.5)

    def test_split_pot(self):
        r = equity("AhKd", "AsKc", "2c3d4h5s9c")
        self.assertTrue(r.exact)
        self.assertAlmostEqual(r.equity, 0.5, places=6)

    def test_multiway_sums_to_one(self):
        r = equity_multi(["AA", "KK", "QQ"], n_samples=20000)
        self.assertAlmostEqual(sum(r.multiway), 1.0, places=6)
        self.assertGreater(r.multiway[0], r.multiway[1])
        self.assertGreater(r.multiway[1], r.multiway[2])

    def test_reproducible(self):
        a = equity("AhKh", "QQ+", n_samples=5000, seed=42)
        b = equity("AhKh", "QQ+", n_samples=5000, seed=42)
        self.assertEqual(a.equity, b.equity)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            equity("AhKh", "AsKs", "Ah7c2d")
        with self.assertRaises(ValueError):
            equity("AhKh", "AsKs", "Kh7c")  # 4 张


class TestOdds(unittest.TestCase):
    def test_required_equity(self):
        self.assertAlmostEqual(odds.required_equity_call(100, 50), 0.25)
        self.assertAlmostEqual(odds.required_equity_call(100, 100), 1 / 3)
        self.assertAlmostEqual(odds.mdf(100, 50), 2 / 3)
        self.assertAlmostEqual(odds.alpha(100, 50), 1 / 3)

    def test_ev(self):
        self.assertAlmostEqual(odds.ev_call(1 / 3, 100, 100), 0.0)
        self.assertAlmostEqual(odds.ev_call(0.5, 100, 100), 50.0)
        self.assertAlmostEqual(odds.ev_call(1.0, 100, 100), 200.0)
        self.assertAlmostEqual(odds.ev_bluff(0.5, 100, 50), 25.0)
        self.assertAlmostEqual(odds.ev_bluff(0.0, 100, 50), -50.0)
        self.assertAlmostEqual(odds.spr(1000, 100), 10.0)

    def test_analyze(self):
        a = odds.analyze(100, 50, 0.3)
        self.assertEqual(a["required_equity_pct"], 25.0)
        self.assertIn("+EV", a["verdict"])


if __name__ == "__main__":
    unittest.main()
