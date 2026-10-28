"""从资料生成学习路径：把已入库的章节按主题排成 N 周计划。

不需要模型，完全确定性的启发式：
1. 每篇文档按标题+小标题归类到主题
2. 主题按「翻前 → 3bet → 翻牌 → 转牌 → 河牌 → 多人 → 剥削 → 心理」排序
3. 每个学习日 = 1~2 个章节 + 当天卡片目标
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from . import topics

_NUM = re.compile(r"(\d+)")
# AI 总结笔记通常有固定模板，这些小节信息密度低，直接跳过
_SKIP_HEADS = (
    "目录", "faq", "结语", "附录", "课程前言", "子页面", "练习题答案",
    "概览与背景", "核心概念与术语", "策略框架与决策流程", "课程导论",
    "前言", "视频简介", "课程简介", "写在前面",
)


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in _NUM.split(s or "")]


def _doc_sections(chunks) -> dict[int, dict]:
    """把 chunk 行按文档聚合，保留章节顺序。"""
    docs: dict[int, dict] = {}
    for c in chunks:
        d = docs.setdefault(
            c["doc_id"],
            {"doc_id": c["doc_id"], "title": c["title"], "kind": c["kind"], "sections": [], "chars": 0},
        )
        d["chars"] += len(c["text"] or "")
        head = (c["heading"] or "").split(" / ")[-1]
        if head and head not in [s["heading"] for s in d["sections"]]:
            d["sections"].append({"heading": head, "text": c["text"]})
    return docs


def build_path(store, weeks: int = 4, days_per_week: int = 5, minutes: int = 25, priority=None) -> dict:
    """priority: 手牌漏洞对应的主题，会被加权、多分天数，排得更靠前。"""
    priority = list(dict.fromkeys(priority or []))
    chunks = store.all_chunks()
    docs = _doc_sections(chunks)
    if not docs:
        return {"weeks": [], "topics": [], "total_days": 0}

    cards = {}
    for row in store.conn.execute("SELECT doc_id, COUNT(*) AS n FROM cards GROUP BY doc_id"):
        cards[row["doc_id"]] = row["n"]

    # 归类：标题权重高于章节名
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for d in docs.values():
        head_text = d["title"] + " " + " ".join(s["heading"] for s in d["sections"][:12])
        scored = topics.classify(head_text)
        name = scored[0].name if scored else "其他"
        d["topic"] = name
        d["score"] = scored[0].hits if scored else 0
        by_topic[name].append(d)

    order = topics.topic_names() + ["其他"]
    for name in by_topic:
        by_topic[name].sort(key=lambda d: _natural_key(d["title"]))

    total_days = weeks * days_per_week
    order = topics.topic_names() + ["其他"]
    active = [t for t in order if by_topic.get(t)]

    # 每个主题挑最有价值的章节：跳过目录/FAQ/结语，跳过和标题重复的第一节
    def useful(d, sec):
        h = (sec["heading"] or "").strip()
        if not h or h.startswith(d["title"]):
            return False
        if any(k in h.lower() for k in _SKIP_HEADS):
            return False
        n = len(sec["text"] or "")
        return 200 <= n <= 3000

    picked: dict[str, list[dict]] = {}
    for name in active:
        secs = []
        for d in by_topic[name]:
            for sec in d["sections"]:
                if useful(d, sec):
                    secs.append(
                        {
                            "doc_id": d["doc_id"],
                            "title": d["title"],
                            "heading": sec["heading"],
                            "text": sec["text"],
                            "topic": name,
                            "cards": min(cards.get(d["doc_id"], 0), 8),
                        }
                    )
        picked[name] = secs

    # 名额按主题体量的平方根分配，避免"翻前"一个主题吃掉整条路径
    weights = {t: math.sqrt(max(len(picked[t]), 1)) for t in active}
    for t in priority:
        if t in weights:
            weights[t] *= 2.5
    total_w = sum(weights.values()) or 1
    budget = total_days
    slots = {t: max(1, round(budget * weights[t] / total_w)) for t in active}

    # 按课程顺序连续排：同一主题连在一起，一周一个主线，不要每天跳主题
    seq: list[dict] = []
    for t in active:
        seq.extend(picked[t][: slots[t]])

    if not seq:
        return {"weeks": [], "topics": [], "total_days": 0}

    per_day = 1 if len(seq) <= total_days * 1.5 else 2

    plan_weeks = []
    idx = 0
    for w in range(weeks):
        days = []
        for d in range(days_per_week):
            if idx >= len(seq):
                break
            block = seq[idx : idx + per_day]
            idx += len(block)
            day_topics = []
            for b in block:
                if b["topic"] not in day_topics:
                    day_topics.append(b["topic"])
            days.append(
                {
                    "day": d + 1,
                    "topic": " / ".join(day_topics),
                    "read": [
                        {"doc_id": b["doc_id"], "title": b["title"], "heading": b["heading"], "preview": (b["text"] or "")[:160]}
                        for b in block
                    ],
                    "cards_target": max(4, sum(b["cards"] for b in block) // 2 or 4),
                    "minutes": minutes,
                }
            )
        if days:
            themes = []
            for day in days:
                for t in day["topic"].split(" / "):
                    if t not in themes:
                        themes.append(t)
            plan_weeks.append({"week": w + 1, "theme": " / ".join(themes), "days": days})

    # 有漏洞的主题排到前面（同一主题内部仍按课程顺序）
    if priority:
        active.sort(key=lambda t: (t not in priority, order.index(t)))

    return {
        "weeks": plan_weeks,
        "priority": priority,
        "topics": [
            {"name": n, "docs": len(by_topic.get(n, [])), "sections": len(picked.get(n, []))}
            for n in active
        ],
        "total_days": sum(len(w["days"]) for w in plan_weeks),
        "pool": sum(len(v) for v in picked.values()),
    }


def render_path(plan: dict) -> str:
    if not plan["weeks"]:
        return "资料库是空的，先导入并 ingest。"
    lines = [
        f"学习路径：{len(plan['weeks'])} 周 / {plan['total_days']} 天，共 {plan['pool']} 个章节可选",
        "",
        "主题覆盖：" + " · ".join(f"{t['name']}({t['sections']})" for t in plan["topics"]),
        "",
    ]
    for w in plan["weeks"]:
        lines.append(f"第 {w['week']} 周 · {w['theme']}")
        for d in w["days"]:
            read = "；".join(f"《{r['title']}》{r['heading']}" for r in d["read"])
            lines.append(f"  第 {d['day']} 天 [{d['topic']}] 读：{read}  + 卡片 {d['cards_target']} 张")
        lines.append("")
    return "\n".join(lines)
