"""毫秒级快速修正层（CFR 思想，但不是完整 CFR）。

目的：策略树的规则给的是「牌面类别 → 尺度」，粒度到类别。
本模块用真实牌面做一次蒙特卡洛胜率 + 范围优势计算，把规则的频率/尺度
按实测优势微调，让同一个「高A-低-彩」在不同具体牌面上不完全一样。

- 纯 Python，不依赖 numpy（打包体积不变）
- 目标：单次 < 30ms
- 不做博弈迭代，只算「范围 vs 范围」的胜率差 → 优势指数
"""
from __future__ import annotations

import random
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "shdc"


def _card_idx(r: str, s: str) -> int:
    return RANKS.index(r) * 4 + SUITS.index(s)


def _expand(hand: str, dead: set) -> list:
    """'AKs' → 具体两张牌的组合列表（排除已用掉的牌）。"""
    if len(hand) == 2:
        r = hand[0]
        return [(_card_idx(r, SUITS[i]), _card_idx(r, SUITS[j]))
                for i in range(4) for j in range(i + 1, 4)
                if _card_idx(r, SUITS[i]) not in dead and _card_idx(r, SUITS[j]) not in dead]
    r1, r2 = hand[0], hand[1]
    want_suited = hand.endswith("s")
    out = []
    for s1 in SUITS:
        for s2 in SUITS:
            if want_suited and s1 != s2:
                continue
            if not want_suited and s1 == s2:
                continue
            a, b = _card_idx(r1, s1), _card_idx(r2, s2)
            if a in dead or b in dead:
                continue
            out.append((a, b))
    return out


def _best5(cards: list) -> tuple:
    """7 张里挑最好的 5 张，返回可比较的评分元组。"""
    best = None
    for c5 in combinations(cards, 5):
        rs = sorted((c // 4 for c in c5), reverse=True)
        ss = [c % 4 for c in c5]
        flush = len(set(ss)) == 1
        from collections import Counter
        cnt = Counter(rs)
        groups = sorted(cnt.items(), key=lambda x: (-x[1], -x[0]))
        shape = tuple(g[1] for g in groups)
        # 顺子
        uniq = sorted(set(rs), reverse=True)
        straight_hi = None
        for i in range(len(uniq) - 4):
            if uniq[i] - uniq[i + 4] == 4:
                straight_hi = uniq[i]
                break
        if straight_hi is None and 12 in uniq and 0 in uniq and 1 in uniq and 2 in uniq and 3 in uniq:
            straight_hi = 3
        if flush and straight_hi is not None:
            score = (8, straight_hi)
        elif shape[0] == 4:
            score = (7, groups[0][0], groups[1][0])
        elif shape[0] == 3 and shape[1] == 2:
            score = (6, groups[0][0], groups[1][0])
        elif flush:
            score = (5, *rs)
        elif straight_hi is not None:
            score = (4, straight_hi)
        elif shape[0] == 3:
            score = (3, groups[0][0], *[g[0] for g in groups[1:]])
        elif shape[0] == 2 and shape[1] == 2:
            score = (2, groups[0][0], groups[1][0], groups[2][0])
        elif shape[0] == 2:
            score = (1, groups[0][0], *[g[0] for g in groups[1:]])
        else:
            score = (0, *rs)
        if best is None or score > best:
            best = score
    return best


def equity(hero_hands: list, villain_hands: list, board: list,
           iters: int = 300, seed: int = 0) -> float:
    """hero 范围 vs villain 范围，在给定牌面上的胜率（0-1）。"""
    if not hero_hands or not villain_hands:
        return 0.5
    rng = random.Random(seed)
    dead = set(board)
    wins = ties = 0
    for _ in range(iters):
        h = rng.choice(hero_hands)
        v = rng.choice(villain_hands)
        used = dead | set(h) | set(v)
        if len(used) != len(dead) + 4:
            continue
        need = 5 - len(board)
        pool = [c for c in range(52) if c not in used]
        run = rng.sample(pool, need) if need > 0 else []
        full = list(board) + run
        hs = _best5(full + list(h))
        vs = _best5(full + list(v))
        if hs > vs:
            wins += 1
        elif hs == vs:
            ties += 1
    tot = wins + ties
    return (wins + ties * 0.5) / iters if iters else 0.5


def advantage(hero_range: str, villain_range: str, board_text: str,
              iters: int = 300) -> dict:
    """范围优势指数：>0 我方优势，<0 对手优势。"""
    from .ranges import parse_range
    try:
        board = [_card_idx(board_text[i].upper(), board_text[i + 1].lower())
                 for i in range(0, len(board_text), 2)
                 if i + 1 < len(board_text)]
    except Exception:
        return {"ok": False}
    dead = set(board)
    hero_hands = []
    for c in parse_range(hero_range):
        # parse_range 给的是 (card1, card2) 双牌组合
        if c[0] not in dead and c[1] not in dead:
            hero_hands.append((c[0], c[1]))
    vill_hands = []
    for c in parse_range(villain_range):
        if c[0] not in dead and c[1] not in dead:
            vill_hands.append((c[0], c[1]))
    if not hero_hands or not vill_hands:
        return {"ok": False}
    eq = equity(hero_hands, vill_hands, board, iters=iters)
    return {"ok": True, "equity": round(eq, 4),
            "adv": round(eq - 0.5, 4),
            "n_hero": len(hero_hands), "n_vill": len(vill_hands)}


def best_response(hero_range: str, villain_range: str, board_text: str,
                  base_pct: float, iters: int = 200) -> dict:
    """最佳反应：锁定对手范围后，我方该怎么调整尺度/频率。

    依据 solver 架构文档的三种语义之一（best_response）：
    锁定对手 → 我方针对方这个范围做 max-EV 调整。
    """
    r = advantage(hero_range, villain_range, board_text, iters=iters)
    if not r.get("ok"):
        return {"ok": False}
    new_pct, why = refine_sizing(base_pct, r["adv"])
    return {"ok": True, "semantics": "best_response",
            "equity": r["equity"], "adv": r["adv"],
            "base_sizing": base_pct, "br_sizing": round(new_pct),
            "why": why,
            "label": f"对手被锁定 → 我方胜率 {r['equity']*100:.1f}%，{why}"}


def refine_sizing(base_pct: float, adv: float) -> tuple:
    """按范围优势微调尺度：优势越大越敢打大。

    返回 (新尺度, 说明)
    """
    if adv >= 0.10:
        return base_pct * 1.25, "范围优势大 → 尺度上调 25%"
    if adv >= 0.04:
        return base_pct * 1.10, "略有优势 → 尺度上调 10%"
    if adv <= -0.10:
        return base_pct * 0.75, "范围劣势 → 尺度下调 25%"
    if adv <= -0.04:
        return base_pct * 0.90, "略处劣势 → 尺度下调 10%"
    return base_pct, "均势 → 维持规则尺度"
