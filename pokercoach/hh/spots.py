"""翻后细分：按牌面结构统计你的动作频率。

回答的是这类问题：A 高牌面我是不是下注太多？什么转牌我弃得过多？
每个"spot"只记两件事：牌面类型 + 你做了什么。
"""

from __future__ import annotations

from collections import defaultdict

from ..cards import parse_card, rank_of, suit_of

# 牌面类型 → 合理的下注/弃牌区间（微级别经验值，用来定位偏离，不是判分）
CBET_BANDS = {
    "A高": (70, 88),
    "K高": (60, 78),
    "Q高": (52, 72),
    "J-T高": (45, 66),
    "低牌": (32, 58),
}

TURN_FOLD_BANDS = {
    "超张": (40, 58),
    "成花": (52, 72),
    "成顺": (50, 70),
    "公对面": (38, 58),
    "白板": (38, 55),
}


def _flop_high(ranks: list[int]) -> str:
    top = max(ranks)
    if top == 12:
        return "A高"
    if top == 11:
        return "K高"
    if top == 10:
        return "Q高"
    if top >= 8:
        return "J-T高"
    return "低牌"


def flop_tags(board: list[int]) -> dict:
    ranks = [rank_of(c) for c in board]
    suits = [suit_of(c) for c in board]
    uniq = sorted(set(ranks))
    if len(set(suits)) == 1:
        suited = "同花面"
    elif len(set(suits)) == 2:
        suited = "双花面"
    else:
        suited = "彩虹面"
    return {
        "high": _flop_high(ranks),
        "paired": len(uniq) < 3,
        "suited": suited,
        "connected": len(uniq) >= 3 and uniq[-1] - uniq[0] <= 4,
    }


def _has_four_straight(ranks: list[int]) -> bool:
    s = set(ranks)
    if 12 in s:
        s.add(-1)  # A 可以当 1
    for lo in range(-1, 10):
        if all(x in s for x in range(lo, lo + 4)):
            return True
    return False


def turn_tags(flop: list[int], turn: int) -> list[str]:
    """转牌相对翻牌发生了什么变化。"""
    fr = [rank_of(c) for c in flop]
    to = rank_of(turn)
    suits = [suit_of(c) for c in flop] + [suit_of(turn)]
    tags = []
    if to in fr:
        tags.append("公对面")
    if to > max(fr):
        tags.append("超张")
    if suits.count(suit_of(turn)) >= 3:
        tags.append("成花")
    if _has_four_straight(fr + [to]):
        tags.append("成顺")
    return tags or ["白板"]


def hero_spots(h) -> list[dict]:
    """从一手牌里抽出英雄的翻后决策点。"""
    hero = h.hero
    if not h.board or len(h.board) < 3:
        return []
    board = [parse_card(c) for c in h.board]
    flop, turn = board[:3], board[3] if len(board) >= 4 else None

    pre = [a for a in h.actions if a.street == "preflop" and a.kind != "post"]
    raisers = [a for a in pre if a.kind == "raises"]
    pfa = raisers[-1].player if raisers else None
    if pfa != hero:
        return []  # 只看自己是翻前加注者的局面

    spots = []
    flop_actions = [a for a in h.actions if a.street == "flop"]
    if flop_actions:
        first_bet = next((a for a in flop_actions if a.kind in ("bets", "raises")), None)
        hero_idx = next((i for i, a in enumerate(flop_actions) if a.player == hero), None)
        if hero_idx is not None and (first_bet is None or first_bet.player == hero):
            t = flop_tags(flop)
            acted = flop_actions[hero_idx]
            spots.append(
                {
                    "st": "flop",
                    "high": t["high"],
                    "texture": [t["suited"]] + (["公对面"] if t["paired"] else []) + (["连牌"] if t["connected"] else []),
                    "act": "bet" if acted.kind in ("bets", "raises") else "check",
                }
            )

    if turn is not None:
        turn_actions = [a for a in h.actions if a.street == "turn"]
        bets = [a for a in turn_actions if a.kind in ("bets", "raises")]
        if bets:
            first = bets[0]
            hero_idx = next((i for i, a in enumerate(turn_actions) if a.player == hero), None)
            if hero_idx is not None and turn_actions.index(first) < hero_idx and first.player != hero:
                tags = turn_tags(flop, turn)
                acted = turn_actions[hero_idx]
                spots.append(
                    {
                        "st": "turn",
                        "tags": tags,
                        "act": "fold" if acted.kind == "folds" else ("raise" if acted.kind == "raises" else "call"),
                    }
                )
    return spots


def summarize(flags: list[dict]) -> dict:
    """按牌面类型聚合：下注率 / 弃牌率。"""
    flop = defaultdict(lambda: {"n": 0, "bet": 0})
    turn = defaultdict(lambda: {"n": 0, "fold": 0, "call": 0, "raise": 0})
    for f in flags:
        for s in f.get("spots", []):
            if s["st"] == "flop":
                b = flop[s["high"]]
                b["n"] += 1
                b["bet"] += s["act"] == "bet"
            elif s["st"] == "turn":
                for tag in s["tags"]:
                    b = turn[tag]
                    b["n"] += 1
                    b["fold"] += s["act"] == "fold"
                    b["call"] += s["act"] == "call"
                    b["raise"] += s["act"] == "raise"

    out_flop = []
    for name in ("A高", "K高", "Q高", "J-T高", "低牌"):
        v = flop.get(name)
        if not v or v["n"] < 15:
            continue
        pct = round(v["bet"] / v["n"] * 100, 1)
        lo, hi = CBET_BANDS[name]
        out_flop.append(
            {
                "name": name, "n": v["n"], "pct": pct, "band": f"{lo}~{hi}",
                "verdict": "偏高" if pct > hi else ("偏低" if pct < lo else "正常"),
            }
        )

    out_turn = []
    for name in ("超张", "成花", "成顺", "公对面", "白板"):
        v = turn.get(name)
        if not v or v["n"] < 15:
            continue
        pct = round(v["fold"] / v["n"] * 100, 1)
        lo, hi = TURN_FOLD_BANDS[name]
        out_turn.append(
            {
                "name": name, "n": v["n"], "pct": pct, "band": f"{lo}~{hi}",
                "verdict": "偏高" if pct > hi else ("偏低" if pct < lo else "正常"),
                "raise_pct": round(v["raise"] / v["n"] * 100, 1),
            }
        )
    return {"flop": out_flop, "turn": out_turn}


def render_report(summary: dict) -> str:
    lines = []
    if summary["flop"]:
        lines.append("翻牌 cbet 率（你是翻前加注者、轮到你行动时）")
        for r in summary["flop"]:
            mark = "" if r["verdict"] == "正常" else f"  ← {r['verdict']}"
            lines.append(f"  {r['name']:5s} {r['pct']:5.1f}%  基准 {r['band']}  n={r['n']}{mark}")
        lines.append("")
    if summary["turn"]:
        lines.append("转牌面对下注的弃牌率")
        for r in summary["turn"]:
            mark = "" if r["verdict"] == "正常" else f"  ← {r['verdict']}"
            lines.append(
                f"  {r['name']:5s} 弃 {r['pct']:5.1f}%  基准 {r['band']}  "
                f"加注 {r['raise_pct']:4.1f}%  n={r['n']}{mark}"
            )
    return "\n".join(lines) if lines else "样本不足，先多打一些手再来看。"
