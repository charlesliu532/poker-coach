"""开池范围对比：把你的实际开池频率，叠到一张 13×13 的手牌矩阵上。

参考范围是六人桌 100bb 的标准开池区间（不是 GTO 精确解，是"合理基准"），
用来回答一个问题：哪些该开的牌你一次都没开过。
"""

from __future__ import annotations

from ..cards import RANKS
from ..ranges import parse_range

# 标准 6-max 开池范围（100bb）。改这里就能换基准。
REFERENCE: dict[str, str] = {
    "UTG": "22+, A2s+, K9s+, Q9s+, J9s+, T9s, 98s, 87s, 76s, ATo+, KQo",
    "HJ": "22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, A9o+, KJo+, QJo",
    "CO": "22+, A2s+, K4s+, Q6s+, J7s+, T7s+, 96s+, 85s+, 75s+, 64s+, 54s, A7o+, K9o+, Q9o+, J9o+, T9o",
    # 课程里给的是 BTN 约 45%（2.25x、100bb），这里对齐课程口径
    "BTN": (
        "22+, A2s+, K4s+, Q6s+, J7s+, T7s+, 96s+, 85s+, 74s+, 64s+, 54s, 43s, "
        "A2o+, K9o+, Q9o+, J9o+, T9o, K5s, Q5s, J6s, T6s, 95s, 84s, 63s, 53s, "
        "K8o, Q8o, J8o, T8o, 98o"
    ),
    "SB": "22+, A2s+, K4s+, Q6s+, J7s+, T7s+, 96s+, 85s+, 75s+, 64s+, 54s, A7o+, K9o+, Q9o+, J9o+, T9o",
}


def classes_of(expr: str) -> set[str]:
    out: set[str] = set()
    for a, b, _w in parse_range(expr):
        ra, rb = a // 4, b // 4
        if ra == rb:
            out.add(RANKS[ra] * 2)
        else:
            hi, lo = max(ra, rb), min(ra, rb)
            out.add(f"{RANKS[hi]}{RANKS[lo]}{'s' if a % 4 == b % 4 else 'o'}")
    return out


_COMBO_WEIGHT = {"s": 4, "o": 12}


def combo_pct(expr: str) -> float | None:
    """按组合数加权算开池率，和 HUD 上的 RFI 口径一致。"""
    if not expr:
        return None
    combos = 0
    for cls in classes_of(expr):
        combos += 6 if len(cls) == 2 else _COMBO_WEIGHT[cls[-1]]
    return round(combos / 1326 * 100, 1)


def grid_order() -> list[str]:
    return list(reversed(RANKS))


def build_matrix(flags: list[dict], pos: str) -> dict:
    """统计这个位置每类手牌被发到多少次、开了多少次。"""
    dealt: dict[str, int] = {}
    opened: dict[str, int] = {}
    for f in flags:
        if f.get("pos") != pos or not f.get("first_in", True):
            continue
        hand = f.get("hand") or "?"
        if hand == "?":
            continue
        dealt[hand] = dealt.get(hand, 0) + 1
        if f.get("opened"):
            opened[hand] = opened.get(hand, 0) + 1

    ref = classes_of(REFERENCE.get(pos, "")) if pos in REFERENCE else set()
    rows = []
    for r in grid_order():
        row = []
        for c in grid_order():
            i, j = r, c
            if i == j:
                hand = r + r
            elif RANKS.index(i) > RANKS.index(j):
                hand = i + j + "s"
            else:
                hand = j + i + "o"
            n = dealt.get(hand, 0)
            o = opened.get(hand, 0)
            pct = round(o / n * 100) if n else None
            row.append(
                {
                    "hand": hand,
                    "n": n,
                    "open": o,
                    "pct": pct,
                    "ref": hand in ref,
                }
            )
        rows.append(row)
    return {
        "pos": pos,
        "matrix": rows,
        "reference_pct": combo_pct(REFERENCE.get(pos, "")) if pos in REFERENCE else None,
    }


def find_gaps(flags: list[dict], pos: str, min_n: int = 5) -> dict:
    """该开没开（漏）与该弃却开（多）。"""
    m = build_matrix(flags, pos)
    missing, extra = [], []
    for row in m["matrix"]:
        for cell in row:
            if cell["n"] < min_n:
                continue
            pct = cell["pct"] or 0
            if cell["ref"] and pct <= 30:
                missing.append({**cell, "gap": 100 - pct})
            elif not cell["ref"] and pct >= 50:
                extra.append({**cell, "gap": pct})
    missing.sort(key=lambda x: (-x["gap"], -x["n"]))
    extra.sort(key=lambda x: (-x["gap"], -x["n"]))
    total_open = sum(c["open"] for row in m["matrix"] for c in row)
    total_dealt = sum(c["n"] for row in m["matrix"] for c in row)
    return {
        "pos": pos,
        "open_pct": round(total_open / total_dealt * 100, 1) if total_dealt else None,
        "reference_pct": m["reference_pct"],
        "matrix": m["matrix"],
        "missing": missing[:20],
        "extra": extra[:20],
        "missing_count": len(missing),
        "extra_count": len(extra),
    }
