"""内置事实题库：不依赖笔记、答案确定、干扰项由答案本身推导。

这些是扑克里必须条件反射的数字（MDF、赔率、尺度），
来源是可查证的标准定义，比从笔记里硬抽的题目可靠得多。

MDF / alpha 的数值对照见
https://holdempro.app/glossary/minimum-defense-frequency
赔率与权益的换算见
https://pages.gtowizard.com/zh/glossary/pot-odds/
"""

from __future__ import annotations

import random

# level / q / a（数值）/ unit / why
FACTS: list[dict] = [
    {"level": 3, "q": "对手下注 1/2 池，你的最低防守频率（MDF）是多少？", "a": 67, "unit": "%",
     "why": "MDF = 底池 ÷ (底池 + 下注) = 1 ÷ (1 + 0.5)"},
    {"level": 3, "q": "对手下注 1/3 池，你的最低防守频率（MDF）是多少？", "a": 75, "unit": "%",
     "why": "MDF = 1 ÷ (1 + 1/3)"},
    {"level": 3, "q": "对手下注 2/3 池，你的最低防守频率（MDF）是多少？", "a": 60, "unit": "%",
     "why": "MDF = 1 ÷ (1 + 2/3)"},
    {"level": 5, "q": "对手下注一个底池，你的最低防守频率（MDF）是多少？", "a": 50, "unit": "%",
     "why": "MDF = 1 ÷ (1 + 1)"},
    {"level": 5, "q": "对手下注 2 倍池，你的最低防守频率（MDF）是多少？", "a": 33, "unit": "%",
     "why": "MDF = 1 ÷ (1 + 2)"},
    {"level": 3, "q": "对手下注 1/2 池，你至少需要多少胜率才值得跟注？", "a": 25, "unit": "%",
     "why": "跟注 B 去赢底池加对手下注：B ÷ (P + 2B)"},
    {"level": 5, "q": "对手下注一个底池，你至少需要多少胜率才值得跟注？", "a": 33, "unit": "%",
     "why": "1 ÷ (1 + 1 + 1)"},
    {"level": 3, "q": "对手下注 1/3 池，你至少需要多少胜率才值得跟注？", "a": 20, "unit": "%",
     "why": "(1/3) ÷ (1 + 2/3)"},
    {"level": 5, "q": "对手下注 2/3 池，你至少需要多少胜率才值得跟注？", "a": 29, "unit": "%",
     "why": "(2/3) ÷ (1 + 4/3)"},
    {"level": 5, "q": "你用 1/2 池的纯诈唬下注，对手至少要弃牌多少你才不亏？", "a": 33, "unit": "%",
     "why": "alpha = 下注 ÷ (底池 + 下注)"},
    {"level": 5, "q": "你用满池的纯诈唬下注，对手至少要弃牌多少你才不亏？", "a": 50, "unit": "%",
     "why": "alpha = 1 ÷ (1 + 1)"},
    {"level": 2, "q": "有位置（IP）3bet 的常见尺度，是开池的几倍？", "a": 3, "unit": "倍",
     "why": "IP 常用 3 倍，OOP 因为翻后没位置要用 4 倍"},
    {"level": 2, "q": "没位置（OOP）3bet 的常见尺度，是开池的几倍？", "a": 4, "unit": "倍",
     "why": "OOP 要给对手更差的赔率，同时减少被跟注后打翻后的劣势"},
    {"level": 3, "q": "翻牌圈有 9 个出路（同花听牌），到转牌成牌的概率约是多少？", "a": 18, "unit": "%",
     "why": "二四法则：9 × 2 ≈ 18%"},
    {"level": 4, "q": "翻牌圈有 9 个出路（同花听牌），到河牌成牌的概率约是多少？", "a": 36, "unit": "%",
     "why": "二四法则：9 × 4 ≈ 36%"},
    {"level": 1, "q": "小对子在翻牌击中暗三条的概率约是多少？", "a": 12, "unit": "%",
     "why": "约 1/8，所以需要大约 8 倍以上的隐含赔率才值得用小对子跟注"},
    {"level": 1, "q": "翻前用一手牌跟注，想在翻牌中两对或更好，概率大致是？", "a": 5, "unit": "%",
     "why": "约 5%，不要高估弱牌的翻牌命中率"},
    {"level": 7, "q": "对手的 VPIP 是 45%、PFR 只有 5%，最直接的剥削方向是什么？", "a": 0, "unit": "",
     "why": "跟注太多、加注太少：减少诈唬，放大价值下注尺度"},
]

# 这些题不走数值选项，改用文字选项
TEXT_OPTIONS = {
    "对手的 VPIP 是 45%、PFR 只有 5%，最直接的剥削方向是什么？": [
        "减少诈唬，放大价值下注尺度",
        "增加诈唬频率，因为他弃牌多",
        "保持平衡，不做调整",
        "只用坚果牌跟注，其他都弃",
    ]
}


def _fmt(value: float, unit: str) -> str:
    if unit == "倍":
        return f"{value:g} 倍"
    if unit == "%":
        return f"{value:g}%"
    if unit == "bb":
        return f"{value:g}bb"
    return f"{value:g}"


_POOLS = {
    "%": [10, 15, 20, 25, 30, 33, 35, 40, 45, 50, 55, 60, 65, 67, 70, 75, 80, 85, 90, 100],
    "倍": [1.5, 2, 2.5, 3, 3.5, 4, 5],
    "bb": [5, 10, 15, 20, 25, 30, 35, 40, 50, 60, 75, 100],
}


def numeric_options(answer: float, unit: str, rng: random.Random, k: int = 3) -> list[str]:
    """由正确答案推导干扰项：同单位、数量级接近、取「扑克里常见的数」。"""
    pool = [v for v in _POOLS.get(unit, []) if v != answer]
    if len(pool) < k:
        pool = [answer * f for f in (0.5, 0.8, 1.2, 1.5)]
    pool.sort(key=lambda v: (abs(v - answer), v))
    chosen = pool[:k]
    rng.shuffle(chosen)
    return [_fmt(v, unit) for v in chosen]


def fact_question(index: int) -> dict | None:
    if not 0 <= index < len(FACTS):
        return None
    f = FACTS[index]
    rng = random.Random(f"fact{index}")

    if f["q"] in TEXT_OPTIONS:
        options = list(TEXT_OPTIONS[f["q"]])
        correct = options[0]
        rng.shuffle(options)
        answer_idx = options.index(correct)
    else:
        correct = _fmt(f["a"], f["unit"])
        options = [correct] + numeric_options(f["a"], f["unit"], rng)
        rng.shuffle(options)
        answer_idx = options.index(correct)

    return {
        "id": -1000 - index,
        "level": f["level"],
        "topic": "标准事实",
        "kind": "fact",
        "q": f["q"],
        "options": options,
        "answer": answer_idx,
        "explain": f["why"],
    }


def facts_for_level(level: int, limit: int = 3, exclude: set | None = None) -> list[dict]:
    exclude = exclude or set()
    out = []
    for i, f in enumerate(FACTS):
        if f["level"] != level:
            continue
        if -1000 - i in exclude:
            continue
        q = fact_question(i)
        if q:
            out.append({k: v for k, v in q.items() if k != "answer"})
        if len(out) >= limit:
            break
    return out
