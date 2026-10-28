"""全牌谱评估：把指标偏差、策略树一致性、翻前纪律合成一份报告。"""
from __future__ import annotations

import statistics
from pathlib import Path


def _score_metrics(metrics: list[dict]) -> tuple[float, list[dict]]:
    """每个指标按偏离程度扣分；样本不足的权重减半。返回 (0-100, 明细)。"""
    if not metrics:
        return 0.0, []
    total_w = got = 0.0
    detail = []
    for m in metrics:
        # 用「离正常区间的距离 / 档位半宽」算惩罚：
        # 刚出正常区间 → 轻罚；到「很高/很低」临界 → 中罚；再往外 → 重罚
        bandw = m.get("whi", m["hi"] + 1) - m.get("wlo", m["lo"] - 1)
        span = max(bandw / 2, 1)
        over = abs(m["gap"]) if m["gap"] else 0.0
        pen = min(2.0, over / span)
        w = 1.0 if m["enough"] else 0.5
        s = max(0.0, 100 * (1 - pen))
        total_w += w
        got += s * w
        detail.append({"key": m["key"], "label": m["label"], "score": round(s, 1),
                       "pen": round(pen, 2), "weight": w, "verdict": m["verdict"]})

    return (got / total_w if total_w else 0.0), detail


def evaluate(store, tree_dir: Path, leaks: dict, mismatch: dict) -> dict:
    metrics = leaks.get("metrics") or []
    hands = leaks.get("hands") or 0
    wr = leaks.get("winrate_bb100")

    m_score, m_detail = _score_metrics(metrics)

    # 策略树一致性得分
    nodes = mismatch.get("nodes") or []
    tot_n = sum(n["n"] for n in nodes)
    tot_bad = sum(n["bad"] for n in nodes)
    tree_rate = (tot_bad / tot_n * 100) if tot_n else None
    tree_score = max(0.0, 100 - (tree_rate or 0) * 1.6) if tree_rate is not None else None

    # 翻前纪律：开池宽度是否偏离基准
    rfi = leaks.get("rfi") or {}
    rfi_bad = []
    for pos, d in rfi.items():
        pct = d.get("pct")
        if pct is None:
            continue
        lo, hi = {"UTG": (14, 22), "HJ": (16, 25), "CO": (22, 33),
                  "BTN": (36, 52), "SB": (28, 55)}.get(pos, (0, 100))
        if not (lo <= pct <= hi):
            rfi_bad.append({"pos": pos, "pct": pct, "lo": lo, "hi": hi,
                            "dir": "偏宽" if pct > hi else "偏窄"})
    pre_score = max(0.0, 100 - len(rfi_bad) * 12) if rfi else None

    # 综合：翻后指标 60% + 策略树一致性 25% + 翻前纪律 15%
    parts = [(m_score, 0.60)]
    if tree_score is not None:
        parts.append((tree_score, 0.25))
    if pre_score is not None:
        parts.append((pre_score, 0.15))
    tw = sum(w for _, w in parts)
    overall = sum(s * w for s, w in parts) / tw if tw else 0.0

    bad_metrics = [m for m in metrics if m["verdict"] != "正常" and m["enough"]]
    bad_metrics.sort(key=lambda m: -abs(m["gap"]))

    # 按「影响 × 样本」排序最该修的问题
    todo = []
    for m in bad_metrics[:6]:
        todo.append({"kind": "指标", "name": m["label"],
                     "detail": f"{m['value']}%（标准 {m['lo']}~{m['hi']}%）{m['verdict']}",
                     "size": abs(m["gap"]), "n": m["samples"]})
    for n in nodes[:6]:
        if n["rate"] >= 20:
            todo.append({"kind": "策略树", "name": f"{n['pot']}·{n['street']}·{n['role']}",
                         "detail": f"错 {n['bad']}/{n['n']}（{n['rate']}%）· 规则 {n['rule']}",
                         "size": n["rate"] / 2, "n": n["n"]})
    todo.sort(key=lambda x: -(x["size"] * (1 + min(x["n"], 500) / 500)))

    good = [m["label"] for m in metrics if m["verdict"] == "正常" and m["enough"]]

    # 等级
    if overall >= 80:
        grade, verdict = "A", "总体纪律良好，主要在打磨细节"
    elif overall >= 65:
        grade, verdict = "B", "基础稳，但有 2~3 个明确漏洞在持续漏钱"
    elif overall >= 50:
        grade, verdict = "C", "有明显系统性问题，先修指标再谈剥削"
    else:
        grade, verdict = "D", "多处大幅偏离，建议回到基础重建"

    return {
        "hands": hands, "winrate_bb100": wr,
        "overall": round(overall, 1), "grade": grade, "verdict": verdict,
        "parts": {
            "指标得分": round(m_score, 1),
            "策略树一致性": (round(tree_score, 1) if tree_score is not None else None),
            "翻前纪律": (round(pre_score, 1) if pre_score is not None else None),
            "策略树错误率": (round(tree_rate, 1) if tree_rate is not None else None),
        },
        "metric_detail": sorted(m_detail, key=lambda x: x["score"]),
        "todo": todo[:5],
        "strengths": good[:6],
        "rfi_issues": rfi_bad,
        "sample_ok": hands >= 10000,
        "note": ("样本 ≥1 万手时指标才比较可信；低于这个数，结论只能当方向参考。"
                 if hands < 10000 else ""),
    }


def auto_plan(store, tree_dir, leaks: dict, mismatch: dict, minutes: int = 25) -> dict:
    """根据评估结果重排学习路径：先补最漏的，再看策略树出错最多的节点。"""
    ev = evaluate(store, tree_dir, leaks, mismatch)
    metrics = leaks.get("metrics") or []
    nodes = mismatch.get("nodes") or []

    # 1) 指标漏洞 → 对应主题
    topic_hits = {}
    for m in metrics:
        if m["verdict"] == "正常":
            continue
        weight = abs(m["gap"]) * (1.0 if m["enough"] else 0.5)
        t = m.get("topic") or "其他"
        topic_hits.setdefault(t, {"topic": t, "weight": 0, "reasons": []})
        topic_hits[t]["weight"] += weight
        topic_hits[t]["reasons"].append(
            f"{m['label']} {m['value']}%（正常 {m['lo']}~{m['hi']}%）{m['verdict']}")

    # 2) 策略树出错节点 → 也归到主题
    TOPIC_OF = {"翻牌": "翻牌持续下注", "转牌": "转牌与双枪", "河牌": "河牌与抓诈唬"}
    for n in nodes:
        if n["rate"] < 20:
            continue
        t = TOPIC_OF.get(n["street"], "其他")
        if n["role"].endswith("PFR"):
            t = t if n["pot"] == "SRP" else f"{n['pot']} 池"
        topic_hits.setdefault(t, {"topic": t, "weight": 0, "reasons": []})
        topic_hits[t]["weight"] += n["rate"] * 0.4
        topic_hits[t]["reasons"].append(
            f"策略树：{n['pot']}·{n['street']}·{n['role']} 错 {n['rate']}%（{n['bad']}/{n['n']}）")

    ranked = sorted(topic_hits.values(), key=lambda x: -x["weight"])

    # 3) 取这些主题下的到期卡片
    from . import topics as topic_mod
    from .progress import doc_topics

    dm = doc_topics(store)
    due = store.due_cards(limit=120)
    picked, seen = [], set()
    for t in [x["topic"] for x in ranked]:
        for c in due:
            if c["id"] in seen:
                continue
            if dm.get(c["doc_id"]) == t:
                picked.append(dict(c))
                seen.add(c["id"])
                if len(picked) >= 12:
                    break
        if len(picked) >= 12:
            break
    if len(picked) < 8:                       # 主题卡片不够就补通用到期卡
        for c in due:
            if len(picked) >= 12:
                break
            if c["id"] not in seen:
                picked.append(dict(c))
                seen.add(c["id"])

    card_min = max(5, min(minutes - 10, len(picked)))
    return {
        "minutes": minutes,
        "generated_from": "evaluate",
        "score": ev["overall"], "grade": ev["grade"],
        "focus": [{"topic": t["topic"], "weight": round(t["weight"], 1),
                   "reasons": t["reasons"][:4]} for t in ranked[:4]],
        "cards": picked,
        "split": {"cards": card_min, "reading": max(10, minutes - card_min)},
        "note": ("路径是按你当前的漏洞重排的：先补权重最高的主题。"
                 "修完再看 '按策略树出错最多'，那里是具体动作层面的偏差。"),
    }
