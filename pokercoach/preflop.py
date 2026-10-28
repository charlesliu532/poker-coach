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

# 6 人桌合法对位共 12 组。原有 9 组有课程数据，缺的 5 组按「就近 + 位置修正」补，
# 每组都标了依据，不再让缺项落到 BB_3BET_VS_BTN 这个最宽的默认值上。
_THREE = {
    ("SB", "BTN"): SB_3BET_VS_BTN,   ("SB", "CO"): SB_3BET_VS_BTN,
    ("BB", "BTN"): BB_3BET_VS_BTN,   ("BB", "CO"): BB_3BET_VS_BTN,
    ("BB", "UTG"): BB_3BET_VS_UTG,   ("BB", "HJ"): BB_3BET_VS_UTG,
    ("BTN", "CO"): BTN_3BET_VS_CO,   ("CO", "HJ"): BTN_3BET_VS_CO,
    ("BTN", "UTG"): BTN_3BET_VS_UTG,
    # ── 补齐（推导，依据写在括号里）────────────────────────
    ("HJ", "UTG"): BB_3BET_VS_UTG,   # 对手是最紧的 UTG 开池 → 用对 UTG 的紧范围
    ("CO", "UTG"): BTN_3BET_VS_UTG,  # 同上，位置比 HJ 好一点
    ("SB", "UTG"): BB_3BET_VS_UTG,   # 盲位对 UTG，最紧
    ("SB", "HJ"):  SB_3BET_VS_BTN,   # 对手 HJ 开池，比 BTN 紧一档 → 用 SB 基准
    ("BTN", "HJ"): BTN_3BET_VS_CO,   # 对手 HJ，介于 CO 与 UTG 之间 → 用对 CO 的
}


def threebet(hero: str, villain: str) -> str:
    """hero 对 villain 开池做 3bet 的范围（优先用 GTO 15 对位表）。"""
    H = _HERO_ALIAS.get(hero.upper(), hero.upper())
    V = _OPENER_ALIAS.get(villain.upper(), villain.upper()).replace("UTG1", "UTG").replace("UTG2", "UTG")
    if (H, V) in GTO_3BET:
        return GTO_3BET[(H, V)][0]
    return _THREE.get((H, V), BB_3BET_VS_BTN)


def threebet_call(hero: str, villain: str) -> str:
    """hero 对 villain 开池时，跟注（不 3bet）的范围。"""
    H = _HERO_ALIAS.get(hero.upper(), hero.upper())
    V = _OPENER_ALIAS.get(villain.upper(), villain.upper()).replace("UTG1", "UTG").replace("UTG2", "UTG")
    if (H, V) in GTO_3BET:
        return GTO_3BET[(H, V)][2]
    return ""


def threebet_pct(hero: str, villain: str) -> float:
    H = _HERO_ALIAS.get(hero.upper(), hero.upper())
    V = _OPENER_ALIAS.get(villain.upper(), villain.upper()).replace("UTG1", "UTG").replace("UTG2", "UTG")
    return GTO_3BET.get((H, V), ("", 0, "", 0))[1]


# ══ GTO 3bet 范围（6人桌 100bb，全部 15 个对位）══════════════════
# 来源：holdempro.app/tools/3-bet-ranges（免费公开的 GTO 简化解算结果）
# 格式：(3bet 范围, 3bet 频率, 跟注范围, 跟注频率)
# 混合频率的手牌用 "A5s:30" 表示「30% 的时候 3bet」
GTO_3BET = {
    ("BB", "UTG"): ("JJ+, AKs, AKo, A4s:20, A5s:20", 3.1,
                    "TT-33, AQs-A9s, A3s-A2s, KTs+, QTs+, JTs, T9s, 98s, 87s, 76s, 65s, 54s, AQo", 10.4),
    ("BB", "MP"):  ("TT+, AQs+, AKo, A5s:30, K9s:20", 3.9,
                    "99-22, AJs-A6s, A4s-A2s, KTs+, K8s-K7s, Q8s+, J9s+, T9s, 98s, 87s, 76s, 65s, 54s, AQo-ATo, KTo+, QJo", 18.3),
    ("BB", "CO"):  ("TT+, AQs+, AQo+, A5s:40, A4s:30, JTs:20, K9s:20, Q9s:20", 5.1,
                    "99-22, AJs-A6s, A3s-A2s, KTs+, K8s-K4s, QTs+, Q8s-Q7s, J9s-J8s, T8s+, 98s, 87s, 76s, 65s, 53s+, 43s, AJo-ATo, KTo+, QTo+, JTo", 21.3),
    ("BB", "BTN"): ("TT+, AJs+, KQs, AQo+, A4s:50, A5s:50, A3s:40, A2s:30, K4s:30, K5s:30, 65s:20, 76s:20, Q9s:20, T9s:20", 6.2,
                    "99-22, ATs-A6s, KJs-K6s, K3s-K2s, QTs+, Q8s-Q2s, J5s+, T8s-T5s, 95s+, 85s+, 75s-74s, 64s, 53s+, 43s, AJo-A5o, K9o+, Q9o+, J9o+, T9o, 98o", 35.6),
    ("BB", "SB"):  ("99+, AJs+, KQs, AJo+, KQo, A5s:50, A4s:40, A3s:30, K9s:30, Q9s:30, 76s:20", 8.1,
                    "88-22, ATs-A6s, A2s, KJs-KTs, K8s-K2s, QTs+, Q8s-Q2s, J6s+, T6s+, 95s+, 85s+, 75s-74s, 64s+, 53s+, 43s, 32s, ATo-A5o, KJo-K4o, Q6o+, J7o+, T7o+, 97o+, 87o, 76o", 46.9),
    ("SB", "UTG"): ("TT+, AJs+, KQs, AKo, A2s:30, A3s:30, 65s:20, 76s:20", 4.7,
                    "99-66, ATs, A5s-A4s, KJs-KTs, QJs, JTs, T9s, 98s, 87s, AQo", 5.7),
    ("SB", "MP"):  ("99+, AJs+, KJs+, QJs, AQo+, KQo:50, A3s:40, A2s:30, 65s:20, K9s:20", 7.1,
                    "88-55, ATs-A9s, A5s-A4s, KTs, QTs, JTs, T9s, 98s, 87s, 76s", 5.1),
    ("SB", "CO"):  ("88+, ATs+, KJs+, QJs, JTs, AQo+, A3s:50, A2s:40, 65s:30, K9s:30, KJo:30, A9o:20, Q9s:20", 8.4,
                    "77-44, A9s-A8s, A5s-A4s, KTs, QTs, T9s, 98s, 87s, 76s, AJo, KQo", 6.6),
    ("SB", "BTN"): ("77+, ATs+, KTs+, QJs, JTs, AJo+, KQo, A4s:60, A5s:60, A3s:50, A2s:40, 54s:30, A9o:30, K8s:30, KTo:30, QJo:30, J8s:20, Q8s:20, T8s:20", 11.8,
                    "66-22, A9s-A6s, K9s, QTs-Q9s, J9s, T9s, 98s, 87s, 76s, 65s, ATo, KJo", 8.0),
    ("BTN", "UTG"): ("JJ+, AQs+, AKo, A6s:30, A7s:30, K9s:30, J9s:20, Q9s:20", 3.7,
                     "TT-22, AJs-A9s, A5s-A2s, KTs+, QTs+, JTs, T9s, 98s, 87s, 76s, 65s, 54s, AQo-AJo, KQo", 12.5),
    ("BTN", "MP"): ("JJ+, AJs+, KQs, AQo+, K8s:30, 53s:20, 64s:20, A9o:20, J8s:20, Q8s:20", 5.3,
                    "TT-22, ATs-A2s, KJs-K9s, Q9s+, J9s+, T8s+, 97s+, 87s, 76s, 65s, 54s, AJo-ATo, KJo+, QJo", 16.1),
    ("BTN", "CO"): ("TT+, AJs+, KQs, AQo+, A4s:50, A5s:50, A3s:30, K9s:20, Q9s:20", 5.8,
                    "99-22, ATs-A6s, A2s, KJs-KTs, K8s-K7s, QTs+, Q8s, J8s+, T8s+, 97s+, 87s, 76s, 65s, 54s, AJo-ATo, KTo+, QTo+, JTo", 19.1),
    ("CO", "UTG"): ("JJ+, AQs+, AKo, A8s:30, 54s:20, K9s:20, Q9s:20", 3.6,
                    "TT-33, AJs-A9s, A5s-A2s, KTs+, QTs+, JTs, T9s, 98s, 87s, 76s, 65s, AQo, KQo", 10.9),
    ("CO", "MP"):  ("JJ+, AQs+, KQs, AKo, A5s:40, A4s:30, 76s:20", 3.9,
                    "TT-22, AJs-A9s, A3s-A2s, KJs-KTs, QTs+, JTs, T9s, 98s, 87s, 65s, 54s, AQo-AJo, KQo", 11.9),
    ("MP", "UTG"): ("JJ+, AQs+, AKo, A3s:30, 65s:20, A2s:20, K9s:20", 3.6,
                    "TT-55, AJs-ATs, A5s-A4s, KTs+, QJs, JTs, T9s, 98s, 87s, 76s, AQo", 7.5),
}

# 8 人桌 / 未覆盖对位 → 按「最接近的开池位置」映射
_OPENER_ALIAS = {"UTG1": "UTG", "UTG2": "UTG", "LJ": "MP", "HJ": "MP"}
# 6人桌 HJ 就是 GTO 表里的 MP
_HERO_ALIAS = {"UTG1": "UTG", "UTG2": "UTG", "LJ": "MP", "HJ": "MP"}
