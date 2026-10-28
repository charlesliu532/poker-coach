"""翻前范围库（按位置）。数字来自课程/数据库，标注来源与置信度。"""

# ── 开池范围 ──────────────────────────────────────────────
# 来源优先级：Preflop Xploits 02-02 转写（UTG 20% / HJ 24% / CO 30% / BTN 43% / SB 全同花）
# 注：Upswing 的 UTG 是 16.5%，与本课 20% 不同，此处采本课（有视频原话支撑）
UTG = ("55+, A2s+, K5s, Q9s, J9s, T9s, 98s, 87s, 76s, 65s, 67s, 54s, "
       "KTo+, QTo+, JTo, AJo+, KQo, ATo")
HJ = ("55+, A2s+, K5s+, Q9s+, J9s+, T9s, 98s, 87s, 76s, 65s, 67s, 54s, "
      "KTo+, QTo+, JTo, ATo+, KJo, KQo, AJo+")
CO = ("33+, A2s+, K5s+, Q7s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, "
      "KTo+, QTo+, JTo, ATo+, KJo+, KQo, A9o+, K9o+, Q9o+, J9o+, T9o")
# BTN 开池 ~45-50%
BTN = ("22+, A2s+, K2s+, Q5s+, J7s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, 43s, "
       "A2o+, K9o+, Q9o+, J9o+, T9o, 98o")
# SB 开池 ~43.6%
# SB：原文「很接近按钮，再多 1.5% 左右」→ 取 ≈ BTN（43%）。
# ⚠ 原文同时说「不开任何 offsuit」，两者数学上不能同时成立（全同花上限 29.4%）——
#   判定为 ASR 串行，采用「接近 BTN」这一说法。
SB = ("22+, A2s+, K2s+, Q5s+, J7s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, "
      "A2o+, K9o+, Q9o+, J9o+, T9o")
# BB 跟注（对 BTN 的宽防守；对 UTG 会紧很多）
# 跟注范围要剔除会被 3bet 的顶端（AA-QQ、AK）；否则密度计算会把 BB 的坚果虚高
BB_VS_BTN = ("22-JJ, A2s-ATs, K2s+, Q2s+, J3s+, T4s+, 95s+, 84s+, 74s+, 63s+, 53s+, 43s, "
             "A2o-AQo, K5o+, Q6o+, J7o+, T7o+, 96o+, 86o+, 76o, 65o")
BB_VS_UTG = ("22-JJ, A2s-ATs, K5s+, Q7s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, "
             "A8o-AQo, K9o+, Q9o+, J9o+, T9o")
_FIXED = {"UTG": UTG, "HJ": HJ, "CO": CO, "BTN": BTN, "SB": SB,
          "BB": BB_VS_BTN, "BB_VS_UTG": BB_VS_UTG}


def get(pos: str, vs: str | None = None) -> str:
    if pos.upper() == "BB" and vs:
        return BB_VS_UTG if vs.upper() == "UTG" else BB_VS_BTN
    return _FIXED[pos.upper()]


# ── 3-Bet 范围（按「3bet 方 vs 开池方」）──────────────────────────
# 来源：青阳 L23/L24（3bet or fold、SB 10bb、BB 11bb）+ Upswing 线性化倾向
SB_3BET_VS_BTN = ("TT+, AQs+, AKo, AKo, KQs, AJs, KJs, QJs, JTs, T9s, 98s, "
                  "A5s, A4s, K9s")
BB_3BET_VS_BTN = ("99+, AJs+, KQs, AQo+, KQo, JTs, T9s, A5s, A4s")
BB_3BET_VS_UTG = "QQ+, AKs, AKo, AQs"
BTN_3BET_VS_CO = "TT+, AJs+, KQs, AQo+, A5s, K9s"
BTN_3BET_VS_UTG = "JJ+, AQs+, AKo, A5s"

_THREE = {
    ("SB", "BTN"): SB_3BET_VS_BTN, ("SB", "CO"): SB_3BET_VS_BTN,
    ("BB", "BTN"): BB_3BET_VS_BTN, ("BB", "CO"): BB_3BET_VS_BTN,
    ("BB", "UTG"): BB_3BET_VS_UTG,  ("BB", "HJ"): BB_3BET_VS_UTG,
    ("BTN", "CO"): BTN_3BET_VS_CO,  ("CO", "HJ"): BTN_3BET_VS_CO,
    ("BTN", "UTG"): BTN_3BET_VS_UTG,
}


def threebet(hero: str, villain: str) -> str:
    """hero 对 villain 开池做 3bet 的范围。"""
    return _THREE.get((hero.upper(), villain.upper()), BB_3BET_VS_BTN)
