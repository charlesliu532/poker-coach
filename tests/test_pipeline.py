"""资料入库、检索、教练层的测试。运行: python -m unittest discover -s tests -v"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokercoach.coach import Coach
from pokercoach.index import BM25, expand_query, tokenize
from pokercoach.ingest import chunk_text, extract_cards, ingest, parse_subtitle
from pokercoach.store import Store

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


class TestChunking(unittest.TestCase):
    def test_long_text_splits(self):
        text = "。".join(f"这是第{i}句话，讲的是翻牌后的下注策略" for i in range(60)) + "。"
        chunks = chunk_text(text, "cbet", size=300)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c["heading"] == "cbet" for c in chunks))
        self.assertTrue(all(len(c["text"]) <= 400 for c in chunks))

    def test_short_text_single_chunk(self):
        chunks = chunk_text("短句。", "x")
        self.assertEqual(len(chunks), 1)


class TestCards(unittest.TestCase):
    def test_qa_extraction(self):
        text = "Q：底池赔率怎么算？\nA：下注除以底池加两倍下注。\n"
        cards = extract_cards(text, "赔率")
        self.assertEqual(len(cards), 1)
        self.assertIn("底池赔率", cards[0]["front"])
        self.assertIn("下注除以", cards[0]["back"])

    def test_principle_extraction(self):
        cards = extract_cards("原则：位置决定宽度，不要用垃圾牌开池。", "翻前")
        self.assertEqual(len(cards), 1)
        self.assertIn("核心原则", cards[0]["front"])


class TestSubtitle(unittest.TestCase):
    def test_parse(self):
        srt = "1\n00:00:01,000 --> 00:00:03,500\n第一句\n\n2\n00:00:03,500 --> 00:00:06,000\n第二句\n"
        segs = parse_subtitle(srt)
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[0]["start"], 1.0)
        self.assertAlmostEqual(segs[1]["end"], 6.0)


class TestIndex(unittest.TestCase):
    def test_chinese_tokenizer(self):
        toks = tokenize("翻牌持续下注")
        self.assertIn("翻牌", toks)
        self.assertIn("牌", toks)
        self.assertGreater(toks.count("翻牌"), 1)  # 双字权重加倍

    def test_synonym_expansion(self):
        self.assertIn("cbet", expand_query("持续下注频率"))

    def test_bm25_ranks_relevant_first(self):
        docs = [
            {"text": "河牌抓诈唬要看阻断牌和 MDF", "heading": "河牌"},
            {"text": "翻前 BTN 开池范围很宽", "heading": "翻前"},
            {"text": "翻后持续下注的尺度选择", "heading": "翻后"},
        ]
        hits = BM25(docs).search("河牌怎么抓诈唬")
        self.assertEqual(hits[0][1]["heading"], "河牌")


class TestPipeline(unittest.TestCase):
    def test_ingest_samples_and_query(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            store = Store(tmp / "t.sqlite")
            stats = ingest(SAMPLES, store, transcribe_media=False)
            self.assertGreaterEqual(stats["docs"], 3)
            self.assertGreater(stats["cards"], 5)

            coach = Coach(store)
            self.assertGreater(len(coach.bm25.docs), 5)
            hits = coach.search("MDF 最低防守频率", k=3)
            self.assertTrue(hits)
            self.assertIn("MDF", hits[0]["text"])

            # 转录出来的切片要带时间轴
            hits = coach.search("河牌 防守频率", k=5)
            self.assertTrue(any(h["time"] for h in hits))

            # 离线提问：没有 key 也要有内容
            res = coach.ask("河牌对手下注一个底池怎么防守？")
            self.assertEqual(res["mode"], "offline")
            self.assertTrue(res["sources"])
            self.assertIn("资料", res["prompt"])

            # 问题里的数字要自动算
            math = coach.auto_math("AKs vs 22 底池 100 对手下注 75")
            self.assertIn("equity", math)
            self.assertIn("odds", math)
            self.assertAlmostEqual(math["odds"]["required_equity_pct"], 30.0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
