"""翻前范围带翻后 + surplus 选诈唬 的单元测试。

跑法：python -m unittest discover -s tests
"""
from __future__ import annotations

import unittest
from pathlib import Path

from pokercoach import bluff, preflop_line
from pokercoach.ranges import parse_range
from pokercoach.tree import _class_combo_count, parse_board


class TestPreflopLine(unittest.TestCase):
    def test_parse_and_format(self):
        steps = preflop_line.parse("BTN:open>BB:call")
        self.assertEqual([s["act"] for s in steps], ["open", "call"])
        self.assertEqual(preflop_line.format(steps), "BTN:open>BB:call")
        # 中文动作也认
        self.assertEqual(preflop_line.parse("BTN:开池>BB:跟注")[1]["act"], "call")

    def test_srp_open_vs_flat(self):
        r = preflop_line.resolve("BTN", "BB", "BTN:open>BB:call")
        self.assertTrue(r["ok"])
        self.assertEqual(r["pot"], "SRP")
        self.assertEqual(r["hero_action"], "open")
        self.assertEqual(r["villain_action"], "call")
        self.assertGreater(r["hero_spec_pct"], 35)   # BTN 开池 ~42%
        self.assertGreater(r["villain_spec_pct"], 25)  # BB 平跟 ~34%

    def test_3bet_pot_uses_call3bet_range(self):
        r = preflop_line.resolve("BTN", "SB", "BTN:open>SB:3bet>BTN:call")
        self.assertTrue(r["ok"])
        self.assertEqual(r["pot"], "3BP")
        self.assertEqual(r["hero_action"], "call")
        self.assertLess(r["hero_spec_pct"], 20)      # 跟注 3bet 很紧
        self.assertGreater(r["villain_spec_pct"], 10)

    def test_hero_who_3bet_gets_3bet_range(self):
        r = preflop_line.resolve("SB", "BTN", "BTN:open>SB:3bet>BTN:call")
        self.assertTrue(r["ok"])
        self.assertEqual(r["hero_action"], "3bet")
        self.assertLess(r["hero_spec_pct"], 20)

    def test_fold_does_not_make_it_multiway(self):
        # CO 弃牌了，翻后就是单挑 3bet 池，不能标成「3BP多人」
        r = preflop_line.resolve(
            "UTG", "HJ", "UTG:open>HJ:3bet>CO:fold>UTG:call")
        self.assertTrue(r["ok"])
        self.assertEqual(r["pot"], "3BP")
        self.assertEqual(r["players"], 2)

    def test_folded_hero_has_no_postflop_range(self):
        r = preflop_line.resolve("BTN", "SB", "BTN:open>SB:3bet>BTN:fold")
        self.assertFalse(r["ok"])
        self.assertIn("弃牌", r["note"])

    def test_no_line_falls_back(self):
        r = preflop_line.resolve("BTN", "BB", "")
        self.assertFalse(r["ok"])
        self.assertIsNone(r["hero_set"])

    def test_4bet_pot(self):
        r = preflop_line.resolve(
            "HJ", "UTG", "UTG:open>HJ:3bet>UTG:4bet>HJ:call")
        self.assertTrue(r["ok"])
        self.assertEqual(r["pot"], "4BP")
        self.assertLess(r["hero_spec_pct"], 8)       # 跟注 4bet 极紧


class TestBluffSurplus(unittest.TestCase):
    BOARD, _ = parse_board("A72r")
    VILLAIN = parse_range("AA, KK, AKs, AQo, 22")

    def test_blocking_strong_ranks_higher(self):
        # K83 面：A5 挡掉对手的 AA，76 什么都挡不到 → A5 的 surplus 更高
        board, _ = parse_board("K83r")
        villain = parse_range("AA, KK")
        hero = parse_range("A5s, 76s")
        # 这里把对手整个范围都当「会跟的强牌」，只看阻断牌的净效果
        ranked = bluff.rank([(a, b) for a, b, *_ in hero], board,
                            [(a, b) for a, b, *_ in villain], 33,
                            strong_frac=1.0)
        by = {}
        for x in ranked:
            by.setdefault(x["combo"], x)
        self.assertGreater(by["A5s"]["surplus"], by["76s"]["surplus"])
        self.assertGreater(by["A5s"]["block_strong"], by["76s"]["block_strong"])

    def test_choose_fills_quota(self):
        hero = parse_range("KQo, 76s")
        ranked = bluff.rank([(a, b) for a, b, *_ in hero], self.BOARD,
                            [(a, b) for a, b, *_ in self.VILLAIN], 33)
        picked = bluff.choose(ranked, 2.5)
        total = sum(x["take"] for x in picked if x["selected"])
        self.assertAlmostEqual(total, 2.5, places=6)

    def test_plan_cuts_air_to_quota(self):
        board = self.BOARD
        cells = [
            {"combo": "AA", "cat": "暗三条", "bucket": 60},
            {"combo": "KK", "cat": "小口袋对", "bucket": 100},
            {"combo": "QQ", "cat": "小口袋对", "bucket": 100},
            {"combo": "KQo", "cat": "纯空气", "bucket": 80},
            {"combo": "76s", "cat": "后门空气", "bucket": 80},
        ]
        hero = parse_range("AA, KK, QQ, KQo, 76s")
        villain = self.VILLAIN
        p = bluff.plan(cells, [(a, b) for a, b, *_ in hero], board,
                       [(a, b) for a, b, *_ in villain], 33)
        self.assertTrue(p["ok"])
        self.assertLess(p["target"], p["air_available"])
        # 配额内只留一部分空气
        self.assertLess(p["selected"], p["air_available"])
        self.assertGreater(p["target_share"], 0.15)
        self.assertLess(p["target_share"], 0.25)

    def test_no_air_returns_none(self):
        cells = [{"combo": "AA", "cat": "暗三条", "bucket": 80}]
        hero = parse_range("AA")
        p = bluff.plan(cells, [(a, b) for a, b, *_ in hero], self.BOARD,
                       [(a, b) for a, b, *_ in self.VILLAIN], 33)
        self.assertIsNone(p)


class TestComboCount(unittest.TestCase):
    def test_pair_blocked_by_board(self):
        board, _ = parse_board("A72r")
        self.assertEqual(_class_combo_count("AA", board), 3)   # 一张 A 在牌面
        self.assertEqual(_class_combo_count("KK", board), 6)
        self.assertEqual(_class_combo_count("AKs", board), 3)  # A♠ 在牌面
        self.assertEqual(_class_combo_count("AKo", board), 9)


class TestTreeIntegration(unittest.TestCase):
    """有数据文件时跑一遍真实节点：范围过滤 + 频率 + 诈唬计划都要在。"""

    def test_node_with_line(self):
        from pokercoach.paths import data_path
        tdir = data_path("tree")
        if not (Path(tdir) / "rules.csv").exists():
            self.skipTest("没有策略树数据")
        from pokercoach import tree
        r = tree.grid(tdir, "SRP", "IP-PFR", "A72r", "翻牌", "对手过牌",
                      hero_pos="BTN", opp_pos="BB", stack="100bb",
                      simplify=True, preflop_line="BTN:open>BB:call")
        self.assertTrue(r["ok"])
        self.assertTrue(r["preflop"]["ok"])
        self.assertAlmostEqual(
            sum(a["pct"] for a in r["freq"]["actions"]), 100.0, delta=0.5)
        self.assertGreater(r["freq"]["total_combos"], 300)
        self.assertIsNotNone(r["bluff"])
        self.assertTrue(r["bluff"]["ok"])
        self.assertLess(r["bluff"]["selected"], r["bluff"]["air_available"])


if __name__ == "__main__":
    unittest.main()
