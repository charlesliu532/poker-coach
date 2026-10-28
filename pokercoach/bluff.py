"""按 EV surplus 排序选诈唬 —— 「配额由 alpha 定，选牌由阻断牌定」。

传统桶表只会说「空气下注 40%」，等于假设所有空气都一样该诈唬。
但 solver 里空气并不等价：拿 A♠x 诈唬比拿 A♥x 好，因为它挡掉对手更多强牌
（AA/AK/Ax 的跟注），对手更难跟，弃牌率更高。所以：

    1. 配额：这个尺度该有多少诈唬 → alpha 公式 B/(P+2B)
    2. 选牌：把空气按 EV surplus 从高到低排，取够配额就停

surplus（底池 = 1，下注 = s）：
    f  = 基准弃牌率 × (1 + 1.6·挡强牌 − 1.1·挡弱牌)
    EV = f·1 − (1−f)·s

挡掉对手**会跟/会加**的强牌 → f 升 → 更该诈唬；
挡掉对手**本来会弃**的弱牌 → 他没牌可弃了 → 反而不该诈唬。
"""
from __future__ import annotations

AIR_CATS = ("纯空气", "后门空气", "空气")

# 牌力前 30% 视为「会跟注/加注的强牌」，其余视为「会弃的弱牌」
STRONG_FRAC = 0.30
K_STRONG = 1.6
K_WEAK = 1.1


def _popcount_hit(cards: tuple[int, int], seg: list[tuple[int, int]]) -> float:
    if not seg:
        return 0.0
    a, b = cards
    hit = sum(1 for c1, c2 in seg if c1 == a or c2 == a or c1 == b or c2 == b)
    return hit / len(seg)


# 板面牌力分：判断对手这手牌「会不会跟/加」要用牌面，不是翻前强度。
# A72 面上的 22 是暗三条（会跟），不能因为它翻前弱就算进弃牌段。
_CAT_STRENGTH = {
    "两对+": 1.00, "暗三条": 0.98, "超对": 0.95, "三条": 0.92,
    "顶对好踢": 0.82, "顶对弱踢": 0.74, "顶对": 0.72,
    "中对": 0.62, "底对": 0.50, "小口袋对": 0.55,
    "听牌": 0.62, "卡顺": 0.55,
    "A大": 0.45, "A中": 0.36, "A小": 0.28,
    "后门空气": 0.22, "纯空气": 0.15, "空气": 0.15,
}


def _board_strength(board, c1: int, c2: int) -> float:
    """对手具体组合在牌面上的牌力分（0-1）。"""
    try:
        from .tree import classify
        hole = [(c1 // 4 + 2, c1 % 4), (c2 // 4 + 2, c2 % 4)]
        cat = classify(board, hole)
        return _CAT_STRENGTH.get(cat, 0.3)
    except Exception:
        try:
            from .ranges import combo_to_hand
            from .tree import _hand_strength
            return _hand_strength(combo_to_hand(c1, c2))
        except Exception:
            return 0.3


def _split_villain(villain_combos, strong_frac: float, board=None):
    """把对手范围按**牌面牌力**切成「强 / 弱」两段（只切一次）。"""
    vc = []
    for item in villain_combos or []:
        vc.append((item[0], item[1]))
    if not vc:
        return [], []
    vc.sort(key=lambda c: -_board_strength(board or [], c[0], c[1]))
    k = max(1, int(len(vc) * max(0.05, min(0.9, strong_frac))))
    return vc[:k], vc[k:]


def _alpha(size_pct: float) -> float:
    s = max(0.0, float(size_pct)) / 100.0
    return s / (1.0 + s)


def rank(hero_combos, board, villain_combos, size_pct: float,
         fold_base: float | None = None, strong_frac: float = STRONG_FRAC,
         k_strong: float = K_STRONG, k_weak: float = K_WEAK) -> list[dict]:
    """给每个具体组合算 surplus，从高到低排。

    hero_combos: [(c1, c2)] 牌编码（rank*4+suit，rank=0..12）
    board: [(rank, suit)]，rank=2..14（tree.parse_board 的输出）
    """
    from .tree import classify

    s = max(0.0, float(size_pct)) / 100.0
    base = _alpha(size_pct) if fold_base is None else max(0.0, min(0.99, float(fold_base)))
    strong, weak = _split_villain(villain_combos, strong_frac, board)
    out = []
    for c1, c2 in hero_combos or []:
        hole = [(c1 // 4 + 2, c1 % 4), (c2 // 4 + 2, c2 % 4)]
        try:
            cat = classify(board, hole)
        except Exception:
            cat = "纯空气"
        bs = _popcount_hit((c1, c2), strong)
        bw = _popcount_hit((c1, c2), weak)
        f = base * (1.0 + k_strong * bs - k_weak * bw)
        f = max(0.0, min(0.98, f))
        surplus = f * 1.0 - (1.0 - f) * s
        out.append({
            "c1": c1, "c2": c2,
            "combo": _combo_name(c1, c2),
            "cat": cat,
            "is_air": cat in AIR_CATS,
            "block_strong": round(bs, 4),
            "block_weak": round(bw, 4),
            "f": round(f, 4),
            "surplus": round(surplus, 4),
        })
    out.sort(key=lambda x: (-x["surplus"], -x["block_strong"], x["block_weak"],
                            x["c1"], x["c2"]))
    for i, x in enumerate(out):
        x["rank"] = i + 1
    return out


def _combo_name(c1: int, c2: int) -> str:
    from .ranges import combo_to_hand
    try:
        return combo_to_hand(c1, c2)
    except Exception:
        return "??"


def choose(ranked: list[dict], target_combos: float) -> list[dict]:
    """按 surplus 从高到低取，直到取够 target_combos。

    每个具体组合权重 1；边界上的组合可以只取一部分（take ∈ (0,1)）。
    """
    remaining = max(0.0, float(target_combos))
    for x in ranked:
        if remaining <= 0:
            x["selected"] = False
            x["take"] = 0.0
            continue
        if not x.get("is_air"):
            x["selected"] = False
            x["take"] = 0.0
            continue
        take = 1.0 if remaining >= 1.0 else remaining
        x["selected"] = True
        x["take"] = round(take, 3)
        remaining -= take
    return ranked


def plan(cells, hero_combos, board, villain_combos, size_pct: float,
         fold_base: float | None = None, target_scale: float = 1.0) -> dict | None:
    """在节点上执行「配额 → 排序 → 选牌」，返回可展示的计划。

    cells 只用来读桶表给的下注率（价值/空气各有多少组合在打）；
    真正改 bucket 的动作在 tree.grid 里做。
    """
    from .ranges import combo_to_hand

    if not hero_combos or not villain_combos:
        return None
    t = _alpha(size_pct) / (1.0 + _alpha(size_pct))   # 诈唬占下注范围的比例
    # 按类别归组具体组合
    by_cls: dict[str, list[tuple[int, int]]] = {}
    for c1, c2 in hero_combos:
        by_cls.setdefault(combo_to_hand(c1, c2), []).append((c1, c2))

    value_combos = 0.0
    air_cells = []
    for c in cells:
        cid = c.get("combo")
        b = c.get("bucket")
        if c.get("impossible") or b is None:
            continue
        variants = by_cls.get(cid) or []
        if not variants:
            continue
        if (c.get("cat") or "") in AIR_CATS:
            if b > 0:
                air_cells.append((c, variants))
        else:
            value_combos += len(variants) * float(b) / 100.0

    if not air_cells or value_combos <= 0:
        return None
    air_available = sum(len(v) * float(c["bucket"]) / 100.0 for c, v in air_cells)
    quota = value_combos * t / max(1e-6, 1.0 - t)
    # 对手形象：过度诈唬型 → 少诈唬；下注不足型 → 多诈唬。
    # 必须在配额这一层乘，否则会被「按 alpha 截断空气」覆盖掉。
    quota *= max(0.0, float(target_scale))
    target = min(quota, air_available)
    if target < 0.5 or target >= air_available * 0.98:
        return {"ok": False, "why": "配额与桶表接近，不需要重选诈唬",
                "target": round(target, 2), "air_available": round(air_available, 2),
                "quota": round(quota, 2), "target_share": round(t, 4)}

    candidates = [pair for _c, variants in air_cells for pair in variants]
    ranked = choose(rank(candidates, board, villain_combos, size_pct, fold_base),
                    target)
    return {
        "ok": True,
        "size_pct": size_pct,
        "target_share": round(t, 4),
        "quota": round(quota, 2),
        "air_available": round(air_available, 2),
        "target": round(target, 2),
        "selected": round(sum(x["take"] for x in ranked if x.get("selected")), 2),
        "ranked": ranked,
    }
