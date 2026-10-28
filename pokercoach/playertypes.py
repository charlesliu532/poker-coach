"""玩家类型：直接采用课程里的分类，并挂上对应的范围。

分类来源（都在你的 Notion 课程笔记里）：
- 《1.3 HUD和玩家数据》：紧凶 TAG / 松凶 LAG / 岩石 Nit / 跟注站 CS
- 《BvB 数据库分析 - SB 开池》：超级老板型 / 紧弱或娱乐玩家 / 实力较强的常客
- 《03 高抽水环境翻前策略》：跟注站多时用线性范围
- 《M03-L06 C-Bet 策略》：针对 Nit / LAG / CS 做极化或剥削

范围本身：少数是笔记里明确给了频率（比如对超级老板 SB 可以开 100%），
其余是"该类型的典型范围"，按通用经验补的，代码里标了 note 字段。
"""

from __future__ import annotations

import json as _json
from pathlib import Path

from .paths import data_path

CAVEAT = (
    "课程原文：本节所涉及的范围仅供说明方向之用，切勿直接照搬。"
    "真正需要掌握的是驱动调整的底层逻辑，而非具体数值。——《Preflop Xploits》M04-L01"
)

TYPES: list[dict] = [
    {
        "axis": "中性",
        "adjust": "按理论范围打，不做偏移",
        "id": "紧凶",
        "alias": ["TAG", "常客", "Regular"],
        "vpip": "22~28%",
        "desc": "有位置意识、会 3bet、翻后能弃牌。默认按理论范围打他。",
        "range": "22+, A2s+, K9s+, QTs+, JTs, T9s, 98s, ATo+, KQo",
        "note": "分类出自《HUD和玩家数据》；范围按常客的典型范围补",
    },
    {
        "axis": "偏松",
        "adjust": "侧重价值、减少诈唬；别用中等强度跟他打大池",
        "id": "松凶",
        "alias": ["LAG", "Maniac", "狂人"],
        "vpip": "30~40%",
        "desc": "开池宽、爱 3bet、翻后频繁施压。别用中等强度跟他打大池。",
        "range": "22+, A2s+, K4s+, Q7s+, J8s+, T7s+, 96s+, 85s+, 75s+, A4o+, K9o+, Q9o+, J9o+, T9o",
        "note": "分类出自《HUD和玩家数据》；范围按 LAG 典型范围补",
    },
    {
        "axis": "紧",
        "adjust": "侧重诈唬剥削：他弃牌多，多偷盲、少给价值",
        "id": "岩石",
        "alias": ["Nit", "紧弱"],
        "vpip": "15~20%",
        "desc": "只玩强牌、很少诈唬。他加注你就得小心，但他弃牌多，可以多偷。",
        "range": "77+, ATs+, KQs, AQo+, AJo, KQo",
        "note": "分类出自《HUD和玩家数据》；BvB 一节提到对紧弱可用约 58.4% 的宽范围开池",
    },
    {
        "axis": "松",
        "adjust": "侧重价值剥削：价值打足，诈唬全部停掉",
        "id": "跟注站",
        "alias": ["CS", "Calling Station"],
        "vpip": "45~60%",
        "desc": "几乎不弃牌、对尺度不敏感。价值打足，诈唬全部停掉。",
        "range": "22+, A2s+, K2s+, Q5s+, J6s+, T6s+, 95s+, 84s+, 74s+, 63s+, 53s+, A2o+, K7o+, Q8o+, J8o+, T8o+, 98o, 87o",
        "note": "分类出自《HUD和玩家数据》与《03 高抽水环境》；「跟注站多时用线性范围」也在这两节",
    },
    {
        "axis": "极松",
        "adjust": "侧重价值剥削：范围极宽、几乎不弃牌，直接打价值",
        "id": "娱乐玩家",
        "alias": ["鱼", "Fish", "超级老板", "Recreational"],
        "vpip": "60%+",
        "desc": "什么牌都玩、很少 3bet。BvB 一节说对他 SB 可以开 100%。",
        "range": "22+, A2s+, K2s+, Q2s+, J3s+, T5s+, 94s+, 83s+, 72s+, 62s+, 52s+, 42s+, A2o+, K2o+, Q4o+, J6o+, T7o+, 96o+, 85o+, 75o+, 65o",
        "note": "BvB 一节：对超级老板型直接用 100% 极宽开池",
    },
]


# ── 「标准」：按我们自己的基线打，作为所有剥削的参照点 ──────────
_STANDARD = {
    "axis": "基准",
    "adjust": "他就是我们的基准：不需要剥削，按树里的标准策略打",
    "id": "标准",
    "alias": ["Baseline", "GTO", "理论型"],
    "vpip": "基准",
    "preflop": {"vpip": 21, "pfr": 18, "3bet": 8},
    "desc": ("按我们策略树的基线打：翻前范围、cbet 频率、抓诈比例都符合标准。"
             "拿他当参照——对任何其他类型的调整，都是相对他算出来的偏移。"),
    # range 留空 → analyze_vs 时用「我方位置对应的基线范围」代替，
    # 这样密度天然等于 1.00，可以直接当 1.0 的锚点
    "range": None,
    "note": "基准型；密度按定义 = 1.00，用来衡量其他类型偏离多少",
}
TYPES.insert(0, _STANDARD)

# ── 策略树 vs_type 里在用、原先缺的三类 ──────────────────────
_EXTRA = [
    {"axis": "被动", "adjust": "他不加注、不诈唬 → 不用平衡，价值打足、别想诈唬他",
     "id": "受气包", "alias": ["Punching Bag", "沙袋"],
     "vpip": "25~35%", "preflop": {"vpip": 30, "pfr": 6, "3bet": 2},
     "desc": "几乎不主动下注/加注，无 XR、无诈唬；不解读尺度，只按绝对牌力反应。",
     "range": "22+, A2s+, K9s+, QTs+, JTs, T9s, 98s, ATo+, KQo, KJo",
     "note": "出自《精英现金剥削 M03-L03/L12》；范围按「跟注但不加注」的被动型补"},
    {"axis": "偏差·翻后", "adjust": "他诈唬过多 → 抓诈放宽、少弃牌；价值下注别过薄",
     "id": "过度诈唬型", "alias": ["Over-bluffer"],
     "vpip": "22~30%", "preflop": {"vpip": 26, "pfr": 22, "3bet": 10},
     "desc": "翻前接近常客，但翻后下注/加注频率显著高于 GTO，河牌爱施压。",
     "range": "22+, A2s+, K9s+, QTs+, JTs, T9s, 98s, ATo+, KQo",
     "note": "范围按常客取；差异在翻后频率，不在范围"},
    {"axis": "偏差·翻后", "adjust": "他不下注 → 别指望他替你做大底池，强牌自己打；他的下注偏价值",
     "id": "下注不足型", "alias": ["Under-bettor"],
     "vpip": "22~30%", "preflop": {"vpip": 26, "pfr": 18, "3bet": 7},
     "desc": "翻前接近常客，但翻后下注频率偏低、尺度偏小，强牌爱慢玩。",
     "range": "22+, A2s+, K9s+, QTs+, JTs, T9s, 98s, ATo+, KQo",
     "note": "范围按常客取；差异在翻后频率，不在范围"},
]
for _t in _EXTRA:
    if _t["id"] not in {x["id"] for x in TYPES}:
        TYPES.append(_t)
BY_ID = {t["id"]: t for t in TYPES}
# 旧名兼容：树里历史数据用过这些叫法
ALIAS = {"常客": "紧凶", "娱乐": "娱乐玩家", "紧弱": "岩石", "激进型": "松凶", "鱼": "娱乐玩家"}
for _a, _b in ALIAS.items():
    if _b in BY_ID:
        BY_ID.setdefault(_a, BY_ID[_b])

import json


def effective(store) -> list[dict]:
    """基础类型 + 用户在本机改过的范围。"""
    out = []
    for t in TYPES:
        d = dict(t)
        raw = store.profile_get(f"ptype:{t['id']}")
        if raw:
            try:
                d.update(json.loads(raw))
            except Exception:
                pass
        out.append(d)
    return out


def get(name: str, store=None) -> dict:
    if store is not None:
        for t in effective(store):
            if t["id"] == name:
                return t
    return BY_ID.get(name, BY_ID["紧凶"])


def options(store=None) -> list[dict]:
    items = effective(store) if store is not None else TYPES
    return [
        {"id": t["id"], "vpip": t["vpip"], "desc": t["desc"],
         "axis": t.get("axis", ""), "adjust": t.get("adjust", ""), "caveat": CAVEAT}
        for t in items
    ]


def combo_pct(range_str: str) -> float | None:
    from .ranges import parse_range

    try:
        combos = sum(w for _, _, w in parse_range(range_str))
    except Exception:
        return None
    return round(combos / 1326 * 100, 1)


# ══ 类型 → 翻前宽度 ══════════════════════════════════════════
PREFLOP_ADJUST = {
    "标准":  (1.00, "按基线开", "他不偏离，你也不用偏离"),
    "岩石":  (1.20, "开更宽（多偷）", "他弃牌多、3bet 少 → 偷盲价值高"),
    "紧凶":  (1.05, "略宽", "他会 3bet，别开太野"),
    "受气包": (1.25, "开很宽", "他几乎不 3bet → 你几乎无成本开池"),
    "松凶":  (0.85, "开窄一点", "他爱 3bet → 减少被反制的开池牌"),
    "跟注站": (0.90, "开窄、加大尺度", "他从不弃牌 → 偷盲免费，但别用垃圾牌打大池"),
    "娱乐玩家": (1.00, "宽度不变、尺度加大", "他爱跟 → 用强牌大注榨价值，少诈唬"),
    "过度诈唬型": (0.95, "略窄", "他翻后施压多 → 开池牌要更能扛"),
    "下注不足型": (1.10, "略宽", "他不下注 → 你有更多位置价值"),
}

# ══ 轴二：翻后频率（不改范围，只改门槛）══════════════════════
TENDENCY_ADJUST = {
    # 每一种形象都要有翻后数值，不能只有两个「偏差型」：
    # 紧凶/松凶/跟注站这些是玩家池里最常见的，选它们必须能看到频率变化。
    "标准":   {"bluff_catch": 0.00, "value_thin": 0.00, "bluff": 0.00,
               "note": "标准对手 → 按基线"},
    "紧凶":   {"bluff_catch": +0.05, "value_thin": -0.05, "bluff": +0.12,
               "note": "紧凶弃牌多、诈唬少 → 多偷，价值别太薄"},
    "松凶":   {"bluff_catch": +0.10, "value_thin": +0.05, "bluff": -0.10,
               "note": "松凶跟/加都多 → 少诈唬、价值打足"},
    "岩石":   {"bluff_catch": -0.05, "value_thin": -0.10, "bluff": +0.20,
               "note": "岩石极紧、弃牌多 → 多偷，薄价值少打"},
    "跟注站":  {"bluff_catch": -0.25, "value_thin": +0.15, "bluff": -0.25,
               "note": "跟注站跟太多 → 价值打足、诈唬停掉"},
    "娱乐玩家": {"bluff_catch": -0.20, "value_thin": +0.12, "bluff": -0.20,
               "note": "娱乐玩家爱跟 → 价值打足、少诈唬"},
    "受气包":  {"bluff_catch": -0.15, "value_thin": +0.10, "bluff": -0.20,
               "note": "受气包不弃也不加 → 只打价值，诈唬降"},
    "过度诈唬型": {"bluff_catch": +0.20, "value_thin": +0.10, "bluff": -0.30,
                   "note": "他诈唬过多 → 多抓、少诈唬；但他也会跟，薄价值可以打"},
    "下注不足型": {"bluff_catch": -0.25, "value_thin": -0.10, "bluff": +0.15,
                   "note": "他不下注、下注偏价值 → 他一下注就该弃；强牌别慢玩，自己打"},
}

# ══ 3bet 范围（他加注用的那部分，不在跟注范围里）══════════════
THREEBET_RANGE = {
    # 标准用基线（含 A5s/A4s/JTs/T9s 这类极化牌）
    "标准":   "99+, AJs+, KQs, AQo+, KQo, JTs, T9s, A5s, A4s",
    "跟注站":  "AA, KK, AKs, AKo",
    "受气包":  "AA, KK, AKs",
    "岩石":   "QQ+, AKs, AKo, AQs",
    "紧凶":   "TT+, AQs+, AKo, KQs, AJs",
    "松凶":   "77+, ATs+, KQs, AJo+, A5s, A4s, K9s",
    "娱乐玩家": "AA, KK, AKs",
    "过度诈唬型": "TT+, AQs+, AKo, KQs, A5s, KTo, QTo",
    "下注不足型": "QQ+, AKs, AKo, AQs",
}


def combos_of(spec: str):
    from .ranges import parse_range

    return {(c[0], c[1]) for c in parse_range(spec)}


def split_range(type_id: str, opp_pos: str = "BB"):
    """返回 (跟注组合, 3bet组合, 全范围文本, 3bet范围文本)。

    他 3bet 的那些牌不会出现在跟注范围里——这是「跟注站也有 3% 3bet」的含义。
    """
    from .preflop import get as base_get

    t = BY_ID.get(type_id)
    if not t:
        raise KeyError(type_id)
    full_spec = t.get("range") or (base_get(opp_pos) if opp_pos else base_get("BB", "BTN"))
    tb_spec = THREEBET_RANGE.get(type_id) or "QQ+, AKs, AKo"
    full, tb = combos_of(full_spec), combos_of(tb_spec)
    return sorted(full - tb), sorted(tb), full_spec, tb_spec


def analyze_vs(board: str, type_id: str, hero_pos: str = "BTN",
               opp_pos: str = "BB", pot_type: str = "SRP") -> dict:
    """类型 → 按池型取范围（SRP 用跟注部分 / 3BP 用 3bet 部分）→ 密度 → 建议。"""
    from . import rangeboard
    from .preflop import get as our_range

    t = BY_ID.get(type_id)
    if not t:
        return {"error": f"没有这个玩家类型：{type_id}"}

    flat, tb, full_spec, tb_spec = split_range(type_id, opp_pos)
    use_tb = pot_type in ("3BP", "4BP")
    their = tb if use_tb else flat
    if not their:
        return {"error": "这个类型在这个池型下没有范围"}

    ours = sorted(combos_of(our_range(hero_pos, opp_pos if opp_pos else None)))
    head = rangeboard.analyze_combos(board, ours, their)
    dens = head["density"]

    if dens >= 1.4:
        advice = "你明显坚果优势（≥1.4）→ 可上大尺度/超池"
    elif dens >= 1.15:
        advice = "你有坚果优势 → 中大尺度、偏高频率"
    elif dens >= 0.85:
        advice = "坚果接近对称 → 小尺度高频，或走极化；不要超池"
    else:
        advice = "对手坚果更多（<0.85）→ 保守，别超池，控制底池"

    _pw = PREFLOP_ADJUST.get(t["id"], (1.0, "", ""))
    pre_w = width_of(t["id"])
    pre_txt, pre_why = _pw[1], _pw[2]
    return {
        "type": t["id"], "vpip_range": t["vpip"], "preflop": t.get("preflop"),
        "is_baseline": t["id"] == "标准",
        "pot_type": pot_type,
        "range_used": "3bet 范围" if use_tb else "跟注范围",
        "their_range": tb_spec if use_tb else full_spec,
        "their_n": len(their), "flat_n": len(flat), "threebet_n": len(tb),
        "board": board,
        "nut_density": (round(dens, 2) if dens != float("inf") else None),
        "nut_density_text": ("∞（他没有坚果）" if dens == float("inf") else f"{dens:.2f}"),
        "nut_def": head["nut_def"],
        "their_cats": {k: v for k, v in head["villain"].items() if not isinstance(v, list)},
        "our_cats": {k: v for k, v in head["hero"].items() if not isinstance(v, list)},
        "sizing_advice": advice,
        "preflop_width_factor": pre_w, "preflop_width_txt": pre_txt,
        "preflop_width_why": pre_why,
        "tendency_adjust": tendency_of(t["id"]),
        "freq": freq_of(t["id"]),
        "tendency": t.get("adjust", ""),
        "desc": t.get("desc", ""),
        "adjust_text": t.get("adjust", ""),
        "identify": t.get("identify", ["", ""]),
        "caveat": CAVEAT,
        "scenarios": compare_scenarios(board, type_id, hero_pos, opp_pos)["scenarios"],
    }

# ══ 独立频率模型 ════════════════════════════════════════════
# 关键修正：VPIP 宽 ≠ 3bet 宽，3bet 宽 ≠ 4bet 宽。
# 这三件事互相独立，不能用一个数推另一个。
#   vpip      : 入池频率（跟注 or 加注，都算）
#   pfr       : 翻前加注频率
#   threebet  : 面对单次加注时，加注回去的频率
#   call3bet  : 自己被 3bet 后，**跟注**的比例（不是 4bet）
#   fourbet   : 自己被 3bet 后，再加注的频率
FREQ = {
    "标准":    {"vpip": 21, "pfr": 18, "threebet": 8,  "call3bet": 55, "fourbet": 2},
    "岩石":    {"vpip": 17, "pfr": 14, "threebet": 5,  "call3bet": 32, "fourbet": 2},
    "紧凶":    {"vpip": 25, "pfr": 20, "threebet": 9,  "call3bet": 50, "fourbet": 3},
    "松凶":    {"vpip": 35, "pfr": 28, "threebet": 15, "call3bet": 62, "fourbet": 7},
    "跟注站":   {"vpip": 52, "pfr": 8,  "threebet": 3,  "call3bet": 78, "fourbet": 1},
    "娱乐玩家":  {"vpip": 62, "pfr": 10, "threebet": 4,  "call3bet": 82, "fourbet": 1},
    "受气包":   {"vpip": 30, "pfr": 6,  "threebet": 2,  "call3bet": 72, "fourbet": 0},
    "过度诈唬型": {"vpip": 26, "pfr": 22, "threebet": 11, "call3bet": 48, "fourbet": 6},
    "下注不足型": {"vpip": 24, "pfr": 18, "threebet": 7,  "call3bet": 55, "fourbet": 2},
}

# 被 3bet 后「跟注」用的范围（不是 4bet 范围，两者独立）
CALL_3BET_RANGE = {
    "标准":    "22-JJ, A2s-AQs, KTs+, QTs+, JTs, T9s, 98s, AJo+, KQo",
    "岩石":    "QQ-JJ, AKs, AQs, TT-99",
    "紧凶":    "JJ-77, AQs+, ATs, KQs, KJs, QJs, JTs, T9s, AQo",
    "松凶":    "JJ-55, AQs+, ATs+, KQs, KJs, QJs, JTs, T9s, 98s, AQo, KQo, AJo",
    "跟注站":   "22-QQ, A2s-ATs, KTs+, QTs+, JTs, T9s, 98s, AJo+, KJo+, QJo",
    "娱乐玩家":  "22-QQ, A2s-AJs, KTs+, QTs+, JTs, T9s, 98s, 87s, AJo+, KJo+, QJo, JTo",
    "受气包":   "22-QQ, A2s-AJs, KTs+, QTs+, JTs, AJo+, KJo+",
    "过度诈唬型": "JJ-55, AQs+, ATs+, KQs, KJs, QJs, JTs, T9s, AQo, KQo",
    "下注不足型": "JJ-77, AQs+, ATs, KQs, QJs, JTs, AQo",
}

# ══ 三种场景：他用的范围完全不同 ══════════════════════════════
SCENARIOS = {
    "SRP":        ("flat",      "单加注池：我们开池、他跟注"),
    "3BP_IPFR":   ("call3bet",  "3bet 池：我 3bet、他跟注（他是 3bet 的跟注方）"),
    "3BP_ICALL":  ("threebet",  "3bet 池：他 3bet、我跟注（他是 3bet 方）"),
    "4BP":        ("threebet",  "4bet 池：他 3bet 后继续"),
}


def range_for_scenario(type_id: str, scenario: str, opp_pos: str = "BB"):
    """返回 (组合列表, 说明, 范围文本)。 """
    flat, tb, full_spec, tb_spec = split_range(type_id, opp_pos)
    kind, label = SCENARIOS.get(scenario, ("flat", ""))
    if kind == "threebet":
        return tb, label + "｜3bet 范围", tb_spec
    if kind == "call3bet":
        spec = CALL_3BET_RANGE.get(type_id) or CALL_3BET_RANGE["标准"]
        return sorted(combos_of(spec)), label + "｜跟注 3bet 范围", spec
    return flat, label + "｜跟注范围", full_spec


def compare_scenarios(board: str, type_id: str, hero_pos: str = "BTN",
                      opp_pos: str = "BB") -> dict:
    """把三种场景的密度一次算出来，用于对照。"""
    from . import rangeboard
    from .preflop import get as our_range

    ours = sorted(combos_of(our_range(hero_pos, opp_pos if opp_pos else None)))
    out = {"type": type_id, "board": board, "scenarios": {}}
    for sc in SCENARIOS:
        combos, label, spec = range_for_scenario(type_id, sc, opp_pos)
        if not combos:
            continue
        r = rangeboard.analyze_combos(board, ours, combos)
        _dens = r["density"]
        out["scenarios"][sc] = {
            "label": label,
            # inf 不能直接进 JSON（Python 会写 Infinity，浏览器 JSON.parse 会拒绝）
            "density": (None if _dens == float("inf") else round(_dens, 2)),
            "their_n": len(combos), "their_nut": r["villain"]["nut"],
            "our_nut": r["hero"]["nut"], "range_spec": spec,
        }
    return out

# ── 可编辑配置：data/tree/adjustments.json ────────────────────
_CFG_PATH = data_path("tree", "adjustments.json")


def load_adjustments() -> dict:
    """读配置文件；文件不存在就用代码里的默认值。"""
    try:
        return json.loads(_CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_adjustments(cfg: dict) -> None:
    _CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def freq_of(type_id: str) -> dict:
    """频率：优先用配置文件里的，否则用默认。"""
    f = load_adjustments().get("freq", {}).get(type_id)
    return f or FREQ.get(type_id) or FREQ["标准"]


def width_of(type_id: str):
    cfg = load_adjustments().get("preflop_width", {})
    w = cfg.get(type_id)
    return w if w is not None else PREFLOP_ADJUST.get(type_id, (1.0,))[0]


def tendency_of(type_id: str):
    cfg = load_adjustments().get("tendency", {})
    return cfg.get(type_id) or TENDENCY_ADJUST.get(type_id)

def merge_adjustments(patch: dict) -> dict:
    """局部更新：只覆盖传上来的字段，没传的保持原值。

    之前是整份覆盖——上传一个精简载荷会把其他类型全冲掉。
    """
    cur = load_adjustments()
    if not cur:
        cur = {"freq": {}, "preflop_width": {}, "tendency": {}}
    for section in ("freq", "preflop_width", "tendency"):
        if section not in patch:
            continue
        incoming = patch[section] or {}
        if not isinstance(incoming, dict):
            continue
        base = cur.setdefault(section, {})
        for type_id, val in incoming.items():
            if isinstance(val, dict):
                base.setdefault(type_id, {})
                if isinstance(base[type_id], dict):
                    base[type_id].update(val)      # 逐字段合并
                else:
                    base[type_id] = val
            else:
                base[type_id] = val
    for k, v in patch.items():
        if k not in ("freq", "preflop_width", "tendency", "cfg"):
            cur[k] = v
    save_adjustments(cur)
    return cur

# ══ 一眼识别：在牌桌上怎么判断他是哪一类 ══════════════════════
IDENTIFY = {
    "标准":    ("不太有明显漏洞：会弃牌、会诈唬、尺度合理", "摊牌时他亮的牌和该有的范围基本吻合"),
    "紧凶":    ("入池不多但一入池就加注，PFR 和 VPIP 差距小", "翻后能弃掉顶对，不会一路跟到底"),
    "松凶":    ("入池多、加注多，翻牌后经常连开两三条街", "你过牌他就下注，尺度还偏大"),
    "岩石":    ("入池极少，几乎不 3bet，一加注基本就是大牌", "摊牌只亮 AA/KK/AK 这类，从不亮诈唬"),
    "跟注站":   ("什么牌都跟，VPIP 很高但 PFR 很低", "你下多大他都跟，很少主动下注或加注"),
    "娱乐玩家":  ("VPIP 60% 以上，几乎来者不拒", "喜欢看翻牌，不关心位置，很少 3bet"),
    "受气包":   ("跟注为主，几乎不主动下注、不加注", "你怎么打他都只是跟或弃，永远不会反过来压你"),
    "过度诈唬型": ("翻前还行，翻后突然变凶：频繁下注、加注、超池", "河牌爱施压，抓他几次会发现他亮的是空气"),
    "下注不足型": ("翻前正常，翻后下注频率明显偏低、尺度偏小", "强牌爱过牌慢玩，等不到他主动做大底池"),
}
for _t in TYPES:
    if "identify" not in _t:
        _t["identify"] = IDENTIFY.get(_t["id"], ("", ""))


# ══ 尺度调整：面对不同对手，同样的节点该用多大 ═══════════════
# 键：对手类型；值：(乘数, 说明)
SIZING_ADJUST = {
    "标准":       (1.0,  "按基线尺度"),
    "紧凶":       (0.95, "他很少跟大注 → 尺度别拉太满，多打薄价值"),
    "岩石":       (0.9,  "他弃牌多 → 小注偷更多，大注只在有牌时"),
    "松凶":       (1.0,  "他会反制 → 尺度保持标准，别过大被加注"),
    "跟注站":     (1.4,  "他什么牌都跟 → 价值尺度加大，少诈唬"),
    "娱乐玩家":   (1.45, "他爱跟不弃 → 尺度拉满榨价值"),
    "受气包":     (1.2,  "他被动 → 大一点拿价值，他不太会弃"),
    "过度诈唬型":  (1.1,  "他诈唬多 → 给他空间，尺度别逼走他的诈唬"),
    "下注不足型":  (1.15, "他不主动下注 → 自己打大一点"),
}


# ══ 4bet 范围（极紧，纯价值 + 少量阻断牌诈唬）═══════════════
# 结构：价值牌（QQ+/AK）+ 诈唬牌（A5s-A2s，用来阻断对手 AA/AK）
FOURBET_RANGE = {
    "标准":   "QQ+, AKs, AKo, A5s, A4s",
    "紧凶":   "QQ+, AKs, AKo",
    "松凶":   "TT+, AQs+, AKo, A5s, A4s, KQs",
    "岩石":   "KK+, AKs",
    "跟注站": "AA, KK",
    "娱乐玩家": "AA, KK, AKs",
    "受气包": "AA, KK",
    "过度诈唬型": "QQ+, AKs, AKo, A5s, A4s, K9s",
    "下注不足型": "QQ+, AKs, AKo",
}

# 我 4bet 之后，对手如果跟注，我的翻后范围就是 4bet 那部分
# 我面对 3bet 选择跟注时，翻后范围就是 CALL_3BET_RANGE


# ══ 跟注 4bet 范围（比 4bet 宽，但也极紧）═══════════════════
CALL_4BET_RANGE = {
    "标准":   "TT+, AQs+, AKo, KQs",
    "紧凶":   "JJ+, AQs+, AKo",
    "松凶":   "99+, AQs+, AKo, KQs, A5s",
    "岩石":   "QQ+, AKs, AKo",
    "跟注站": "99+, AJs+, AQo+",
    "娱乐玩家": "88+, ATs+, AQo+",
    "受气包": "QQ+, AKs",
    "过度诈唬型": "TT+, AQs+, AKo, KQs, A5s, A4s",
    "下注不足型": "JJ+, AQs+, AKo",
}

# ══ 5bet 全下范围（几乎只有坚果级）═════════════════════════
FIVEBET_RANGE = {
    "标准":   "QQ+, AKs, AKo",
    "紧凶":   "QQ+, AKs, AKo",
    "松凶":   "JJ+, AKs, AKo, A5s",
    "岩石":   "KK+, AA, AKs",
    "跟注站": "AA, KK",
    "娱乐玩家": "AA, KK, AKs",
    "受气包": "AA, KK",
    "过度诈唬型": "JJ+, AKs, AKo, A5s, A4s",
    "下注不足型": "QQ+, AKs, AKo",
}


# ══ 3bet 范围按「谁开的池」区分 ═══════════════════════════════
# 开池位置越靠前，他的范围越强 → 你 3bet 必须越紧。
THREEBET_VS_OPENER = {
    # 对手开池位置: (价值范围, 诈唬范围, 参考频率)
    "UTG":  ("QQ+, AKs, AKo",              "A5s, A4s",          3.0),
    "UTG1": ("JJ+, AKs, AKo",              "A5s",               4.0),
    "UTG2": ("TT+, AQs+, AKo",             "A5s",               5.0),
    "HJ":   ("99+, AJs+, KQs, AQo+",       "A5s, K9s",          6.5),
    "CO":   ("99+, ATs+, KQs, AJo+",       "A5s, A4s, K9s",     8.0),
    "BTN":  ("88+, ATs+, KJs+, ATo+",      "A5s, A4s, K9s",     10.0),
    "SB":   ("88+, ATs+, KQs, AJo+",       "A5s",               9.0),
    "BB":   ("77+, A9s+, KTs+, QJs, ATo+", "A5s, A4s, K9s",     12.0),
}

# 3bet 方位置修正：OOP 略收紧，盲位略放宽
THREEBET_POS_FACTOR = {
    "UTG": 0.8, "UTG1": 0.85, "UTG2": 0.9, "HJ": 0.95,
    "CO": 1.0, "BTN": 1.0, "SB": 1.05, "BB": 1.1,
}
