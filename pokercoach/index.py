"""中文检索：混合分词 + BM25。

没有引入向量库：几千条笔记切片用 BM25 完全够用，而且零依赖、可解释。
中文按"单字 + 双字"切（双字权重更高），英文/数字按词切，另外加一节扑克术语同义词。
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9\-]*")

SYNONYMS = {
    "翻牌": ["flop", "翻后"],
    "转牌": ["turn"],
    "河牌": ["river"],
    "翻前": ["preflop", "翻牌前"],
    "持续下注": ["cbet", "c-bet", "持续下注率"],
    "下注": ["bet", "注"],
    "加注": ["raise"],
    "再加注": ["3bet", "3-bet", "三次加注"],
    "弃牌": ["fold", "盖牌"],
    "跟注": ["call"],
    "过牌": ["check"],
    "底池": ["pot"],
    "胜率": ["equity", "权益"],
    "范围": ["range", "手牌范围"],
    "诈唬": ["bluff"],
    "价值下注": ["valuebet", "价值"],
    "半诈唬": ["semibluff", "semi-bluff"],
    "挤压": ["squeeze"],
    "防御": ["defend", "防守"],
    "按钮": ["btn", "button", "庄位"],
    "小盲": ["sb", "small blind"],
    "大盲": ["bb", "big blind"],
    "枪口": ["utg", "under the gun"],
    "中位": ["mp", "middle position"],
    "关位": ["co", "cutoff"],
    "单挑": ["hu", "heads up"],
    "多路": ["multiway"],
    "摊牌": ["showdown"],
    "赔率": ["odds"],
    "隐含赔率": ["implied odds"],
    "阻断牌": ["blocker", "阻挡牌"],
    "剥削": ["exploit", "剥削性"],
    "平衡": ["balanced", "均衡"],
    "极化": ["polarized", "两极化"],
    "范围优势": ["range advantage"],
    "坚果优势": ["nut advantage"],
    "下注尺度": ["sizing", "尺寸"],
}

# 反向索引：英文/缩写 -> 中文
_REVERSE: dict[str, list[str]] = defaultdict(list)
for zh, others in SYNONYMS.items():
    for o in others:
        _REVERSE[o.lower()].append(zh)


def tokenize(text: str) -> list[str]:
    text = text.lower()
    toks: list[str] = []
    for m in _WORD.finditer(text):
        toks.append(m.group())
    for m in _CJK.finditer(text):
        s = m.group()
        for ch in s:
            toks.append(ch)
        for i in range(len(s) - 1):
            bigram = s[i : i + 2]
            toks.append(bigram)
            toks.append(bigram)  # 双字权重加倍：中文检索主要靠它
    return toks


def expand_query(text: str) -> list[str]:
    """查询时把术语换成同义词一起检索，解决"翻牌/cbet"这类说法不一致。"""
    base = tokenize(text)
    extra: list[str] = []
    low = text.lower()
    for zh, others in SYNONYMS.items():
        if zh in text or any(o in low for o in others):
            for cand in [zh, *others]:
                extra.extend(tokenize(cand)[:6])
    for tok in list(set(base)):
        for zh in _REVERSE.get(tok, []):
            extra.extend(tokenize(zh)[:6])
    return base + extra


class BM25:
    def __init__(self, docs: list[dict], k1: float = 1.2, b: float = 0.75):
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths: list[int] = []
        self.df: Counter = Counter()

        for i, d in enumerate(docs):
            toks = tokenize(d.get("text", "") + " " + d.get("heading", ""))
            tf = Counter(toks)
            self.lengths.append(sum(tf.values()) or 1)
            for term, c in tf.items():
                self.postings[term].append((i, c))
                self.df[term] += 1
        self.N = len(docs) or 1
        self.avgdl = sum(self.lengths) / self.N if self.lengths else 1.0

    def search(self, query: str, limit: int = 8, doc_filter=None) -> list[tuple[float, dict]]:
        q = expand_query(query)
        if not q:
            return []
        qtf = Counter(q)
        scores: dict[int, float] = defaultdict(float)
        for term, qn in qtf.items():
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = math.log(1 + (self.N - self.df[term] + 0.5) / (self.df[term] + 0.5))
            for idx, tf in plist:
                dl = self.lengths[idx]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                scores[idx] += qn * idf * tf * (self.k1 + 1) / denom
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        out = []
        for idx, sc in ranked:
            d = self.docs[idx]
            if doc_filter and not doc_filter(d):
                continue
            out.append((round(sc, 4), d))
            if len(out) >= limit:
                break
        return out


def snippet(text: str, query: str, width: int = 90) -> str:
    """截一段包含查询词的上下文。"""
    if not text:
        return ""
    low = text.lower()
    hits = [low.find(t) for t in set(expand_query(query)) if len(t) > 1 and low.find(t) >= 0]
    pos = min(hits) if hits else 0
    start = max(0, pos - width // 2)
    end = min(len(text), start + width * 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].replace("\n", " ") + suffix
