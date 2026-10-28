"""EQR（权益实现率）：把「裸胜率」修成「实际能拿到的权益」。

为什么需要它：
  裸 equity 假设「所有牌都能把胜率兑现成底池份额」，但现实不是——
  OOP 兑现不了那么多，小对子要靠隐含赔率，A高面的大牌 miss 后很难继续。
  V(h) ≈ EQR(h, 位置, SPR) × equity(h, 对手范围, 牌面) × 底池

EQR 是标定系数，不是理论推导值。本表按常见扑克共识设定，
标 conf=推导，可以用真实数据再校准。
"""
from __future__ import annotations

# 手牌类别 → (IP 系数, OOP 系数)
# 依据：位置越好越能兑现；小对子/同花连张在深 SPR 靠隐含赔率，浅 SPR 兑现差
_EQR = {
    "big_pair":   (1.02, 0.95),   # AA-JJ：几乎不 miss
    "small_pair": (0.92, 0.82),   # 77-22：无隐含赔率时兑现差
    "suited_bw":  (1.00, 0.92),   # 同花大牌 AKs-KTs
    "offsuit_bw": (0.92, 0.84),   # 非同花大牌 AKo-KTo
    "suited_conn":(1.03, 0.93),   # 同花连张 98s-54s：深筹码靠听牌
    "suited_ace": (1.00, 0.90),   # A5s-A2s：Blockers + 同花
    "suited_other":(0.96, 0.88),
    "offsuit_other":(0.86, 0.78), # 基本兑现不了
}

RANKS = "23456789TJQKA"


def classify_hand(hand: str) -> str:
    """把手牌分到 _EQR 的类别。"""
    if len(hand) < 2:
        return "offsuit_other"
    r1, r2 = hand[0], hand[1]
    if len(hand) == 2:
        i = RANKS.index(r1) if r1 in RANKS else 0
        return "big_pair" if i >= 8 else "small_pair"   # JJ+
    hi = max(RANKS.index(r1), RANKS.index(r2))
    lo = min(RANKS.index(r1), RANKS.index(r2))
    suited = hand.endswith("s")
    if not suited:
        return "offsuit_bw" if hi >= 10 else "offsuit_other"
    # 同花
    # 连张只算「两张都不大」的，AKs 属于同花大牌
    if (hi - lo == 1 and hi <= 10) or (hi - lo == 2 and 6 <= hi <= 10):
        return "suited_conn"
    if hi == 12 and lo <= 4:
        return "suited_ace"
    if hi >= 9:
        return "suited_bw"
    return "suited_other"


def spr_factor(spr: float) -> float:
    """SPR 修正：深筹码放大隐含赔率型手牌的 EQR，浅筹码压缩。"""
    if spr <= 1.5:
        return 0.85
    if spr <= 3:
        return 0.92
    if spr <= 6:
        return 1.00
    if spr <= 12:
        return 1.05
    return 1.08


def get(hand: str, in_position: bool, spr: float = 6.0) -> dict:
    """返回单手牌的 EQR 系数与说明。"""
    cat = classify_hand(hand)
    ip, oop = _EQR.get(cat, (0.9, 0.82))
    base = ip if in_position else oop
    sf = spr_factor(spr)
    val = round(base * sf, 3)
    return {"hand": hand, "cat": cat, "eqr": val,
            "base": base, "spr_factor": sf,
            "pos": "IP" if in_position else "OOP"}


def realized_equity(equity: float, hand: str, in_position: bool,
                    spr: float = 6.0) -> dict:
    """实际权益 = 裸权益 × EQR（上限 1）。"""
    g = get(hand, in_position, spr)
    val = min(1.0, equity * g["eqr"])
    return {**g, "raw_equity": round(equity, 4), "realized": round(val, 4)}


# ══ 按「牌面实际牌力」的 EQR（比按手牌名准）═══════════════
# AA 和 KK 在 A72 面差别很大：暗三条能兑现 100%，超对只有 60%
_BOARD_EQR = {
    "暗三条": (1.08, 1.02), "坚果": (1.10, 1.05), "三条": (1.05, 1.00),
    "两对": (1.05, 0.98), "两对+": (1.05, 0.98),
    "顶对好踢": (1.02, 0.94), "顶对": (1.00, 0.92), "顶对弱踢": (0.98, 0.90),
    "中对": (0.92, 0.82), "底对": (0.85, 0.74),
    "超对": (0.95, 0.85), "听牌": (1.04, 0.94), "强听牌": (1.06, 0.96),
    "卡顺": (0.90, 0.82), "后门空气": (0.80, 0.72),
    "A大": (0.95, 0.86), "高张": (0.88, 0.80), "空气": (0.78, 0.70),
    "纯空气": (0.78, 0.70),
}


def from_board_cat(cat: str, in_position: bool, spr: float = 6.0) -> dict:
    """按牌面牌力类别取 EQR（比按手牌名更准）。"""
    ip, oop = _BOARD_EQR.get(cat or "", (0.90, 0.82))
    base = ip if in_position else oop
    val = round(base * spr_factor(spr), 3)
    return {"cat": cat, "eqr": val, "base": base, "spr_factor": spr_factor(spr)}


# ══ 扰动测试：判断混合比例是「有意义」还是「任意」═══════════
# 依据：均衡价值唯一、均衡策略不唯一。真正无差异的节点上，
# 任何比例都最优；一个 solver 给 60/40，另一个给 45/55，同样 GTO。
# 所以我们要测：把参数扰动 1%，比例会不会剧烈翻转。
def perturb_stable(parts: list, hand_class: str, hand_cat: str,
                   noise: float = 0.01) -> dict:
    """对尺度分配做扰动测试。

    parts: [{"label": str, "pct": float}, ...]（已按 EQR 分配）
    返回每个动作的稳定性：翻转 = 任意；稳定 = 有意义。
    """
    import random
    rng = random.Random(7)
    if len(parts) < 2:
        return {"stable": True, "flips": [], "note": "只有一个动作"}
    base_order = [p["label"] for p in sorted(parts, key=lambda x: -x["pct"])]
    flips = []
    for _ in range(12):
        noisy = [dict(p, pct=p["pct"] * (1 + rng.uniform(-noise, noise))) for p in parts]
        order = [p["label"] for p in sorted(noisy, key=lambda x: -x["pct"])]
        if order[:2] != base_order[:2]:
            flips.append(order[0])
    ratio = len(flips) / 12
    return {
        "stable": ratio < 0.3,
        "flip_rate": round(ratio, 2),
        "flips": sorted(set(flips)),
        "note": ("比例稳定，可以当参考" if ratio < 0.3
                 else "比例不稳定 → 只记「边界」和「聚合频率」，别背百分比"),
    }
