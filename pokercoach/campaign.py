"""闯关系统：等级、解锁、经验值、成就。

把"学习扑克"拆成 8 关，每关对应一个主题：
翻前 → 3bet → 翻牌 cbet → 转牌 → 河牌 → 多人底池 → 剥削 → 心理

通关条件：这一关的题目做对一半以上，且正确率 ≥ 75%。
"""

from __future__ import annotations

import json
from datetime import date

from . import quiz, topics

RANKS = [
    (0, "新手"), (300, "青铜"), (800, "白银"), (1500, "黄金"),
    (2500, "铂金"), (4000, "钻石"), (6000, "大师"),
]

XP_CORRECT = 10
XP_WRONG = 3
XP_CLEAR = 100


def rank_of(xp: int) -> dict:
    name, floor, nxt = "新手", 0, None
    for i, (need, label) in enumerate(RANKS):
        if xp >= need:
            name, floor = label, need
            nxt = RANKS[i + 1][0] if i + 1 < len(RANKS) else None
    return {"name": name, "floor": floor, "next": nxt}


def _streak(rows) -> int:
    best = cur = 0
    for r in rows:
        if r["correct"]:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _days_active(rows) -> int:
    days = {r["created"][:10] for r in rows}
    return len(days)


def _consecutive_days(rows) -> int:
    days = sorted({r["created"][:10] for r in rows})
    if not days:
        return 0
    best = cur = 1
    prev = date.fromisoformat(days[0])
    for d in days[1:]:
        cur_d = date.fromisoformat(d)
        if (cur_d - prev).days == 1:
            cur += 1
            best = max(best, cur)
        elif (cur_d - prev).days > 1:
            cur = 1
        prev = cur_d
    return best


def _mastered_cards(store) -> int:
    row = store.conn.execute(
        "SELECT COUNT(*) AS n FROM reviews WHERE interval >= 7"
    ).fetchone()
    return row["n"] or 0


ACHIEVEMENTS = [
    {"id": "first_blood", "name": "第一滴血", "desc": "答对第一道题", "icon": "🩸"},
    {"id": "streak_5", "name": "五连击", "desc": "连续答对 5 题", "icon": "⚡"},
    {"id": "streak_10", "name": "十连击", "desc": "连续答对 10 题", "icon": "🔥"},
    {"id": "correct_50", "name": "五十题", "desc": "累计答对 50 题", "icon": "📘"},
    {"id": "correct_200", "name": "两百题", "desc": "累计答对 200 题", "icon": "📚"},
    {"id": "clear_1", "name": "翻前毕业", "desc": "通关第 1 关", "icon": "🎓"},
    {"id": "clear_2", "name": "3bet 毕业", "desc": "通关第 2 关", "icon": "🎓"},
    {"id": "clear_3", "name": "cbet 毕业", "desc": "通关第 3 关", "icon": "🎓"},
    {"id": "clear_4", "name": "转牌毕业", "desc": "通关第 4 关", "icon": "🎓"},
    {"id": "clear_5", "name": "河牌毕业", "desc": "通关第 5 关", "icon": "🎓"},
    {"id": "clear_6", "name": "多人底池毕业", "desc": "通关第 6 关", "icon": "🎓"},
    {"id": "clear_7", "name": "剥削毕业", "desc": "通关第 7 关", "icon": "🎓"},
    {"id": "clear_8", "name": "心态毕业", "desc": "通关第 8 关", "icon": "🏆"},
    {"id": "mastered_50", "name": "五十张掌握", "desc": "50 张卡进入掌握状态", "icon": "🧠"},
    {"id": "days_3", "name": "连续三天", "desc": "连续 3 天来练习", "icon": "📅"},
]


def _level_cleared(total_cards: int, stat: dict) -> bool:
    if not stat:
        return False
    # 小关卡（只有几张卡）不能被"至少 8 题"卡死
    need = min(max(4, int(total_cards * 0.4)), 10, max(total_cards, 1))
    return stat["cards"] >= need and stat["n"] >= max(5, need) and stat["ok"] / stat["n"] >= 0.75


def status(store) -> dict:
    levels = quiz.level_summary(store)
    stats = store.level_stats()
    rows = store.attempt_rows()
    correct_total = sum(r["correct"] for r in rows)
    answered = len(rows)

    for lv in levels:
        lv["stat"] = stats.get(lv["level"], {})
        lv["cleared"] = _level_cleared(lv["total"], lv["stat"])
        lv["accuracy"] = round(lv["stat"].get("ok", 0) / lv["stat"]["n"] * 100) if lv["stat"] else None
        # 通关门槛：只要求"解出 N 张不同的卡 + 准确率"，不是刷完整个题库
        need = min(max(4, int(lv["total"] * 0.4)), 10, max(lv["total"], 1))
        lv["clear_need"] = need
        lv["clear_have"] = lv["stat"].get("cards", 0)
        lv["clear_pct"] = round(lv["clear_have"] / need * 100, 1) if need else 0

    # 个人学习工具不做硬锁：所有关卡都能进，"推荐"只是排序提示
    for lv in levels:
        lv["unlocked"] = True

    # 经验值：答对/答错都给分，通关额外奖励（只算一次）
    cleared_count = sum(1 for lv in levels if lv["cleared"])
    wrong_total = answered - correct_total
    xp = correct_total * XP_CORRECT + wrong_total * XP_WRONG + cleared_count * XP_CLEAR

    best_streak = _streak(rows)
    days = _consecutive_days(rows)
    mastered = _mastered_cards(store)

    unlocked_ids = set()
    if correct_total >= 1:
        unlocked_ids.add("first_blood")
    if best_streak >= 5:
        unlocked_ids.add("streak_5")
    if best_streak >= 10:
        unlocked_ids.add("streak_10")
    if correct_total >= 50:
        unlocked_ids.add("correct_50")
    if correct_total >= 200:
        unlocked_ids.add("correct_200")
    for lv in levels:
        if lv["cleared"]:
            unlocked_ids.add(f"clear_{lv['level']}")
    if mastered >= 50:
        unlocked_ids.add("mastered_50")
    if days >= 3:
        unlocked_ids.add("days_3")

    stored = set(json.loads(store.profile_get("achievements", "[]")))
    new = unlocked_ids - stored
    if new:
        store.profile_set("achievements", json.dumps(sorted(stored | new), ensure_ascii=False))

    achievements = [
        {**a, "unlocked": a["id"] in (stored | unlocked_ids)} for a in ACHIEVEMENTS
    ]

    return {
        "xp": xp,
        "rank": rank_of(xp),
        "answered": answered,
        "correct": correct_total,
        "accuracy": round(correct_total / answered * 100, 1) if answered else None,
        "best_streak": best_streak,
        "days": days,
        "mastered_cards": mastered,
        "levels": levels,
        "achievements": achievements,
        "new_achievements": [a["name"] for a in ACHIEVEMENTS if a["id"] in new],
    }
