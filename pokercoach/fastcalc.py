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
    """按范围优势**连续**调整尺度。

    原来是 5 档（±10%/±25%/不动），导致胜率 25% 和 37% 拿到同一个建议。
    改成连续映射：adv 每偏离 1 个百分点，尺度按比例动 2.2 个百分点。
    """
    # 优势 → 倍数，范围 [0.6, 1.45]，连续无台阶
    mult = 1.0 + (adv / 0.10) * 0.22
    mult = max(0.60, min(1.45, mult))
    new_pct = base_pct * mult
    gain = (mult - 1.0) * 100
    if abs(gain) < 3:
        why = f"均势（优势 {adv*100:+.1f}%）→ 维持 {round(new_pct)}%"
    elif gain > 0:
        why = f"占优 {adv*100:+.1f}% → 尺度 {base_pct:.0f}% ⇒ {round(new_pct)}%（+{gain:.0f}%）"
    else:
        why = f"劣势 {adv*100:+.1f}% → 尺度 {base_pct:.0f}% ⇒ {round(new_pct)}%（{gain:.0f}%）"
    return new_pct, why


# ══ 频率也要跟着对手形象变（不只是尺度）═══════════════════
# 逻辑：
#   跟注站/娱乐玩家 → 诈唬没意义，价值该多打 → 整体频率「按价值权重」上调
#   岩石/紧凶      → 他们弃牌多，诈唬更值 → 整体频率上调，但价值别过火
#   受气包         → 他们不会弃也不会加 → 只打价值，频率降
# 注意：这是**启发式**，不是 solver 频率。
_FREQ_ADJ = {
    "跟注站":   {"value": +0.15, "bluff": -0.25, "net": +0.05},
    "娱乐玩家": {"value": +0.12, "bluff": -0.20, "net": +0.04},
    "岩石":     {"value": -0.05, "bluff": +0.20, "net": +0.10},
    "紧凶":     {"value": -0.03, "bluff": +0.12, "net": +0.06},
    "松凶":     {"value": +0.02, "bluff": -0.08, "net": -0.02},
    "受气包":   {"value": +0.10, "bluff": -0.20, "net": -0.05},
    "标准":     {"value": 0.0, "bluff": 0.0, "net": 0.0},
}


def refine_frequency(base_freq: float, adv: float, opp_type: str = "*",
                     hand_role: str = "value") -> dict:
    """按「对手形象 + 范围优势 + 这手牌是价值还是诈唬」调整下注频率。

    base_freq: 规则给的基础频率（%）
    adv: 范围优势
    hand_role: value / bluff / merged
    """
    adj = _FREQ_ADJ.get((opp_type or "").strip()) or {"value": 0, "bluff": 0, "net": 0}
    role_adj = {"value": adj["value"], "bluff": adj["bluff"]}.get(hand_role, 0)
    # 范围优势也影响：优势越大越该打
    adv_adj = (adv / 0.10) * 0.10
    delta = adj["net"] + role_adj + adv_adj
    new_freq = max(0.0, min(100.0, base_freq * (1 + delta)))
    why = []
    if abs(adj["net"]) > 0.005:
        why.append(f"对手 {opp_type} → 基础 {adj['net']*100:+.0f}%")
    if abs(role_adj) > 0.005:
        why.append(f"这手是{('价值' if hand_role=='value' else '诈唬')} → {role_adj*100:+.0f}%")
    if abs(adv_adj) > 0.01:
        why.append(f"优势 {adv*100:+.0f}% → {adv_adj*100:+.0f}%")
    return {"base_freq": round(base_freq, 1),
            "freq": round(new_freq),
            "delta_pct": round(delta * 100),
            "why": "，".join(why) or "对手标准 → 维持规则频率"}


# ══ 诈唬比例校验（alpha / MDF）══════════════════════════════
# 理论：下注 b（底池比例 s），对手的 MDF = 1/(1+s)，
# 我们的下注范围里「诈唬应占」alpha = s/(1+s)。
# 例：33% 池 → 24.8% 的注应该是诈唬；100% 池 → 50%。
# 这给出「伙牌比例是否合理」的硬检查，不依赖 solver。
def bluff_ratio_target(size_pct: float) -> float:
    """诈唬应占**总下注**的比例 = B/(P+2B)。

    注意区分三件事（很容易混）：
      MDF   = P/(P+B)      防守方该跟多少
      alpha = B/(P+B)      bluff:value 的比例 (alpha : 1)
      诈唬占下注范围 = B/(P+2B) = alpha/(1+alpha)
    33% 池：MDF 75.2%，alpha 24.8%，诈唬占 19.9%。
    """
    s = max(0.0, float(size_pct)) / 100.0
    return s / (1.0 + 2.0 * s)


def mdf(size_pct: float) -> float:
    """对手的最小防守频率。"""
    s = max(0.0, float(size_pct)) / 100.0
    return 1.0 / (1.0 + s)


def alpha(size_pct: float) -> float:
    """bluff:value 中的 alpha（不是占比）。"""
    s = max(0.0, float(size_pct)) / 100.0
    return s / (1.0 + s)


def check_bluff_mix(value_pct: float, bluff_pct: float, size_pct: float) -> dict:
    """校验一个节点的价值/诈唬比例是否接近 alpha。"""
    tot = value_pct + bluff_pct
    if tot <= 0:
        return {"ok": None, "note": "没有下注"}
    actual = bluff_pct / tot
    target = bluff_ratio_target(size_pct)
    dev = actual - target
    return {
        "ok": abs(dev) <= 0.15,
        "actual_bluff_share": round(actual, 3),
        "target_bluff_share": round(target, 3),
        "deviation": round(dev, 3),
        "size_pct": size_pct,
        "note": ("诈唬比例合理" if abs(dev) <= 0.15 else
                 ("诈唬过多（容易被抓）" if dev > 0 else "诈唬过少（对手弃牌太多）")),
    }


# ══ 第二层：构成 —— 按 EV surplus 排序挑诈唬，考虑阻断牌 ═════
# Solver 没有「诈唬」类别，它算 EV(bet) − EV(check)。
# 纯 air 时 surplus = f·P − (1−f)·B，f 是**考虑阻断牌后**的弃牌概率。
# 所以诈唬范围在牌力上不单调：A♠x 比 A♥x 更该诈唬，哪怕牌力一样。
def blocker_effect(hero_cards: tuple, villain_combos: list,
                   strong_frac: float = 0.30) -> dict:
    """这手牌对手范围里强牌/弱牌的阻断程度。

    hero_cards: (c1, c2) 整数编码
    villain_combos: [(c1, c2, weight)] 对手范围
    strong_frac: 把对手范围按牌力前多少算「强牌（会跟/会加）」
    """
    h1, h2 = hero_cards
    if not villain_combos:
        return {"block_strong": 0.0, "block_weak": 0.0, "n": 0}
    # 按牌力排序切出强/弱两段
    from .tree import _hand_strength
    from .ranges import combo_to_hand
    try:
        ordered = sorted(villain_combos, key=lambda c: -_hand_strength(combo_to_hand(c[0], c[1])))
    except Exception:
        ordered = villain_combos
    k = max(1, int(len(ordered) * strong_frac))
    strong, weak = ordered[:k], ordered[k:]
    def _blocks(seg):
        if not seg:
            return 0.0
        hit = sum(1 for c in seg if c[0] in (h1, h2) or c[1] in (h1, h2))
        return hit / len(seg)
    return {"block_strong": round(_blocks(strong), 4),
            "block_weak": round(_blocks(weak), 4),
            "n": len(villain_combos)}


def bluff_surplus(fold_base: float, pot: float, bet: float,
                  block_strong: float, block_weak: float,
                  k_strong: float = 1.6, k_weak: float = 1.1) -> dict:
    """纯 air 的诈唬 surplus。

    挡掉对手强牌 → 他更难跟 → f 升
    挡掉对手弱牌 → 他 air 变少 → 反倒不该诈唬 → f 降
    """
    f = fold_base * (1 + k_strong * block_strong - k_weak * block_weak)
    f = max(0.0, min(0.98, f))
    surplus = f * pot - (1 - f) * bet
    return {"f": round(f, 4), "surplus": round(surplus, 4),
            "should_bluff": surplus > 0,
            "why": (f"弃牌率 {f*100:.0f}% vs alpha {alpha(100*bet/max(1e-9,pot))*100:.0f}%"
                    + (" → 该诈唬" if surplus > 0 else " → 不该诈唬"))}
