"""主题体系：把资料和视频按"现金局学习主线"归类。

用途有三个：
1. 判断一份文档/一条笔记是不是扑克内容（印象笔记里混着别的东西）
2. 按主题批量挑视频去转录
3. 生成学习路径
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 顺序就是建议的学习顺序：先翻前，再单挑翻后，再河牌，最后多人底池和剥削
TOPICS: list[tuple[str, list[str]]] = [
    ("翻前基础", ["翻前", "开池", "rfi", "起手牌", "位置", "utg", "btn", "大盲", "小盲", "preflop", "range"]),
    ("3bet 与 4bet", ["3bet", "3-bet", "4bet", "4-bet", "再加注", "挤压", "squeeze", "cold call"]),
    ("翻牌持续下注", ["cbet", "c-bet", "持续下注", "翻牌", "flop", "范围优势", "牌面纹理", "board texture"]),
    ("转牌与双枪", ["转牌", "turn", "双枪", "double barrel", "第二枪", "check-raise", "过牌加注"]),
    ("河牌与抓诈唬", ["河牌", "river", "抓诈唬", "hero call", "mdf", "阻断牌", "blocker", "超池", "overbet"]),
    ("多人底池", ["多人", "multiway", "三人", "4人", "squeeze", "limped"]),
    ("剥削与调整", ["剥削", "exploit", "hud", "vpip", "pfr", "样本", "调整", "频率"]),
    ("心理与资金", ["tilt", "情绪", "资金管理", "bankroll", "心态", "下风期", "止损"]),
]

# 用来判断"这是不是扑克内容"
_POKER_HINTS = [
    "翻前", "翻牌", "转牌", "河牌", "底池", "胜率", "范围", "诈唬", "下注", "加注", "弃牌",
    "跟注", "过牌", "3bet", "cbet", "gto", "solver", "equity", "pot odds", "position",
    "poker", "德州", "扑克", "大盲", "小盲", "按钮位", "筹码", "摊牌", "阻断牌", "尺度",
]


@dataclass
class TopicScore:
    name: str
    hits: int


def classify(text: str) -> list[TopicScore]:
    """返回命中的主题，按命中数排序。"""
    low = (text or "").lower()
    out = []
    for name, keys in TOPICS:
        hits = sum(low.count(k.lower()) for k in keys)
        if hits:
            out.append(TopicScore(name, hits))
    return sorted(out, key=lambda t: -t.hits)


def best_topic(text: str) -> str:
    scored = classify(text)
    return scored[0].name if scored else ""


def poker_score(text: str) -> int:
    low = (text or "").lower()
    return sum(low.count(k) for k in _POKER_HINTS)


def is_poker(text: str, threshold: int = 3) -> bool:
    return poker_score(text) >= threshold


def topic_names() -> list[str]:
    return [t[0] for t in TOPICS]


def match_media(name: str, extra: str = "") -> str:
    """给视频/文件名找主题：先看名字，再看它所在的笔记标题。"""
    for text in (name, extra, f"{name} {extra}"):
        t = best_topic(text)
        if t:
            return t
    return ""


_KEYWORD_SPLIT = re.compile(r"[\s_\-—（）()\[\]【】]+")


def search_terms(topic: str) -> list[str]:
    for name, keys in TOPICS:
        if name == topic or topic.lower() in name.lower():
            return keys + [name]
    return [topic]
