"""翻前范围 × 翻牌 的坚果优势分析。

设计目的：同一张牌面，不同位置对打出来的策略相反，原因在**翻前范围**不在牌面本身。
例：754 上 UTG 开池几乎没 6x，BTN 开池有一堆 6x → 前者无坚果优势、后者有。

用法：
    python -m pokercoach.rangeboard 754r "UTG" "BB"
"""
from __future__ import annotations

import numpy as np

from . import equity as eq
from . import ranges, tree

NUT_MIN = 2  # 兜底：两对及以上

def nut_threshold(board_cards) -> tuple[int, str]:
    """按牌面类型切换「什么算坚果」。返回 (category 下限, 说明)。"""
    ranks = sorted({c // 4 for c in board_cards})
    suits = {c % 4 for c in board_cards}
    if len(suits) == 1:
        return 5, "天花面 → 坚果 = 同花+"
    if len(ranks) < len(board_cards):
        return 6, "公对面 → 坚果 = 葫芦+"
    span = ranks[-1] - ranks[0]
    if span <= 4:
        return 4, "连张面 → 坚果 = 顺子+"
    return 2, "散张面 → 坚果 = 两对+"


def _board_cards(text: str) -> list[int]:
    """把 "754r" / "Ah7d2c" 解析成 card int 列表。"""
    from . import cards as C
    t = text.strip()
    # 完整写法：Ah7d2c...
    if len(t) >= 6 and all(t[i] in C.RANK_INDEX and t[i + 1] in C.SUIT_INDEX
                           for i in range(0, len(t) - 1, 2)):
        return C.parse_cards(t)
    # 简写：754r / KQ9tt
    style = ""
    if t[-2:] in ("tt", "ss", "rr", "mm"):
        style = t[-2:]; t = t[:-2]
    elif t[-1] in ("r", "m", "t"):
        style = t[-1]; t = t[:-1]
    ranks = [C.RANK_INDEX[c] for c in t if c in C.RANK_INDEX]
    if len(ranks) != 3:
        raise ValueError(f"牌面写法不对：{text}")
    suits = {"r": [0, 1, 2], "tt": [0, 0, 1], "m": [0, 0, 0]}.get(style, [0, 1, 2])
    return [r * 4 + s for r, s in zip(ranks, suits)]


def _side(combos, board, nut_min=NUT_MIN) -> dict:
    """返回该范围在牌面上的构成。"""
    if not combos:
        return {"total": 0, "nut": 0, "cats": {}, "nut_hands": []}
    holes = np.array([[c[0], c[1]] for c in combos], dtype=np.int16)
    bd = np.repeat(np.array([board], dtype=np.int16), len(holes), axis=0)
    full = np.concatenate([holes, bd], axis=1)
    scores = eq.evaluate(full)
    cats = [eq.category_name(s) for s in scores]
    cat_mask = scores >> 40
    nut_idx = np.where(cat_mask >= nut_min)[0]
    nut_hands = sorted({_fmt(combos[i]) for i in nut_idx})
    from collections import Counter
    return {
        "total": len(combos),
        "nut": int(len(nut_idx)),
        "cats": dict(Counter(cats)),
        "nut_hands": nut_hands,
    }


_R = "23456789TJQKA"


def _fmt(combo) -> str:
    a, b = combo[0], combo[1]
    ra, rb = a // 4, b // 4
    sa, sb = a % 4, b % 4
    if ra == rb:
        return _R[ra] * 2
    hi, lo = (ra, rb) if ra > rb else (rb, ra)
    return _R[hi] + _R[lo] + ("s" if sa == sb else "o")


def _cat_of(hole, board) -> str:
    """自己这两张牌在牌面上是什么。"""
    full = np.array([[hole[0], hole[1]] + list(board)], dtype=np.int16)
    return eq.category_name(eq.evaluate(full)[0])


def analyze(board: str, hero_spec: str, villain_spec: str, hero_cards: str | None = None) -> dict:
    cards = _board_cards(board)
    hc = [(c[0], c[1], c[2]) for c in ranges.parse_range(hero_spec)]
    vc = [(c[0], c[1], c[2]) for c in ranges.parse_range(villain_spec)]
    hc = ranges.remove_blocked(hc, cards)
    vc = ranges.remove_blocked(vc, cards)
    nm, why = nut_threshold(cards)
    res_extra = {}
    if hero_cards:
        from . import cards as C
        mine = C.parse_cards(hero_cards)
        if len(mine) != 2:
            raise ValueError("底牌要两张，如 6s6h")
        v_before = _side(vc, cards, nm)
        vc2 = ranges.remove_blocked(vc, mine)
        hc2 = ranges.remove_blocked(hc, mine)
        v_after = _side(vc2, cards, nm)
        h_after = _side(hc2, cards, nm)
        res_extra = {
            "hero_cards": hero_cards,
            "hero_hand": _cat_of(mine, cards),
            "villain_before": v_before["nut"],
            "villain_after": v_after["nut"],
            "villain_combos_after": v_after["total"],
            "blocked_nuts": v_before["nut"] - v_after["nut"],
            "block_pct": (v_before["nut"] - v_after["nut"]) / max(v_before["nut"], 1),
            "hero_range_nut_after": h_after["nut"],
        }
    h, v = _side(hc, cards, nm), _side(vc, cards, nm)
    hp = h["nut"] / max(h["total"], 1)
    vp = v["nut"] / max(v["total"], 1)
    return {"board": board, "hero": h, "villain": v,
            "hero_pct": hp, "villain_pct": vp,
            "ratio": h["nut"] / max(v["nut"], 1),
            "nut_def": why,
            "density": (hp / vp) if vp > 0 else float("inf"),
            "verdict": _verdict(h["nut"], v["nut"], hp, vp),
            **res_extra}


def analyze_combos(board: str, hero_combos, villain_combos) -> dict:
    """和 analyze 一样，但直接吃组合列表（不用文本范围）。"""
    cards = _board_cards(board)
    nm, why = nut_threshold(cards)
    hc = ranges.remove_blocked([(a, b, 1.0) for a, b in hero_combos], cards)
    vc = ranges.remove_blocked([(a, b, 1.0) for a, b in villain_combos], cards)
    h, v = _side(hc, cards, nm), _side(vc, cards, nm)
    hp = h["nut"] / max(h["total"], 1)
    vp = v["nut"] / max(v["total"], 1)
    return {"board": board, "hero": h, "villain": v,
            "hero_pct": hp, "villain_pct": vp,
            "ratio": h["nut"] / max(v["nut"], 1), "nut_def": why,
            "density": (hp / vp) if vp > 0 else float("inf"),
            "verdict": _verdict(h["nut"], v["nut"], hp, vp)}


def _verdict(nut_h: int, nut_v: int, pct_h: float = 0.0, pct_v: float = 0.0) -> str:
    """坚果优势看「坚果占自身范围的比例」之比（密度），不是绝对组数——
    绝对组数会被宽范围天然拉高，让 BB 永远显得有优势。"""
    if nut_h == 0 and nut_v == 0:
        return "双方都没有坚果 → 只看范围/权益优势"
    r = (pct_h / pct_v) if pct_v > 0 else (2.0 if pct_h > 0 else 1.0)
    if r >= 1.4:
        return "我方明显坚果优势（≥1.4 倍）→ 可上大尺度/超池"
    if r >= 1.1:
        return "我方略优（1.1–1.4 倍）→ 中等尺度"
    if r <= 0.5:
        return "对手坚果是我方 2 倍以上 → 降尺度或高频过牌"
    if r <= 0.9:
        return "对手略优（0.5–0.9 倍）→ 保守"
    return "接近对称 → 小尺度范围下注或极化二选一"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print(__doc__)
        raise SystemExit(1)
    board, hero, villain = sys.argv[1], sys.argv[2], sys.argv[3]
    mine = sys.argv[4] if len(sys.argv) > 4 else None
    from . import preflop
    r = analyze(board, preflop.get(hero), preflop.get(villain), mine)
    print(f"牌面 {board}　坚果定义：{r['nut_def']}")
    for name, side, pct in (("我方", r["hero"], r["hero_pct"]), ("对手", r["villain"], r["villain_pct"])):
        print(f"  {name}: {side['total']:4d} 组合，两对+ {side['nut']:3d}（{pct:.1%}）")
        print(f"        坚果手牌: {' '.join(side['nut_hands'][:18])}")
    if "blocked_nuts" in r:
        print(f"  我持 {r['hero_cards']}（{r['hero_hand']}）")
        print(f"        对手坚果: {r['villain_before']} → {r['villain_after']} 组"
              f"（挡掉 {r['blocked_nuts']} 组，{r['block_pct']:.0%}）")
        print(f"        对手剩余范围: {r['villain_combos_after']} 组")
    print("  →", r["verdict"])
