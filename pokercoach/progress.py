"""学习进度：按主题看掌握度、找出反复忘的卡。

掌握度用间隔长度判断，不依赖"感觉"：
    new       没复习过
    learning  复习过，但间隔还 < 7 天
    mastered  间隔 >= 7 天（SM-2 已经把它推远了）
"""

from __future__ import annotations

from collections import defaultdict

from . import topics


def doc_topics(store) -> dict[int, str]:
    out = {}
    for row in store.conn.execute("SELECT id, title FROM docs"):
        out[row["id"]] = topics.best_topic(row["title"]) or "其他"
    return out


def overview(store) -> dict:
    doc_topic = doc_topics(store)
    # 低质量卡（quality < 6）是被隐藏的，不该计入掌握度分母
    rows = store.conn.execute(
        """SELECT c.id, c.doc_id, c.front, c.back, c.tags, c.quality,
                  r.reps, r.lapses, r.interval, r.ease
           FROM cards c LEFT JOIN reviews r ON r.card_id = c.id
           WHERE c.quality IS NULL OR c.quality >= 6"""
    ).fetchall()

    per_topic: dict[str, dict] = defaultdict(lambda: {"cards": 0, "new": 0, "learning": 0, "mastered": 0, "lapses": 0, "reps": 0})
    total = {"cards": 0, "new": 0, "learning": 0, "mastered": 0, "lapses": 0, "reps": 0}
    for r in rows:
        t = doc_topic.get(r["doc_id"], "其他")
        reps = r["reps"] or 0
        interval = r["interval"] or 0
        bucket = "new" if reps == 0 else ("mastered" if interval >= 7 else "learning")
        for agg in (per_topic[t], total):
            agg["cards"] += 1
            agg[bucket] += 1
            agg["lapses"] += r["lapses"] or 0
            agg["reps"] += reps

    order = topics.topic_names() + ["其他"]
    items = []
    for name in order:
        if name not in per_topic:
            continue
        agg = dict(per_topic[name])
        seen = agg["cards"] - agg["new"]
        agg["name"] = name
        agg["mastered_pct"] = round(agg["mastered"] / agg["cards"] * 100, 1) if agg["cards"] else 0
        agg["accuracy_pct"] = round((agg["reps"] - agg["lapses"]) / agg["reps"] * 100, 1) if agg["reps"] else None
        agg["accuracy_n"] = agg["reps"]          # 样本量：10 次的 90% 没有说服力
        agg["started"] = seen
        items.append(agg)

    total["mastered_pct"] = round(total["mastered"] / total["cards"] * 100, 1) if total["cards"] else 0
    total["accuracy_pct"] = round((total["reps"] - total["lapses"]) / total["reps"] * 100, 1) if total["reps"] else None
    total["accuracy_n"] = total["reps"]
    return {"total": total, "topics": items}


def mistakes(store, limit: int = 20) -> list[dict]:
    """反复答错的卡：lapses 越多越靠前，带出处方便回看原文。"""
    rows = store.conn.execute(
        """SELECT c.id, c.front, c.back, c.tags, c.doc_id,
                  r.lapses, r.reps, r.interval, r.ease
           FROM cards c JOIN reviews r ON r.card_id = c.id
           WHERE r.lapses >= 1
           ORDER BY r.lapses DESC, r.ease ASC, r.reps DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    titles = {r["id"]: r["title"] for r in store.conn.execute("SELECT id, title FROM docs")}
    out = []
    for r in rows:
        out.append(
            {
                "card_id": r["id"],
                "front": r["front"],
                "back": r["back"],
                "tags": r["tags"],
                "doc_id": r["doc_id"],
                "doc_title": titles.get(r["doc_id"], ""),
                "lapses": r["lapses"],
                "reps": r["reps"],
                "interval": round(r["interval"] or 0, 1),
            }
        )
    return out
