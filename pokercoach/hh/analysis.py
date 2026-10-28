"""手牌统计与漏洞识别。

思路：先把每手牌压成一组"有没有发生"的标记（VPIP/PFR/3bet/cbet…），
再按位置和样本量聚合，和微级别的合理区间比对，找出偏离最大的几项。

基准区间是经验值（NL2-NL5 六人桌、池子偏松），只用来定位问题，不是判分标准。
"""

from __future__ import annotations

from collections import Counter, defaultdict

from ..cards import RANKS
from .gg import Hand
from .spots import hero_spots

# 微级别六人桌的经验区间：低于/高于都算偏离
BENCHMARKS: dict[str, dict] = {
    # lo~hi = 正常区间；wlo/whi = 「很低 / 很高」的临界。中间是「偏低 / 偏高」。
    "vpip":       {"label": "VPIP（主动入池率）", "lo": 22, "hi": 27, "wlo": 18, "whi": 32, "min_n": 200, "topic": "翻前基础"},
    "pfr":        {"label": "PFR（翻前加注率）",  "lo": 18, "hi": 23, "wlo": 14, "whi": 27, "min_n": 200, "topic": "翻前基础"},
    "three_bet":  {"label": "3bet 频率",          "lo": 9,  "hi": 11, "wlo": 7,  "whi": 13, "min_n": 120, "topic": "3bet 与 4bet"},
    "fold_to_3bet": {"label": "面对 3bet 的弃牌率", "lo": 45, "hi": 55, "wlo": 38, "whi": 62, "min_n": 80,  "topic": "3bet 与 4bet"},
    "cbet_flop":  {"label": "翻牌持续下注率",      "lo": 60, "hi": 72, "wlo": 50, "whi": 80, "min_n": 150, "topic": "翻牌持续下注"},
    "cbet_turn":  {"label": "转牌持续下注率",      "lo": 45, "hi": 58, "wlo": 38, "whi": 66, "min_n": 120, "topic": "转牌与双枪"},
    "cbet_river": {"label": "河牌下注率",          "lo": 35, "hi": 50, "wlo": 25, "whi": 58, "min_n": 100, "topic": "河牌与抓诈唬"},
    "fold_to_cbet": {"label": "面对持续下注的弃牌率", "lo": 40, "hi": 50, "wlo": 32, "whi": 56, "min_n": 120, "topic": "翻牌持续下注"},
    "wtsd":       {"label": "摊牌率 WTSD",         "lo": 26, "hi": 32, "wlo": 22, "whi": 36, "min_n": 100, "topic": "河牌与抓诈唬"},
    "wsd":        {"label": "摊牌胜率 W$SD",       "lo": 50, "hi": 56, "wlo": 45, "whi": 62, "min_n": 60,  "topic": "河牌与抓诈唬"},
}


def band(value: float, b: dict) -> str:
    """五档判定：很低 / 偏低 / 正常 / 偏高 / 很高"""
    lo, hi, wlo, whi = b["lo"], b["hi"], b.get("wlo", b["lo"] - 1), b.get("whi", b["hi"] + 1)
    if value < wlo:
        return "很低"
    if value < lo:
        return "偏低"
    if value <= hi:
        return "正常"
    if value <= whi:
        return "偏高"
    return "很高"

_RFI_BANDS = {"UTG": (14, 22), "HJ": (16, 25), "CO": (22, 33), "BTN": (36, 52), "SB": (28, 55)}
_RFI_ADVICE = {
    "SB": "SB 开池太少，通常是在大量 limp 或者直接弃牌。SB 要么加注、要么 limp-raise，别平跟进池。",
    "BTN": "BTN 开池太窄，按钮位是这个游戏最赚钱的位置，宽度可以再放宽 5~10 个点。",
    "CO": "CO 开池偏窄，CO 的宽度应该接近 BTN 的 2/3。",
    "HJ": "HJ 偏紧，中位可以多开一些同花连张和 A 高。",
    "UTG": "UTG 偏紧或偏松，检查是不是把边缘牌带进了前位。",
}


def hand_class(cards: list[str]) -> str:
    """['Th','Kh'] -> 'KTs'；对子 -> 'TT'。"""
    if len(cards) != 2:
        return "?"
    ranks = [c[0].upper() for c in cards]
    suits = [c[-1].lower() for c in cards]
    i, j = sorted((RANKS.index(ranks[0]), RANKS.index(ranks[1])), reverse=True)
    if i == j:
        return RANKS[i] * 2
    return f"{RANKS[i]}{RANKS[j]}{'s' if suits[0] == suits[1] else 'o'}"


def hero_flags(h: Hand) -> dict:
    """把一手牌压成标记。每个比率都配一个"机会"标记，避免拿总手数当分母。"""
    hero = h.hero
    pos = h.seats.get(hero, {}).get("pos", "?")

    pre = [a for a in h.actions if a.street == "preflop" and a.kind != "post"]
    flop = [a for a in h.actions if a.street == "flop"]
    turn = [a for a in h.actions if a.street == "turn"]
    river = [a for a in h.actions if a.street == "river"]
    hero_pre = [a for a in pre if a.player == hero]
    folded_pre = any(a.kind == "folds" for a in hero_pre)

    # 英雄的第一次自愿动作之前，已经有人加注了几次
    raises_before = 0
    hero_first = None
    for a in pre:
        if a.player == hero and a.kind in ("folds", "calls", "bets", "raises"):
            hero_first = a
            break
        if a.kind == "raises":
            raises_before += 1

    # 全下的情况也算看过翻牌
    allin_pre = any(a.kind in ("raises", "is all-in") and a.to > 0 for a in hero_pre) and not flop
    saw_flop = (not folded_pre) and (bool(flop) or allin_pre)

    vpip = hero_first is not None and hero_first.kind in ("calls", "bets", "raises")
    pfr = hero_first is not None and hero_first.kind == "raises"
    opened = pfr and raises_before == 0 and pos != "BB"

    three_bet_opp = raises_before == 1
    three_bet = three_bet_opp and pfr
    # 第一个进池却只跟注 = limp
    limp = hero_first is not None and hero_first.kind == "calls" and raises_before == 0 and pos != "BB"
    # 前面没人加注，才轮到"开池"这个动作
    first_in = raises_before == 0 and pos != "BB"

    # 开池后是否被 3bet、以及面对 3bet 的动作
    faced_3bet = False
    fold_to_3bet = False
    if opened:
        for i, a in enumerate(pre):
            if a.player == hero and a.kind == "raises":
                later = pre[i + 1 :]
                if any(x.kind == "raises" for x in later):
                    faced_3bet = True
                    nxt = next((x for x in later if x.player == hero), None)
                    fold_to_3bet = nxt is not None and nxt.kind == "folds"
                break

    all_raises = [a for a in pre if a.kind == "raises"]
    pfa = all_raises[-1].player if all_raises else None
    is_pfa = pfa == hero

    def first_bet(seg):
        return next((a for a in seg if a.kind in ("bets", "raises")), None)

    def hero_folded(seg):
        return any(a.player == hero and a.kind == "folds" for a in seg)

    cbet_flop = cbet_flop_opp = False
    faced_cbet = faced_cbet_opp = fold_to_cbet = False
    if saw_flop and flop:
        fb = first_bet(flop)
        hero_idx = next((i for i, a in enumerate(flop) if a.player == hero), None)
        if is_pfa:
            if fb is None and hero_idx is not None:
                cbet_flop_opp = True
                cbet_flop = any(a.player == hero and a.kind in ("bets", "raises") for a in flop)
            elif fb is not None and fb.player == hero:
                cbet_flop_opp = True
                cbet_flop = True
        elif fb is not None and fb.player == pfa and hero_idx is not None and hero_idx > flop.index(fb):
            faced_cbet_opp = True
            faced_cbet = True
            fold_to_cbet = flop[hero_idx].kind == "folds"

    def barrel(seg, prev_ok):
        if not prev_ok or not seg:
            return False, False
        fb = first_bet(seg)
        hero_acts = [a for a in seg if a.player == hero]
        if not hero_acts:
            return False, False
        opp = fb is None or fb.player == hero
        return opp, any(a.kind in ("bets", "raises") for a in hero_acts)

    cbet_turn_opp, cbet_turn = barrel(turn, cbet_flop)
    cbet_river_opp, cbet_river = barrel(river, cbet_turn)

    reached_showdown = saw_flop and bool(h.shown) and not any(
        hero_folded(seg) for seg in (flop, turn, river)
    )
    wsd = reached_showdown and h.collected.get(hero, 0) > 0

    return {
        "pos": pos,
        "hand": hand_class(h.hero_cards),
        "vpip": vpip,
        "pfr": pfr,
        "opened": opened,
        "three_bet": three_bet,
        "three_bet_opp": three_bet_opp,
        "limp": limp,
        "first_in": first_in,
        "faced_3bet": faced_3bet,
        "fold_to_3bet": fold_to_3bet,
        "saw_flop": saw_flop,
        "cbet_flop": cbet_flop,
        "cbet_flop_opp": cbet_flop_opp,
        "faced_cbet_opp": faced_cbet_opp,
        "fold_to_cbet": fold_to_cbet,
        "cbet_turn": cbet_turn,
        "cbet_turn_opp": cbet_turn_opp,
        "cbet_river": cbet_river,
        "cbet_river_opp": cbet_river_opp,
        "wtsd": reached_showdown,
        "wsd": wsd,
        "board": h.board,
        "spots": hero_spots(h),
        "net": round(h.hero_net(), 4),
        "bb": h.bb,
    }


def _pct(a: int, b: int) -> float | None:
    return round(a / b * 100, 1) if b else None


def aggregate(flags: list[dict]) -> dict:
    n = len(flags)
    if not n:
        return {"hands": 0}

    def count(key: str, denom: str | None = None) -> tuple[int, int]:
        num = sum(1 for f in flags if f.get(key))
        den = sum(1 for f in flags if f.get(denom)) if denom else n
        return num, den

    vpip = count("vpip")
    pfr = count("pfr")
    tb = count("three_bet", "three_bet_opp")
    f3 = count("fold_to_3bet", "faced_3bet")
    cf = count("cbet_flop", "cbet_flop_opp")
    ct = count("cbet_turn", "cbet_turn_opp")
    cr = count("cbet_river", "cbet_river_opp")
    fc = count("fold_to_cbet", "faced_cbet_opp")
    wtsd = count("wtsd", "saw_flop")
    wsd = count("wsd", "wtsd")
    limp = count("limp")

    # BB/100：按每个 bb 归一，避免不同级别混算
    bb_net = sum(f["net"] / f["bb"] for f in flags if f["bb"])
    winrate = round(bb_net / n * 100, 1)

    by_pos = defaultdict(list)
    for f in flags:
        by_pos[f["pos"]].append(f)

    # 开池率的分母只能是"前面没人加注"的手数，否则会被别人先开池的牌稀释
    rfi = {}
    for pos, group in by_pos.items():
        first_in = [f for f in group if f.get("first_in", True)]
        opened = sum(1 for f in first_in if f["opened"])
        if len(first_in) >= 30:
            rfi[pos] = {"pct": _pct(opened, len(first_in)), "n": len(first_in)}

    return {
        "hands": n,
        "winrate_bb100": winrate,
        "totals": {
            "vpip": _pct(*vpip),
            "pfr": _pct(*pfr),
            "three_bet": _pct(*tb),
            "fold_to_3bet": _pct(*f3),
            "cbet_flop": _pct(*cf),
            "cbet_turn": _pct(*ct),
            "cbet_river": _pct(*cr),
            "fold_to_cbet": _pct(*fc),
            "wtsd": _pct(*wtsd),
            "wsd": _pct(*wsd),
            "limp": _pct(*limp),
        },
        "samples": {
            "hands": n,
            "vpip": vpip[1],
            "three_bet": tb[1],
            "fold_to_3bet": f3[1],
            "cbet_flop": cf[1],
            "cbet_turn": ct[1],
            "cbet_river": cr[1],
            "fold_to_cbet": fc[1],
            "wtsd": wtsd[1],
            "wsd": wsd[1],
            "limp": n,
        },
        "rfi": rfi,
    }


def find_leaks(agg: dict) -> list[dict]:
    """和基准区间比，挑出偏离最大的几项。"""
    leaks = []
    for key, band in BENCHMARKS.items():
        val = agg["totals"].get(key)
        n = agg["samples"].get(key, 0)
        if val is None or n < band["min_n"]:
            continue
        lo, hi = band["lo"], band["hi"]
        if lo <= val <= hi:
            continue
        # 偏离程度：超出区间多少（按区间宽度归一）
        width = max(hi - lo, 1)
        dev = (lo - val) if val < lo else (val - hi)
        severity = abs(dev) / width
        direction = "偏低" if val < lo else "偏高"
        leaks.append(
            {
                "id": key,
                "label": band["label"],
                "value": val,
                "target": f"{lo}~{hi}",
                "direction": direction,
                "samples": n,
                "severity": round(severity, 2),
                "topic": band["topic"],
                "advice": _ADVICE.get((key, direction), ""),
            }
        )
    # 位置开池
    for pos, v in (agg.get("rfi") or {}).items():
        band = _RFI_BANDS.get(pos)
        if not band or v["pct"] is None or v["n"] < 150:
            continue
        lo, hi = band
        if lo <= v["pct"] <= hi:
            continue
        width = max(hi - lo, 1)
        dev = (lo - v["pct"]) if v["pct"] < lo else (v["pct"] - hi)
        leaks.append(
            {
                "id": f"rfi_{pos}",
                "label": f"{pos} 开池率",
                "value": v["pct"],
                "target": f"{lo}~{hi}",
                "direction": "偏低" if v["pct"] < lo else "偏高",
                "samples": v["n"],
                "severity": round(abs(dev) / width, 2),
                "topic": "翻前基础",
                "advice": _RFI_ADVICE.get(pos, ""),
            }
        )

    # limp：第一个进池却只跟注
    limp = agg["totals"].get("limp")
    if limp is not None and agg["hands"] >= 500 and limp > 4:
        leaks.append(
            {
                "id": "limp",
                "label": "翻前平跟（limp）比例",
                "value": limp,
                "target": "0~4",
                "direction": "偏高",
                "samples": agg["hands"],
                "severity": round((limp - 4) / 4, 2),
                "topic": "翻前基础",
                "advice": "平跟进池既没有主动权也没有弃牌率。要么加注，要么弃牌；SB 可以用 limp-raise 代替平跟。",
            }
        )

    leaks.sort(key=lambda x: (x["severity"], x["samples"]), reverse=True)
    return leaks


_ADVICE = {
    ("vpip", "偏高"): "入池太宽，尤其在前位。先把 UTG/HJ 的范围砍到只留能承受 3bet 的牌。",
    ("vpip", "偏低"): "太紧会被盲注位随便偷。检查 BTN/CO 是否漏掉了该开池的牌。",
    ("pfr", "偏低"): "跟注太多、加注太少。跟注进池既没主动性也没弃牌率。",
    ("three_bet", "偏低"): "3bet 太少，对手的跟注就免费实现权益。先补上 A5s-A2s、K9s 这类阻断牌诈唬。",
    ("three_bet", "偏高"): "3bet 过频会被 4bet 反制。检查是不是把 KQo、AJo 这类被压制的牌也放进去了。",
    ("fold_to_3bet", "偏高"): "开池后被 3bet 弃太多，对手可以无脑 3bet 剥削你。补上有位置的同花连张和小对子。",
    ("cbet_flop", "偏低"): "翻牌放弃太多。范围优势在干燥面（A 高、K 高）要整体下注，哪怕是小尺度。",
    ("cbet_flop", "偏高"): "每手都 cbet 会被 check-raise 打穿。连牌面和双花面要降低频率。",
    ("cbet_turn", "偏低"): "转牌收手太快，对手跟一枪就能看免费河牌。补上真实听牌和部分后门牌的二次下注。",
    ("cbet_river", "偏低"): "河牌不敢打价值。很多薄价值（顶对好踢、两对）在你这里是漏掉的。",
    ("fold_to_cbet", "偏高"): "面对 cbet 弃太多，尤其在大盲。MDF 之外还要看对手的诈唬比例。",
    ("fold_to_cbet", "偏低"): "跟注太宽，转牌会很难受。检查是不是在用无后门的空气牌硬跟。",
    ("wtsd", "偏高"): "摊牌太多，说明你在用中等强度硬扛到底。河牌该弃的要弃。",
    ("wtsd", "偏低"): "摊牌太少，可能过度弃牌，被对手的价值下注打穿。",
    ("wsd", "偏低"): "摊牌总输，说明进摊牌的范围偏弱——要么跟太松，要么河牌没弃掉该弃的。",
    ("wsd", "偏高"): "摊牌总赢，说明你可能放弃了太多边缘摊牌，或者价值下注不够。",
}


def analyze(flags: list[dict]) -> dict:
    agg = aggregate(flags)
    leaks = find_leaks(agg) if agg.get("hands") else []
    return {
        "agg": agg,
        "leaks": leaks,
        "priority_topics": list(dict.fromkeys(x["topic"] for x in leaks[:4])),
    }


def render_report(result: dict) -> str:
    agg = result["agg"]
    if not agg.get("hands"):
        return "没有手牌数据。先运行 python run.py hh data/hh/raw"
    t = agg["totals"]
    lines = [
        f"手数 {agg['hands']:,} · 胜率 {agg['winrate_bb100']:+.1f} bb/100",
        "",
        "核心指标（括号里是样本数）",
        f"  VPIP {t['vpip']}% ({agg['samples']['vpip']:,})   PFR {t['pfr']}%   "
        f"3bet {t['three_bet']}% ({agg['samples']['three_bet']:,})   "
        f"弃给3bet {t['fold_to_3bet']}% ({agg['samples']['fold_to_3bet']:,})",
        f"  Cbet F {t['cbet_flop']}% ({agg['samples']['cbet_flop']:,})   "
        f"T {t['cbet_turn']}%   R {t['cbet_river']}%   "
        f"弃给cbet {t['fold_to_cbet']}%",
        f"  WTSD {t['wtsd']}%   W$SD {t['wsd']}%",
    ]
    if agg.get("rfi"):
        lines.append("")
        lines.append("各位置开池率")
        for pos, v in agg["rfi"].items():
            lines.append(f"  {pos:4s} {v['pct']:5.1f}%  (n={v['n']})")
    lines.append("")
    if not result["leaks"]:
        lines.append("没有明显偏离基准的指标。样本再大一点再看。")
    else:
        lines.append("主要漏洞（按偏离程度排序）")
        for i, l in enumerate(result["leaks"][:6], 1):
            lines.append(
                f"  {i}. {l['label']}：{l['value']}%（基准 {l['target']}，{l['direction']}，n={l['samples']}）"
            )
        lines.append("")
        for l in result["leaks"][:3]:
            lines.append(f"  → {l['label']}：{l['advice']}")
    return "\n".join(lines)
