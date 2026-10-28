"""策略树：把 rules.csv / buckets.csv 渲染成 13×13 手牌矩阵。

三件事：
1. parse_board   "A72r" → 三张牌（含花色）
2. classify      底牌 + 牌面 → 手牌类别（顶对好踢 / 听牌 / 纯空气 …）
3. grid          节点 → 每个组合的类别与桶
"""
from __future__ import annotations
import csv
import json, itertools
from collections import Counter
from pathlib import Path

RANKS = "23456789TJQKA"
SUITS = "shdc"
SUIT_CN = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

def rc(ch: str) -> int:
    return RANKS.index(ch.upper()) + 2

# ---------------- 牌面解析 ----------------
def parse_board(text: str):
    """支持 A72r / A72tt / A72m / Ah7d2c。返回 ([(rank,suit)...], pattern)"""
    t = text.strip().replace("-", "").replace(" ", "")
    style = ""
    for suf in ("tt", "r", "m"):
        if t.lower().endswith(suf):
            style, t = suf, t[: -len(suf)]
            break
    if len(t) in (6, 8, 10) and t[1] in SUITS:  # 显式花色：3/4/5 张
        cards = [(rc(t[i]), SUITS.index(t[i + 1])) for i in range(0, len(t), 2)]
        n = len({c[1] for c in cards})
        style = {3: "r", 2: "tt", 1: "m"}.get(n, "r")
        return cards, style
    if len(t) != 3:
        raise ValueError("牌面写法不对，例：A72r / KQ9tt / T94m")
    ranks = [rc(c) for c in t]
    style = style or "r"
    if style == "m":
        suits = [0, 0, 0]
    elif style == "tt":
        suits = [0, 0, 1]
    else:
        suits = [0, 1, 2]
    # 让最大牌用 ♠，好看且稳定
    order = sorted(range(3), key=lambda i: -ranks[i])
    out = [None, None, None]
    for k, i in enumerate(order):
        out[i] = (ranks[i], suits[k])
    return out, style

# ---------------- 手牌类别 ----------------
def _straight_outs(ranks):
    """有几张牌能让顺子完成（粗略，够分类用）"""
    s = set(ranks)
    if 14 in s:
        s.add(1)  # A 当 1
    outs = 0
    for lo in range(1, 11):
        window = set(range(lo, lo + 5))
        if len(window & s) == 4:
            outs += 1
    return outs

def classify(board, hole) -> str:
    br = [c[0] for c in board]
    hr = [c[0] for c in hole]
    bs = [c[1] for c in board]
    hs = [c[1] for c in hole]
    allr = br + hr
    cnt = Counter(allr)
    scnt = Counter(bs + hs)
    top3 = sorted(br, reverse=True)[:3]
    while len(top3) < 3:
        top3.append(0)
    bmax, bmid, bmin = top3
    pocket = hr[0] == hr[1]

    flush_draw = any(v == 4 for v in scnt.values()) and any(scnt[s] >= 1 for s in hs)
    has_flush = any(v >= 5 for v in scnt.values())
    straight = _straight_outs(allr) >= 1 and _made_straight(allr)

    counts = sorted(cnt.values(), reverse=True)
    if counts[0] >= 4 or (counts[0] == 3 and counts[1] >= 2) or has_flush or straight:
        return "两对+"

    trips_rank = [r for r, v in cnt.items() if v == 3]
    if trips_rank:
        # 手上有对子且与公共牌成三条 = 暗三条；手上单张撞对子 = 三条
        return "暗三条"
    pairs = [r for r, v in cnt.items() if v >= 2]
    if len(pairs) >= 2:
        return "两对+"

    if pocket:
        if hr[0] > bmax:
            return "超对"
        if hr[0] == bmax:
            return "顶对好踢"   # 顶三条级别，桶表按顶对处理
        if hr[0] in br:
            return "暗三条"
        if hr[0] < bmin:
            return "小口袋对"
        return "小口袋对"

    # 手上一张与公共牌成对
    pair_rank = None
    for h in hr:
        if h in br:
            pair_rank = h
            break
    if pair_rank is not None:
        kicker = hr[1] if hr[0] == pair_rank else hr[0]
        if pair_rank == bmax:
            return "顶对好踢" if kicker > bmid else "顶对弱踢"
        if pair_rank == bmid:
            return "中对"
        return "底对"

    # 没有对子：先看听牌
    if flush_draw or _straight_outs(allr) >= 2:
        return "听牌"
    if _straight_outs(allr) == 1:
        return "听牌"
    backdoor_flush = any(scnt[s] == 3 for s in hs)
    backdoor_straight = _straight_outs(allr) == 0 and _backdoor_straight(allr, hr)
    if backdoor_flush or backdoor_straight:
        return "后门空气"
    if 14 in hr:
        kicker = hr[0] if hr[1] == 14 else hr[1]
        if kicker >= 10:
            return "A大"
        if kicker >= 7:
            return "A中"
        return "A小"
    return "纯空气"

def _made_straight(ranks):
    s = set(ranks)
    if 14 in s:
        s.add(1)
    for lo in range(1, 11):
        if set(range(lo, lo + 5)) <= s:
            return True
    return False

def _backdoor_straight(allranks, hole_ranks):
    s = set(allranks)
    if 14 in s:
        s.add(1)
    h = set(hole_ranks) | ({1} if 14 in hole_ranks else set())
    for lo in range(1, 11):
        win = set(range(lo, lo + 5))
        hit = win & s
        if len(hit) >= 3 and len(hit & h) >= 2:
            return True
    return False

# ---------------- 13×13 组合 ----------------
def combos():
    """169 个组合，返回 [(combo_id, ((rank,suit),(rank,suit)))]"""
    out = []
    for i in range(12, -1, -1):
        for j in range(12, -1, -1):
            hi, lo = max(i, j), min(i, j)
            if i == j:
                out.append((RANKS[i] * 2, ((i + 2, 0), (i + 2, 1))))
            elif i > j:
                out.append((RANKS[i] + RANKS[j] + "s", ((i + 2, 0), (j + 2, 0))))
            else:
                # i < j：i 是小牌，非同花也要「大牌在前」，跟同花统一
                out.append((RANKS[j] + RANKS[i] + "o", ((i + 2, 0), (j + 2, 1))))
    return out

# ---------------- 牌面归类 ----------------
def board_class(cards, pattern) -> str:
    r = sorted([c[0] for c in cards], reverse=True)
    # 河牌/转牌只按「最高的三张」归类，保持与翻牌同一套标签
    hi, mid, lo = (r + [0, 0, 0])[:3]
    paired = hi == mid or mid == lo
    if paired:
        top = "高" if hi >= 13 else ("中" if hi >= 10 else "低")
        return f"{top}-公对"
    top = "高" if hi >= 13 else ("中" if hi >= 10 else "低")
    span = hi - lo
    if span <= 4:
        conn = "连"
    elif span <= 6:
        conn = "半连"
    else:
        conn = "断"
    suit = {"m": "天花", "tt": "两色", "r": "彩"}[pattern]
    if hi == 14 and mid <= 5 and lo <= 4:
        return "轮子"
    if hi == 14 and lo <= 9 and mid <= 9:
        return f"高A-低-{suit}"
    if hi == 14 and mid >= 10:
        return f"高A-高-{suit}"
    if hi == 13 and conn == "断":
        return f"高K-{suit}"
    if hi == 5 and mid == 4 and lo == 3:
        return "轮子"
    return f"{top}-{conn}-{suit}"

# ---------------- 规则查询 ----------------
WILD = {"*", "", "-"}
FIELDS = ("pot_type", "role", "board_class", "street", "node_action", "line", "path",
          "runout", "capped", "vs_type", "hero_pos", "opp_pos", "stack",
          "hero_stack", "villain_stack")

_LOAD_CACHE: dict = {}


def _load(root: Path):
    """带缓存：按 (路径, mtime) 判断是否需要重读。原来每次 grid 都重读 CSV，慢到 70 秒。"""
    rp, bp = root / "rules.csv", root / "buckets.csv"
    try:
        stamp = (rp.stat().st_mtime, bp.stat().st_mtime)
    except OSError:
        stamp = (0, 0)
    hit = _LOAD_CACHE.get(str(root))
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    rules = list(csv.DictReader(open(rp, encoding="utf-8")))
    buckets = list(csv.DictReader(open(bp, encoding="utf-8")))
    _LOAD_CACHE[str(root)] = (stamp, rules, buckets)
    return rules, buckets

def apply_tendency(cells, node_action, vs_type):
    """轴二：按对手翻后倾向，直接改桶表数值。

    过度诈唬型：抓诈↑、薄价值↑、诈唬↓
    下注不足型：抓诈↓、薄价值↓、诈唬↑
    """
    if not vs_type or vs_type in ("*", "任意"):
        return cells, None
    try:
        from .playertypes import TENDENCY_ADJUST
    except Exception:
        return cells, None
    adj = TENDENCY_ADJUST.get(vs_type)
    if not adj:
        return cells, None

    # 判断这是「防守表」（对手下注/加注）还是「进攻表」
    defending = any(k in node_action for k in ("小注", "中注", "大注", "加注", "3bet", "4bet"))
    out = []
    for c in cells:
        if c.get("bucket") is None:
            out.append(c); continue
        v = c["bucket"]
        hc = c.get("cat") or c.get("matched") or ""
        delta = 0.0
        if defending:
            # 抓诈类：中/弱对、A 大
            if hc in ("中对", "底对", "顶对弱踢", "A大"):
                delta = adj["bluff_catch"]
        else:
            # 进攻端：空气看诈唬，薄价值看 value_thin
            if hc in ("纯空气", "后门空气"):
                delta = adj["bluff"]
            elif hc in ("顶对弱踢", "中对"):
                delta = adj["value_thin"]
        if delta:
            c = dict(c)
            c["bucket"] = max(0, min(100, round(v * (1 + delta))))
            c["adjusted"] = f"{v} → {c['bucket']}"
        out.append(c)
    return out, adj["note"]


def find_rule(rules, q):
    best, top = [], -1
    rules = [x for x in rules if x.get("status") != "retired"]
    for r in rules:
        s = 0
        ok = True
        be = (r.get("board_exact") or "").strip()
        if be and be.lower() != (q.get("_board") or "").strip().lower():
            continue
        extra = 3 if be else 0     # 指定精确牌面的规则，特异度远高于「牌面类别」
        # 指定了具体筹码深度 / 位置的规则，必须压过通配规则
        for f in ("stack", "hero_stack", "villain_stack", "hero_pos", "opp_pos"):
            rv = (r.get(f) or "*").strip()
            qv = (q.get(f) or "*").strip()
            if rv not in WILD and qv not in WILD and rv == qv:
                extra += 2
        rp = (r.get("path") or "").strip()
        qp = (q.get("path") or "").strip()
        if rp and qp:                      # 只在查询给了路径时强制前缀匹配
            if not qp.upper().startswith(rp.upper()):
                continue
            extra += max(1, len(rp) // 3)  # 路径越长越具体，加分越多
        vt = (r.get("vs_type") or "*").strip()
        qvt = (q.get("vs_type") or "*").strip()
        # 只有查询真的指定了对手类型，剥削规则才优先——否则通用规则应当胜出
        if vt not in WILD and qvt not in WILD:
            extra += 1
        for f in FIELDS:
            v = (r.get(f) or "*").strip()
            qv = (q.get(f) or "*").strip()
            if v in WILD or qv in WILD:
                continue
            if v != qv:
                ok = False
                break
            s += 1
        if not ok:
            continue
        s += extra
        if s > top:
            top, best = s, [r]
        elif s == top:
            best.append(r)

    # 同分时按来源可靠度排序：课程 > 求解 > 蓝图 > 推导
    RANK = {"课程": 5, "课程+蓝图": 5, "求解": 6, "蓝图": 4,
            "Upswing": 4, "Smash": 4, "红线蓝图": 4, "Overbankroll": 4, "推导": 1}
    best.sort(key=lambda x: -RANK.get(x.get("source"), 0))
    return best

SYNONYM = {
    "暗三条": ["暗三条", "两对+", "其他"],
    "后门空气": ["后门空气", "纯空气", "其他"],
    "A大": ["A大", "A嗨", "纯空气", "其他"],
    "A中": ["A中", "A小", "纯空气", "其他"],
    "A小": ["A小", "A中", "纯空气", "其他"],
}

def bucket_of_exact(hand: str, table_id: str, buckets):
    """按手牌名（AA / AKs / AKo）精确取桶；没有就回退到「其他」。"""
    for b in buckets:
        if b["table_id"] == table_id and b["hand_class"] == hand:
            return int(b["bucket"]), b["hand_class"]
    for b in buckets:
        if b["table_id"] == table_id and b["hand_class"] == "其他":
            return int(b["bucket"]), "其他"
    return None, None


def bucket_of(cat, table_id, buckets):
    rows = [b for b in buckets if b["table_id"] == table_id]
    for name in [cat] + SYNONYM.get(cat, []):
        for b in rows:
            if b["hand_class"] == name:
                return int(b["bucket"]), b["hand_class"]
    for b in rows:
        if b["hand_class"] == "其他":
            return int(b["bucket"]), "其他"
    return None, None


_RANGE_CACHE: dict = {}


def _preflop_range(hero_pos: str, opp_pos: str):
    """取我方在该位置的翻前范围；取不到就返回 None（不做过滤）。"""
    from .preflop import get as _get
    key = (hero_pos, opp_pos or "*")
    if key in _RANGE_CACHE:
        return _RANGE_CACHE[key]
    try:
        spec = _get(hero_pos, opp_pos if opp_pos not in ("*", "", None) else "BB")
        from .ranges import parse_range
        out = {(c[0], c[1]) for c in parse_range(spec)}
    except Exception:
        out = None
    _RANGE_CACHE[key] = out
    return out


def _hand_in_range(cid: str, in_range) -> bool:
    """cid 如 'AA' / 'AKs' / 'AKo'；组合编码是 card = rank*4 + suit。"""
    if not cid or len(cid) < 2:
        return True
    ra = RANKS.find(cid[0])
    rb = RANKS.find(cid[1])
    if ra < 0 or rb < 0:
        return True
    if len(cid) == 2:                      # 口袋对
        return any((ra * 4 + i, ra * 4 + j) in in_range
                   for i in range(4) for j in range(4) if i != j)
    suited = cid.endswith("s")
    for i in range(4):
        for j in range(4):
            if suited and i != j:
                continue
            if not suited and i == j:
                continue
            if (ra * 4 + i, rb * 4 + j) in in_range:
                return True
            if (rb * 4 + i, ra * 4 + j) in in_range:
                return True
    return False



# ══ 动作混合：solver 风格的显示需要「这个动作 + 剩下的部分」 ══
PASSIVE_OF = {
    "对手过牌": "过牌", "我方领打": "过牌", "我方领打（小注）": "过牌",
    "对手小注": "弃牌", "对手中注": "弃牌", "对手大注": "弃牌", "对手下注": "弃牌",
    "对手开池": "弃牌", "开池": "弃牌", "对手3bet": "弃牌", "对手4bet": "弃牌",
    "对手加注": "弃牌", "对手过牌加注": "弃牌", "无": "过牌",
}
# 动作 → 颜色（前端用）
ACTION_COLORS = {
    "下注": "#e07b39", "加注": "#c0392b", "3bet": "#c0392b", "开池": "#e07b39",
    "领打": "#d9822b", "跟注": "#2e86c1", "过牌": "#6b7d8f", "弃牌": "#41535f",
}


def action_mix(bucket, unit, node_action, sizing) -> list:
    """把「单一动作频率」展开成动作混合（主动作 + 互补动作）。"""
    if bucket is None:
        return []
    main = (unit or "下注率").replace("率", "")
    size = (sizing or "").strip()
    label = f"{main} {size}" if size and size not in ("*", "—") else main
    out = [{"action": label, "kind": main, "freq": int(bucket),
            "color": ACTION_COLORS.get(main, "#888")}]
    rest = 100 - int(bucket)
    if rest > 0:
        pas = PASSIVE_OF.get(node_action or "", "过牌")
        out.append({"action": pas, "kind": pas, "freq": rest,
                    "color": ACTION_COLORS.get(pas, "#555")})
    return out



# ══ 从规则尺度解析出具体百分比 ════════════════════════════════
import re as _re


def parse_sizings(sizing: str) -> list:
    """把 "33%" / "25-33%" / "66%+" / "75%/125%" / "Pot / 75%" 解析成 [25, 33] 这种。"""
    t = str(sizing or "")
    # "25-33%" 这种区间 → 两端各一个
    rng = _re.findall(r"(\d{1,3})\s*[-–~]\s*(\d{1,3})", t)
    if rng:
        out = []
        for a, b in rng:
            out += [int(a), int(b)]
        return sorted(set(x for x in out if 10 <= x <= 300))
    # "66%+" → 66 和 100
    plus = _re.findall(r"(\d{1,3})\s*%\s*\+", t)
    if plus:
        v = int(plus[0])
        return sorted({v, min(300, v * 2)})
    # 普通的百分数
    nums = [int(x) for x in _re.findall(r"(\d{1,3})\s*%", t)]
    nums = [x for x in nums if 10 <= x <= 300]
    if nums:
        return sorted(set(nums))
    # "小尺度 33%" 这种前面带字
    m = _re.search(r"(\d{1,3})", t)
    if m and 10 <= int(m.group(1)) <= 300:
        return [int(m.group(1))]
    return []


# 对手可选的下注尺度（按大小归到我们的 node_action）
VILLAIN_BETS = [(25, "对手小注"), (33, "对手小注"), (50, "对手中注"),
                (66, "对手大注"), (75, "对手大注"), (100, "对手大注"), (125, "对手大注")]

# ══ 节点可用动作：牌桌按钮用 ══════════════════════════════
# 每个节点的可选项，键是 node_action 的「我们做决策时面对的情况」
ACTION_SETS = {
    "对手过牌": [("过牌", "check"), ("下注 25%", "bet"), ("下注 50%", "bet"),
                 ("下注 75%", "bet"), ("下注 125%", "bet"), ("全下", "allin")],
    "我方领打": [("过牌", "check"), ("领打 33%", "donk"), ("领打 75%", "donk"), ("全下", "allin")],
    "我方领打（小注）": [("过牌", "check"), ("领打 25%", "donk"), ("领打 50%", "donk")],
    "对手小注": [("弃牌", "fold"), ("跟注", "call"), ("加注 3x", "raise"), ("全下", "allin")],
    "对手中注": [("弃牌", "fold"), ("跟注", "call"), ("加注 2.5x", "raise"), ("全下", "allin")],
    "对手大注": [("弃牌", "fold"), ("跟注", "call"), ("加注 2.2x", "raise"), ("全下", "allin")],
    "对手下注": [("弃牌", "fold"), ("跟注", "call"), ("加注", "raise"), ("全下", "allin")],
    "对手开池": [("弃牌", "fold"), ("跟注", "call"), ("3bet 3x", "raise"), ("全下", "allin")],
    "对手3bet": [("弃牌", "fold"), ("跟注", "call"), ("4bet 2.2x", "raise"), ("全下", "allin")],
    "对手4bet": [("弃牌", "fold"), ("跟注", "call"), ("全下", "allin")],
    "对手加注": [("弃牌", "fold"), ("跟注", "call"), ("再加注", "raise"), ("全下", "allin")],
    "对手过牌加注": [("弃牌", "fold"), ("跟注", "call"), ("全下", "allin")],
}


# 深度 → 尺度系数。**以 100bb 为基准 1.00**（通配规则就是 100bb 的标准解）
DEPTH_SIZING = [
    (25,  0.82, "≤25bb 浅筹码：尺度收，中大注容易被套"),
    (60,  0.92, "26–60bb 中浅：略小于标准"),
    (140, 1.00, "61–140bb：标准解（基线 100bb）"),
    (999, 1.18, ">140bb 超深：隐含赔率高，尺度更极化"),
]


def depth_multiplier(stack: str):
    """按筹码深度取尺度系数，返回 (系数, 说明)。"""
    try:
        bb = float(str(stack).replace("bb", "").split("·")[0])
    except Exception:
        return 1.0, ""
    for cap, mult, note in DEPTH_SIZING:
        if bb <= cap:
            return mult, note
    return 1.0, ""


def adjust_sizing_by_type(sizings: list, vs_type: str = "*", stack: str = "*") -> list:
    """同样的节点，面对不同对手/筹码深度，尺度要跟着调。"""
    out = list(sizings)
    mult = 1.0
    if vs_type and vs_type not in ("*", "任意"):
        try:
            from .playertypes import SIZING_ADJUST
            mult = SIZING_ADJUST.get(vs_type, (1.0, ""))[0]
        except Exception:
            mult = 1.0
    if mult != 1.0:
        out = [max(10, min(300, round(v * mult))) for v in out]
    # 深度系数
    dmult, _dnote = depth_multiplier(stack)
    if dmult != 1.0:
        out = [max(10, min(300, round(v * dmult))) for v in out]
    # 短筹码：小于 40bb 时中/大尺度并成全下更合理
    try:
        bb = float(str(stack).replace("bb", "").split("·")[0])
    except Exception:
        bb = None
    if bb is not None and bb <= 25:
        out = sorted({min(v, 100) for v in out})
    return sorted(set(out))


def node_actions(node_action: str, sizing: str = "", preflop: bool = False,
                 vs_type: str = "*", stack: str = "*") -> list:
    """该节点我方能做的动作。下注尺度直接来自规则，不再用固定列表。"""
    # 面对下注 / 加注：给出分尺度应对
    if node_action in ("对手过牌加注", "对手加注", "对手3bet", "对手4bet"):
        return [{"label": "弃牌", "kind": "fold"},
                {"label": "跟注", "kind": "call"},
                {"label": "全下", "kind": "allin"}]
    if node_action.startswith("对手") and node_action != "对手过牌":
        return [{"label": "弃牌", "kind": "fold"},
                {"label": "跟注", "kind": "call"},
                {"label": "加注 2.5x", "kind": "raise"},
                {"label": "加注 3.5x", "kind": "raise"},
                {"label": "全下", "kind": "allin"}]
    # 我方主动：过牌 + 规则给的尺度 + 全下
    siz = parse_sizings(sizing)
    if not siz:
        siz = [33, 75]
    siz = adjust_sizing_by_type(siz, vs_type, stack)
    kind = "donk" if "领打" in (node_action or "") else "bet"
    if preflop or node_action in ("开池", "对手开池"):
        word, kind = "加注", "raise"          # 翻前叫加注，不叫下注
    elif kind == "donk":
        word = "领打"
    else:
        word = "下注"
    out = [{"label": "过牌", "kind": "check"}]
    for v in siz:
        out.append({"label": f"{word} {v}%", "kind": kind, "pct": v})
    out.append({"label": "全下", "kind": "allin"})
    return out


def villain_actions(node_action: str) -> list:
    """对手轮到行动时能做什么（带尺度 + 过牌加注 XR）。"""
    if node_action.startswith("对手") and node_action != "对手过牌":
        out = [{"label": "弃牌", "kind": "fold"}, {"label": "跟注", "kind": "call"}]
        # 过牌加注：这是我们 OOP 时最关键的武器
        for pct, node in [(66, "对手小注（XR）"), (100, "对手小注（XR）"),
                          (150, "对手过牌加注"), (200, "对手过牌加注")]:
            out.append({"label": f"过牌加注 {pct}%", "kind": "xraise",
                        "pct": pct, "node": node})
        out.append({"label": "全下", "kind": "allin", "node": "对手过牌加注"})
        return out
    # 我们过牌了，对手可以过牌或下注
    out = [{"label": "过牌", "kind": "check"}]
    for pct, _ in VILLAIN_BETS:
        out.append({"label": f"下注 {pct}%", "kind": "bet", "pct": pct,
                    "node": dict(VILLAIN_BETS)[pct]})
    out.append({"label": "全下", "kind": "allin", "node": "对手大注"})
    return out



_SUITS = ["s", "h", "d", "c"]
_SUIT_CN = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}


def combo_variants(combo: str, board_text: str, base_bucket, base_mix):
    """把一手牌（如 A5s）拆成具体花色组合，并按牌面同花做调整。

    例：A♠5♠ 在有黑桃的面上，比 A♥5♥ 更值得加注（阻断坚果）。
    """
    if not combo or len(combo) < 3:
        return []
    r1, r2, kind = combo[0], combo[1], combo[2]
    board_suits = [m.group(2).lower() for m in __import__("re").finditer(r"([2-9TJQKA])([shdc])", board_text or "")]
    out = []
    if kind == "s":                                     # 同花：4 个具体组合
        for st in _SUITS:
            adj = 0
            # 牌面 3 张以上同花 → 持有该花色是强阻断
            if board_suits.count(st) >= 3:
                adj = +18
            elif board_suits.count(st) == 2:
                adj = +6
            out.append({"combo": f"{r1}{_SUIT_CN[st]}{r2}{_SUIT_CN[st]}",
                        "suit": st, "bucket": (None if base_bucket is None else max(0, min(100, int(base_bucket) + adj))),
                        "adj": adj})
    else:                                               # 非同花：只在有阻断意义时区分
        for st in _SUITS:
            adj = 0
            if board_suits.count(st) >= 3:
                adj = +10
            out.append({"combo": f"{r1}{_SUIT_CN[st]}{r2}", "suit": st,
                        "bucket": (None if base_bucket is None else max(0, min(100, int(base_bucket) + adj))),
                        "adj": adj})
    return out




def _typed_ranges(opp_pos, hero, vs_type, pot="SRP"):
    """按对手类型取范围。

    单加注底池：跟注范围用位置基线（BB 平跟 BTN 的那种宽范围）
    3bet/4bet 底池：才用「跟注 3bet」的范围（那才是当时真实的动作范围）
    """
    from .preflop import get as _get, threebet as _3b
    from .ranges import parse_range
    call_spec = _get(opp_pos, hero)
    bet_spec = None
    if vs_type and vs_type not in ("*", "任意"):
        try:
            from .playertypes import THREEBET_RANGE, CALL_3BET_RANGE
            if THREEBET_RANGE.get(vs_type):
                bet_spec = THREEBET_RANGE[vs_type]
            # 只有在 3bet/4bet 底池里才用「跟注 3bet」的范围
            if pot in ("3BP", "4BP", "3BP多人") and CALL_3BET_RANGE.get(vs_type):
                call_spec = CALL_3BET_RANGE[vs_type]
        except Exception:
            pass
    if bet_spec is None:
        try:
            bet_spec = _3b(opp_pos, hero)
        except Exception:
            bet_spec = ""
    call_set = {(c[0], c[1]) for c in parse_range(call_spec)}
    bet_set = {(c[0], c[1]) for c in parse_range(bet_spec)} if bet_spec else set()
    return call_set, bet_set


def opponent_range_cells(opp_pos: str, hero_pos: str, pot: str = "SRP", role: str = "",
                         vs_type: str = "*"):
    """对手的完整翻前范围（跟注 + 3bet），带类型标记。
    kind: call / threebet / fold"""
    if opp_pos in ("*", "", None):
        return None
    hero = hero_pos if hero_pos not in ("*", "", None) else "BTN"
    try:
        call_set, bet_set = _typed_ranges(opp_pos, hero, vs_type, pot)
        # 3bet 底池里：对手如果是 3bet 方，范围只有 3bet 那部分；
        # 如果对手是跟注方，范围只有跟注那部分
        if pot in ("3BP", "3BP多人"):
            if "PFR" in (role or ""):      # 我是 PFR(3bet方) → 对手是跟注方
                bet_set = set()
            else:                          # 我是跟注方 → 对手是 3bet 方
                call_set = set()
    except Exception:
        return None
    out = []
    for cid, _cards in combos():
        is3b = _hand_in_range(cid, bet_set)
        iscall = _hand_in_range(cid, call_set)
        if is3b:
            out.append({"combo": cid, "cat": cid, "bucket": 100,
                        "matched": cid, "mix": [], "folded": False, "kind": "threebet"})
        elif iscall:
            out.append({"combo": cid, "cat": cid, "bucket": 100,
                        "matched": cid, "mix": [], "folded": False, "kind": "call"})
        else:
            out.append({"combo": cid, "cat": cid, "bucket": 0,
                        "matched": cid, "mix": [], "folded": True, "kind": "fold"})
    return out




def _opp_range_set(opp_pos, hero_pos, pot="SRP", role=""):
    """对手在这条线的真实翻后范围（与 opponent_range_cells 口径一致）。"""
    if opp_pos in ("*", "", None):
        return None
    hero = hero_pos if hero_pos not in ("*", "", None) else "BTN"
    try:
        from .preflop import get as _get, threebet as _3b
        from .ranges import parse_range
        call_set = {(c[0], c[1]) for c in parse_range(_get(opp_pos, hero))}
        try:
            bet_set = {(c[0], c[1]) for c in parse_range(_3b(opp_pos, hero))}
        except Exception:
            bet_set = set()
        if pot in ("3BP", "3BP多人"):
            if "PFR" in (role or ""):
                return call_set
            return bet_set
        return call_set | bet_set
    except Exception:
        return None


# ══ 对手视角：每种手牌在这条线做什么 ═══════════════════════════
_CAT_BASE = {
    "坚果": (80, 18, 2), "暗三": (75, 22, 3), "三条": (70, 26, 4),
    "两对": (62, 33, 5), "顶对好踢": (48, 45, 7), "顶对": (40, 50, 10),
    "对子": (22, 58, 20), "听牌": (35, 52, 13), "卡顺": (28, 50, 22),
    "空气": (8, 12, 80), "高张": (12, 25, 63),
}

_TYPE_ADJ = {
    "标准": (1.0, 1.0), "紧凶": (1.25, 0.85), "松凶": (1.45, 1.15),
    "岩石": (0.65, 0.6), "跟注站": (0.35, 1.5), "娱乐玩家": (0.4, 1.55),
    "受气包": (0.3, 1.2), "过度诈唬型": (1.7, 0.9), "下注不足型": (0.6, 1.25),
}

def opponent_frequencies(root: Path, board_text, street, opp_pos, hero_pos,
                         vs_type="标准", in_range=None):
    """对手每种手牌在这条线的「加注 / 跟注 / 弃牌(过牌)」频率。

    in_range: 对手翻后的真实范围（他翻前跟注的那些牌）。
    不在这套范围里的手牌（比如 BB 早用 AA 去 3bet 了）直接算 100% 弃，
    不能给他算出「AA 过牌加注」这种不可能的动作。
    """
    try:
        cards, pat = parse_board(board_text)
    except Exception:
        return None
    # 没传范围就自己算（对手的跟注范围）
    if in_range is None:
        try:
            from .preflop import get as _get
            from .ranges import parse_range
            hh = hero_pos if hero_pos not in ("*", "", None) else "BTN"
            in_range = {(c[0], c[1]) for c in parse_range(_get(opp_pos, hh))}
        except Exception:
            in_range = None
    if not vs_type or vs_type == "*":
        vs_type = "标准"
    adj = _TYPE_ADJ.get(vs_type, (1.0, 1.0))
    out = []
    for cid, cc in combos():
        # 不在对手翻后范围里 → 这手牌根本不存在，直接 100% 弃
        if in_range is not None and not _hand_in_range(cid, in_range):
            out.append({"combo": cid, "cat": "不在范围", "raise": 0, "call": 0, "fold": 100})
            continue
        try:
            cat = classify(cards, [cc[0], cc[1]])
        except Exception:
            cat = "空气"
        base = (30, 40, 30)
        for k, v in _CAT_BASE.items():
            if k in (cat or ""):
                base = v
                break
        r = max(0, min(100, round(base[0] * adj[0])))
        c = max(0, min(100 - r, round(base[1] * adj[1])))
        f = 100 - r - c
        out.append({"combo": cid, "cat": cat,
                    "raise": r, "call": c, "fold": f})
    out.sort(key=lambda x: -(x["raise"] * 2 + x["call"]))
    return out


# ══ 简化策略：频率量化到固定档位 ═══════════════════════════════
SIMPLE_PRE = [100, 75, 50, 25, 0]
SIMPLE_POST = [100, 80, 60, 40, 20, 0]


def _simplify_cfg() -> dict:
    try:
        cfg = json.loads((Path(__file__).resolve().parent.parent / "data" / "tree"
                          / "adjustments.json").read_text(encoding="utf-8"))
        return cfg.get("simplify") or {}
    except Exception:
        return {}


def simple_levels(street: str) -> list:
    sc = _simplify_cfg()
    lev = sc.get("levels_pre") if street == "翻前" else sc.get("levels_post")
    if lev:
        return sorted([int(x) for x in lev], reverse=True)
    return SIMPLE_PRE if street == "翻前" else SIMPLE_POST


def simplify_value(v, street: str):
    if v is None:
        return None
    return min(simple_levels(street), key=lambda x: abs(x - float(v)))


def quantize_error(v, street: str) -> float:
    if v is None:
        return 0.0
    return abs(float(v) - simplify_value(v, street))


def mix_threshold(street: str = "翻牌") -> float:
    sc = _simplify_cfg()
    if street == "翻前":
        return float(sc.get("threshold_pre", 2))
    return float(sc.get("threshold_post", 8))


def force_mixed_multi() -> bool:
    return bool(_simplify_cfg().get("force_mixed_if_multi_sizing", True))


def node_is_mixable(cells: list, street: str, n_sizing: int = 1) -> dict:
    """判定这个节点用「混合」还是「简化」。"""
    vals = [c["bucket"] for c in cells if c.get("bucket") is not None]
    if not vals:
        return {"mode": "简化", "avg_err": 0.0, "max_err": 0.0, "n": 0,
                "threshold": mix_threshold(street), "n_sizing": n_sizing, "reason": ""}
    errs = [quantize_error(v, street) for v in vals]
    avg = sum(errs) / len(errs)
    mx = max(errs)
    th = mix_threshold(street)
    multi = n_sizing > 1 and force_mixed_multi()
    return {
        "mode": "混合" if (multi or avg > th) else "简化",
        "avg_err": round(avg, 1), "max_err": round(mx, 1),
        "n": len(vals), "threshold": th, "n_sizing": n_sizing,
        "reason": (("有 %d 个尺度，必须混合" % n_sizing) if multi else
                   (("误差 %.1f > 阈值 %.0f" % (avg, th)) if avg > th else "")),
    }


def _apply_simple_actions(acts: list, mode: dict, street: str, simplify: bool) -> list:
    """简化下翻后只留一个下注尺度。"""
    if not simplify or (mode or {}).get("mode") != "简化" or street == "翻前":
        return acts
    bets = [a for a in acts if a.get("pct")]
    if len(bets) <= 1:
        return acts
    keep = bets[0]
    return [a for a in acts if not a.get("pct") or a is keep]


# ══ 主入口：渲染一个节点的 169 矩阵 ═══════════════════════════
AUTO_POT = ["3BP", "4BP", "多人池", "3人池"]


def _approx_chain(pot: str, action: str):
    """近似兜底：(池型, 动作) 组合，按「改动最小」排序。"""
    alts_action = []
    if action == "对手中注":
        alts_action = ["对手大注", "对手小注"]
    elif action in ("对手大注", "对手小注"):
        alts_action = ["对手中注"]
    alts_pot = []
    if pot == "3人池":
        alts_pot = ["多人池"]
    elif pot == "3BP多人":
        alts_pot = ["多人池", "3BP"]

    out = []
    # 先只改动作
    for a in alts_action:
        out.append((pot, a, f"动作退到 {a}"))
    # 再只改池型
    for p in alts_pot:
        out.append((p, action, f"池型退到 {p}"))
    # 最后两个都改
    for p in alts_pot:
        for a in alts_action:
            out.append((p, a, f"池型退到 {p} + 动作退到 {a}"))
    return out


def grid(root: Path, pot: str, role: str, board_text: str, street: str, action: str,
         hero_pos: str = "*", opp_pos: str = "*", stack: str = "*",
         runout: str = "*", line: str = "*", vs_type: str = "*", capped: str = "*",
         path: str = "", hero_stack: str = "*", villain_stack: str = "*",
         multi: bool = False, simplify: bool = False, locks=None):
    rules, buckets = _load(root)
    try:
        cards, pat = parse_board(board_text or "A72r")
    except ValueError as e:
        return {"ok": False, "error": str(e), "reason": str(e)}
    bclass = board_class(cards, pat)

    # ── 有效筹码 = 双方较短的那个 ─────────────────────────
    # 我 100bb 对对手 20bb → 实际只能打 20bb 的池，按 20bb 的策略走
    def _bb(v):
        try:
            return float(str(v).replace("bb", "").split("·")[0])
        except Exception:
            return None
    eff_note = ""
    _hs, _vs = _bb(hero_stack), _bb(villain_stack)
    # 只在明确指定了深度时才用有效筹码逻辑；stack="*" 表示「任意」
    if str(stack or "*") == "*":
        _hs = _vs = None
    if _hs and _vs:
        eff = min(_hs, _vs)
        if eff != _hs or eff != _vs:
            eff_note = f"有效筹码 {eff:g}bb（双方较短的那个）"
        # 用有效筹码去找规则
        base = str(stack or "*")
        suffix = "·前注" if "前注" in base else ""
        stack = f"{eff:g}bb{suffix}"
        eff_note = eff_note or f"{eff:g}bb"

    q = {
        "pot_type": pot, "role": role, "street": street, "node_action": action,
        "hero_pos": hero_pos or "*", "opp_pos": opp_pos or "*", "stack": stack or "*",
        "runout": runout or "*", "line": line or "*", "vs_type": vs_type or "*",
        "capped": capped or "*", "path": path or "", "board_class": bclass,
        "_board": board_text,
        "hero_stack": hero_stack or "*", "villain_stack": villain_stack or "*",
    }

    hits = find_rule(rules, q)
    approx = ""
    used_pot, used_action = pot, action
    if not hits:
        # 退到「按牌面类别」再找一次
        q2 = dict(q, board_class=bclass)
        hits = find_rule(rules, q2)
    if not hits:
        for alt_pot, alt_action, why in _approx_chain(pot, action):
            q3 = dict(q, pot_type=alt_pot, node_action=alt_action)
            hits = find_rule(rules, q3)
            if hits:
                approx = why
                used_pot, used_action = alt_pot, alt_action
                break
    if not hits:
        return {"ok": False, "board_class": bclass, "board": board_text,
                "reason": f"没有匹配的规则（{pot}/{role}/{street}/{action}）"}

    r = hits[0]
    tid = r.get("bucket_table") or ""
    unit = "下注率"
    basis = ""

    # 桶表单位
    for b in buckets:
        if b["table_id"] == tid:
            unit = b.get("unit") or "下注率"
            basis = b.get("basis") or ""
            break

    preflop = street == "翻前"
    # 我方翻前打进底池的范围——翻后手里只可能是这些牌
    in_range = None
    if not preflop and hero_pos not in ("*", "", None):
        in_range = _preflop_range(hero_pos, opp_pos or "*")
    cells = []
    for cid, cc in combos():
        if preflop:
            bucket, matched = bucket_of_exact(cid, tid, buckets)
            cat = cid
        else:
            cat = classify(cards, [cc[0], cc[1]])
            bucket, matched = bucket_of(cat, tid, buckets)
        mixed = action_mix(bucket, unit, r.get("node_action") or action, r.get("sizing") or "")
        # 不在我方翻后范围里 → 这手牌根本不在他手里，标成「不可能」
        outside = (in_range is not None) and (not _hand_in_range(cid, in_range))
        if outside:
            # 不在我方翻后范围里：这手牌根本不存在，频率必须归零，
            # 不能只打标记（否则界面可能按原频率渲染出「这手牌可以下注」）
            bucket = 0
            mixed = []
        folded = outside or (bucket is not None and int(bucket) == 0)
        cells.append({"combo": cid, "cat": cat, "bucket": bucket,
                      "matched": matched or cat, "mix": mixed, "folded": folded,
                      "impossible": outside})

    # 对手倾向直接改数值
    cells, tend_note = apply_tendency(cells, r.get("node_action") or action, vs_type)

    # 尺度个数 → 混合/简化判定（用原始值）
    def _sz(h):
        return (h.get("sizing") or "").strip()
    _nsize = len({_sz(h) for h in hits if _sz(h) not in ("", "—", "*")}) or 1
    _mode = node_is_mixable(cells, street, _nsize)

    # 简化：吸附到固定档位
    if simplify:
        for c in cells:
            if c.get("bucket") is not None:
                c["bucket_raw"] = c["bucket"]
                c["bucket"] = simplify_value(c["bucket"], street)
                c["mix"] = action_mix(c["bucket"], unit,
                                      r.get("node_action") or action, r.get("sizing") or "")
                c["folded"] = int(c["bucket"]) == 0

    # 并存尺度
    multi_rules = []
    RANK = {"课程": 4, "课程+蓝图": 4, "Overbankroll": 3, "求解": 5,
            "蓝图": 2, "推导": 1, "Smash": 3, "Upswing": 3, "红线蓝图": 3}
    seen = {}
    for h in hits:
        key = _sz(h)
        if not key or key in ("—", "*"):
            continue
        sc = RANK.get(h.get("source"), 0)
        if key not in seen or sc > seen[key][0]:
            seen[key] = (sc, h)
    for _k, (sc, h) in seen.items():
        multi_rules.append({"rule_id": h["rule_id"], "sizing": h["sizing"],
                            "source": h.get("source"), "conf": h.get("conf"),
                            "bucket_table": h.get("bucket_table"), "note": h.get("note")})
    multi_rules.sort(key=lambda x: -RANK.get(x["source"], 0))

    # 范围下注占比
    # 范围平均值只算「真正在范围里」的牌，范围外的空气不参与（否则被稀释）
    vals = [int(c["bucket"]) for c in cells
            if c.get("bucket") is not None and not c.get("impossible")]
    range_bet_pct = round(sum(vals) / len(vals), 1) if vals else 0

    # 翻前用表格
    table_rows = []
    if preflop:
        rows = [b for b in buckets if b["table_id"] == tid and b["hand_class"] != "其他"]
        try:
            rows.sort(key=lambda b: -int(b["bucket"]))
        except Exception:
            pass
        table_rows = [{"hand_class": b["hand_class"], "bucket": int(b["bucket"])} for b in rows]

    conflict = len(hits) > 1
    return {
        "ok": True,
        "board": board_text,
        "board_class": bclass,
        "rule": {"rule_id": r["rule_id"], "pot_type": r.get("pot_type"),
                 "role": r.get("role"), "street": r.get("street"),
                 "node_action": r.get("node_action"), "sizing": r.get("sizing"),
                 "freq": r.get("freq"), "source": r.get("source"),
                 "conf": r.get("conf"), "note": r.get("note")},
        "cells": cells,
        "table": {"id": tid, "unit": unit, "basis": basis, "rows": len(table_rows)},
        "table_rows": table_rows,
        "node_actions": _apply_simple_actions(node_actions(r.get("node_action") or action,
                                                           r.get("sizing") or "",
                                                           preflop=preflop,
                                                           vs_type=vs_type, stack=stack),
                                              _mode, street, simplify),
        "villain_actions": villain_actions(r.get("node_action") or action),
        "strategy_mode": _mode,
        "multi_rules": multi_rules,
        "range_bet_pct": range_bet_pct,
        "opp_pos": opp_pos,
        "villain_range": opponent_range_cells(opp_pos, hero_pos, pot, role, vs_type),
        "opponent_freq": (None if preflop else
                          opponent_frequencies(root, board_text, street,
                                               opp_pos, hero_pos, vs_type,
                                               in_range=_opp_range_set(opp_pos, hero_pos, pot, role))),
        # ── 快速修正层（CFR 思想，毫秒级）：用真实牌面算范围优势，微调规则尺度 ──
        "live": _live_advice(hero_pos, opp_pos, board_text,
                             r.get("sizing") or "", pot, role),
        "locked": _locked_advice(locks, hero_pos, opp_pos, board_text,
                                 r.get("sizing") or "", pot),
        "approx": approx,
        "effective_stack": eff_note,
        "adjust": tend_note,
        "conflicts": [h["rule_id"] for h in hits[1:]] if conflict else [],
        "guarantee": _guarantee(r, _mode, pot, multi_on=simplify is False),
        "mix_display": mix_display(cells, r.get("sizing") or ""),
        "hold": False,
        "reason": "",
    }


# ══ 节点级动作混合：同一节点多条规则 → 每手牌的频率分配 ═════════
_CAT_KEYS = {"两对+", "顶对好踢", "顶对弱踢", "顶对", "听牌", "A大", "卡顺",
             "中对", "底对", "纯空气", "空气", "高张", "三条", "两对"}


def build_node_mix(hits: list, buckets: list, hand_class: str, node_action: str,
                   street: str, simplified: bool, hand_cat: str = None) -> list:
    """同节点所有并存规则按手牌合并成动作频率。

    例：R16(下注120%) 表里 AA=100，R17(下注30%) 表里 AA=0
        → AA = 加注120% 100%（归一后）
        两条都给 100 → 按比例归一成 67%/33%（方案 A）

    返回 [{action, label, sizing, pct, kind}]
    """
    # 先按「尺度」去重：同一尺度只要来源最可靠的那条，避免推导变体堆叠
    RANK = {"课程": 4, "课程+蓝图": 4, "Overbankroll": 3, "求解": 5, "蓝图": 2, "推导": 1, "Smash": 3}
    best = {}
    for h in hits:
        key = ((h.get("sizing") or "").strip(), h.get("node_action") or "")
        score = RANK.get(h.get("source"), 0)
        if key not in best or score > best[key][0]:
            best[key] = (score, h)
    hits = [h for _s, h in best.values()]

    # 每张桶表 → {hand: value}
    tab = {}
    for b in buckets:
        tab.setdefault(b["table_id"], {})[b["hand_class"]] = int(b["bucket"])

    parts = []
    for h in hits:
        tid = h.get("bucket_table") or ""
        t = tab.get(tid, {})
        # 类别表用手牌类别查（翻后），手牌表用 AA/AKs 查（翻前）
        is_cat = bool(set(t) & _CAT_KEYS)
        key = (hand_cat or hand_class) if is_cat else hand_class
        v = t.get(key)
        if v is None:
            v = t.get("其他", 0)
        if not v:
            continue
        parts.append({"rule": h,
                      "sizing": h.get("sizing") or "",
                      "action": h.get("node_action") or node_action,
                      "pct": float(v)})

    if not parts:
        return []

    total = sum(p["pct"] for p in parts)
    if total > 100:                      # 方案 A：按比例归一
        k = 100.0 / total
        for p in parts:
            p["pct"] = p["pct"] * k
        rest = 0.0
    else:
        rest = 100.0 - total             # 剩下的 = 过牌/弃牌

    # ── 先收敛：同一节点最多保留 3 个尺度（来源最可靠的），
    #    否则 9 个来源冲突会把每个都稀释成 2%。这是「抽象」而不是「平均」。──
    if len(parts) > 3:
        _RANK = {"课程": 5, "课程+蓝图": 5, "求解": 6, "蓝图": 4,
                 "Upswing": 4, "Smash": 4, "红线蓝图": 4, "Overbankroll": 4, "推导": 1}
        parts.sort(key=lambda x: -_RANK.get((x["rule"].get("source") or ""), 0))
        kept = parts[:3]
        dropped = sum(p_["pct"] for p_ in parts[3:])
        # 被砍掉的频率并回剩下的三个，保持总量
        if dropped > 0 and kept:
            tw = sum(p_["pct"] for p_ in kept) or 1
            for p_ in kept:
                p_["pct"] += dropped * p_["pct"] / tw
        parts = kept

    # ── EQR 驱动的尺度分配（替代「把多个来源平均」）──
    # 原则：这手牌能兑现多少权益，决定它该用大尺度还是小尺度。
    #   EQR 高 → 价值牌 → 偏大注
    #   EQR 中 → 混合
    #   EQR 低但有胜率 → 偏小注（诈唬/薄价值）
    if (not simplified) and len(parts) > 1:
        try:
            from .eqr import get as _eqr_get
            from .preflop import get as _pf_get

            def _size_num(sz):
                import re as _r
                m = _r.findall(r"(\d{1,3})\s*%", sz or "")
                return max((int(x) for x in m), default=50)

            # 这手牌的 EQR（用平均位置与 SPR 6 作为基线）
            # 优先按「牌面实际牌力」取 EQR（AA 和 KK 在 A72 面差别很大）
            if hand_cat:
                from .eqr import from_board_cat as _fbc
                g = _fbc(hand_cat, True, 6.0)
            else:
                g = _eqr_get(hand_class, True, 6.0)
            eqr = g["eqr"]
            # 权重：EQR 越高越偏大尺度；low EQR 偏小尺度
            weights = []
            for p_ in parts:
                num = _size_num(p_["sizing"])
                # 大尺度给高 EQR 加权，小尺度给低 EQR 加权
                bias = 1.0 + (eqr - 1.0) * (num - 50) / 50.0
                weights.append(max(0.15, p_["pct"] * bias))
            tot_w = sum(weights)
            if tot_w > 0:
                parts = sorted(
                    [dict(p_, pct=p_["pct"] * w / tot_w * (sum(x["pct"] for x in parts) / max(1e-6, sum(p_["pct"] for p_ in parts))))
                     for p_, w in zip(parts, weights)],
                    key=lambda x: -x["pct"])
        except Exception:
            pass

    if simplified:
        # 简化：同类型动作合并（两个加注尺度合成一个），频率相加
        merged = {}
        for p in parts:
            key = "raise" if ("加注" in p["action"] or "下注" in p["action"]) else "other"
            if key == "raise":
                # 用频率最高的那个尺度当代表
                cur = merged.get("raise")
                if cur is None or p["pct"] > cur["pct"]:
                    merged["raise"] = dict(p)
                else:
                    merged["raise"]["pct"] += p["pct"]
                    continue
                if cur is not None:
                    merged["raise"]["pct"] += cur["pct"]
            else:
                merged[key] = dict(p)
        parts = list(merged.values())

    _stab_hand = {"hand": hand_class, "cat": hand_cat or ""}
    out = []
    for p in parts:
        out.append({"action": p["action"], "label": p["sizing"],
                    "sizing": p["sizing"], "pct": round(p["pct"], 1),
                    "kind": "bet"})
    if rest > 0.5:
        out.append({"action": "过牌/弃牌", "label": "过牌", "sizing": "",
                    "pct": round(rest, 1), "kind": "pass"})
    out.sort(key=lambda x: -x["pct"])
    # ── 扰动测试：这个分配是「有意义的」还是「任意的」──
    try:
        from .eqr import perturb_stable
        bets = [x for x in out if x.get("kind") == "bet"]
        if len(bets) >= 2:
            st = perturb_stable([{"label": x["label"], "pct": x["pct"]} for x in bets],
                                hand_class, hand_cat or "")
            for x in out:
                x["_stable"] = st
    except Exception:
        pass
    return out


# ══ 翻前分步：按「这一步是什么」返回对应范围 ═══════════════════
def preflop_range_matrix(pos: str, opp: str, kind: str = "open", vs_type: str = "*"):
    """kind: open / 3bet / 4bet / call3bet
    返回 169 格矩阵，bucket=100 表示在这套范围里。
    """
    from .playertypes import (THREEBET_RANGE, CALL_3BET_RANGE, FOURBET_RANGE,
                              CALL_4BET_RANGE, FIVEBET_RANGE)
    from .preflop import get as _get, threebet as _3b
    from .ranges import parse_range
    t = vs_type if vs_type not in (None, "", "*", "任意") else "标准"
    try:
        if kind == "3bet":
            # 用课程对位表（谁对谁），不要按开池位置一刀切
            spec = _3b(pos, opp)
            label = f"{pos} 3bet {opp} 的范围"
        elif kind == "4bet":
            spec = FOURBET_RANGE.get(t)
            label = f"{pos} 的 4bet 范围"
        elif kind == "call3bet":
            spec = CALL_3BET_RANGE.get(t)
            label = f"{pos} 跟注 3bet 的范围"
        elif kind == "call4bet":
            spec = CALL_4BET_RANGE.get(t)
            label = f"{pos} 跟注 4bet 的范围"
        elif kind == "5bet":
            spec = FIVEBET_RANGE.get(t)
            label = f"{pos} 5bet 全下的范围"
        else:
            try:
                spec = _get(pos, opp)
            except Exception:
                spec = None
            label = f"{pos} 的开池范围"
        if spec:
            inr = {(c[0], c[1]) for c in parse_range(spec)}
        else:
            # 这个位置不在 preflop 模块里（比如 UTG2）→ 用策略树的桶表
            inr = None
    except Exception as e:
        return {"ok": False, "reason": str(e)}

    cells = []
    n = 0
    # 桶表兜底：从数据目录里找这个位置的开池表
    _tab = None
    if inr is None:
        try:
            _r, _b = _load(Path(__file__).resolve().parent.parent / "data" / "tree")
            cand = [r for r in _r if r.get("hero_pos") == pos and r.get("node_action") == "开池"
                    and r.get("status") != "retired"]
            # 优先用「简单GTO/E8 实测表」，其次 200bb，最后才用 RYE 推导表
            def _rank(r):
                tid = r.get("bucket_table") or ""
                pri = 0
                if tid.startswith(("EG8_", "EGA_", "E8_")): pri += 10
                if (r.get("stack") or "") == "200bb": pri += 3
                if (r.get("source") or "") in ("课程", "求解"): pri += 2
                return -pri
            cand.sort(key=_rank)
            if cand:
                _tid = cand[0]["bucket_table"]
                _tab = {b["hand_class"]: int(b["bucket"]) for b in _b
                        if b["table_id"] == _tid and b["hand_class"] != "其他"}
        except Exception:
            _tab = None
    # 同时算出「加注」和「跟注」两套范围，矩阵才能三色区分
    def _set(specx):
        if not specx:
            return None
        try:
            return {(c[0], c[1]) for c in parse_range(specx)}
        except Exception:
            return None
    raise_set = inr
    call_set = None
    if kind == "3bet":
        # raise 用上面按「开池位置」算出来的 inr，不要再用通用的 THREEBET_RANGE
        call_set = _set(CALL_3BET_RANGE.get(t))
        raise_set = inr
    elif kind == "4bet":
        call_set = _set(CALL_4BET_RANGE.get(t))
        raise_set = _set(FOURBET_RANGE.get(t))
    elif kind == "call3bet":
        call_set, raise_set = inr, None
    elif kind == "call4bet":
        call_set, raise_set = inr, None

    for cid, _cc in combos():
        n_comb = (6 if len(cid) == 2 else (4 if cid.endswith("s") else 12))
        in_raise = bool(raise_set) and _hand_in_range(cid, raise_set)
        in_call = bool(call_set) and _hand_in_range(cid, call_set)
        if _tab is not None and kind == "open":
            in_raise = _tab.get(cid, 0) > 0
            in_call = False
        if in_raise:
            act, n = "raise", n + n_comb
        elif in_call:
            act = "call"
        else:
            act = "fold"
        cells.append({"combo": cid, "cat": cid, "act": act,
                      "bucket": 100 if act != "fold" else 0,
                      "matched": cid, "mix": [], "folded": act == "fold",
                      "impossible": act == "fold"})
    return {"ok": True, "cells": cells, "label": label,
            "spec": spec, "pct": round(n / 1326 * 100, 1), "kind": kind}


# ══ 保证标签：让用户一眼知道这个数有多可信 ═══════════════════════
_GUARANTEE = {
    # (等级, 颜色, 说明)
    "measured": ("实测", "#3ba55d", "来自课程/求解器实测数据"),
    "calibrated": ("已校准", "#4a9eff", "TexasSolver 校准过，保留原规则"),
    "derived": ("推导", "#c9a227", "按原理推导，无实测数据支撑"),
    "approx": ("近似", "#e07b39", "快速蒙特卡洛估算，精度有限"),
}


def _guarantee(rule, mode, pot, multi_on=False):
    src = (rule.get("source") or "").strip()
    note = (rule.get("note") or "")
    if "简单GTO" in note or "实测" in note or src == "求解":
        level = "measured"
    elif "Solver校准" in note or "校准" in note:
        level = "calibrated"
    elif src in ("课程", "课程+蓝图", "Upsmare", "Upswing", "Smash", "红线蓝图"):
        level = "measured"
    elif src == "推导":
        level = "derived"
    else:
        level = "derived"
    label, color, why = _GUARANTEE[level]
    multi = multi_on or (mode or {}).get("mode") == "混合"
    if multi and level == "derived":
        why += "（且为多尺度混合）"
    if pot in ("3人池", "3BP多人", "多人池"):
        why += " ｜ 多人池：无 Nash 定义，仅作近似参考"
    # 只要这一屏有任何启发式成分，整体等级就降一档：
    # 规则来源是实测、但尺度分配是启发式的，不能拿绿点给整屏背书。
    if multi:
        level = "mixed"
        label, color = "规则·启发式", "#c9a227"
        why = "规则来自课程/实测，但「尺度怎么分」是启发式，不是 solver 真值"
    return {"level": level, "label": label, "color": color,
            "why": why, "source": src, "honest": True}


_LIVE_CACHE: dict = {}


def _locked_advice(locks, hero_pos, opp_pos, board_text, sizing, pot):
    """有节点锁定时，算我方的最佳反应（不影响主规则，只做附加建议）。"""
    if not locks or not board_text or len(board_text) < 6:
        return None
    try:
        from .locks import compile_ranges
        from .fastcalc import best_response
        rr = compile_ranges(locks, hero_pos or "*", opp_pos or "*", pot)
        if not rr.get("has_lock"):
            return None
        from .tree import parse_sizings as _ps
        base = _ps(sizing)
        if not base:
            return None
        out = best_response(rr["hero_range"], rr["villain_range"],
                            board_text, base[0])
        if not out.get("ok"):
            return None
        out["source"] = {"hero": rr["hero_src"], "villain": rr["villain_src"]}
        return out
    except Exception:
        return None


def _live_advice(hero_pos, opp_pos, board_text, sizing, pot, role):
    """毫秒级范围优势 → 尺度微调。失败就返回 None，不影响主流程。"""
    if not board_text or len(board_text) < 6:
        return None
    key = (hero_pos, opp_pos, board_text, sizing, pot, role)
    if key in _LIVE_CACHE:
        return _LIVE_CACHE[key]
    try:
        from .fastcalc import advantage, refine_sizing
        from .preflop import get as _g
        if hero_pos in ("*", "", None) or opp_pos in ("*", "", None):
            return None
        h = _g(hero_pos, opp_pos)
        v = _g(opp_pos, hero_pos)
        r = advantage(h, v, board_text, iters=150)
        if not r.get("ok"):
            return None
        # ── EQR：把裸胜率修正成实际能兑现的权益 ──
        try:
            from .eqr import realized_equity
            from .tree import parse_sizings as _pss
            # 我是不是有位置：PFR 方通常算 IP（简化假设）
            ip = "PFR" in (role or "") and not (role or "").startswith("OOP")
            bb = 100.0
            try:
                bb = float(str(stack).replace("bb", "").split("·")[0])
            except Exception:
                pass
            spp = max(1.0, bb / 6.5)          # 粗略 SPR：筹码 / 翻前底池
            g = realized_equity(r["equity"], "AKo", ip, spp)   # 用平均牌取其系数
            r["raw_equity"] = r["equity"]
            r["eqr"] = g["eqr"]
            r["equity"] = g["realized"]
            r["adv"] = round(r["realized"] - 0.5, 4)
        except Exception:
            pass
        from .tree import parse_sizings as _ps
        base = _ps(sizing)
        out = {"equity": r["equity"], "adv": r["adv"],
               "n_hero": r["n_hero"], "n_vill": r["n_vill"]}
        if base:
            newv, why = refine_sizing(base[0], r["adv"])
            out["base_sizing"] = base[0]
            out["refined_sizing"] = round(newv)
            out["why"] = why
        _LIVE_CACHE[key] = out
        return out
    except Exception:
        return None


# ══ 翻前混合频率推导：范围边缘的手牌给混合，核心给纯 ═══════════
# 说明：这是**推导值**，不是 solver 实测。逻辑是「越靠范围边缘越混合」。
def _hand_strength(cid: str) -> float:
    """粗糙牌力分（0-1），用来判断这手牌在范围里的位置。"""
    R = "23456789TJQKA"
    order = {c: i for i, c in enumerate(R)}          # 2→0, A→12
    a, b = order.get(cid[0], 0), order.get(cid[1], 0)
    hi, lo = max(a, b), min(a, b)
    if len(cid) == 2:                                  # 口袋对
        return 0.55 + hi / 12 * 0.45
    base = hi / 12 * 0.6 + lo / 12 * 0.25
    if cid.endswith("s"):
        base += 0.10
    if hi == 12:                                       # 带 A
        base += 0.08
    if hi - lo == 1:                                   # 连牌
        base += 0.03
    return min(1.0, base)


def preflop_freq_matrix(pos: str, opp: str, kind: str = "open", vs_type: str = "*"):
    """每手牌的 加注/跟注/弃牌 百分比（推导的混合频率）。"""
    base = preflop_range_matrix(pos, opp, kind, vs_type)
    if not base.get("ok"):
        return base
    acts = {c["combo"]: c["act"] for c in base["cells"]}
    # 每个动作的「牌力分界线」：范围内最弱的那批给混合
    raise_h = sorted([h for h, a in acts.items() if a == "raise"], key=_hand_strength)
    call_h = sorted([h for h, a in acts.items() if a == "call"], key=_hand_strength)

    # 最弱的 25% 加注牌 → 混合（70% 加 / 30% 跟）
    n_raise = max(1, round(len(raise_h) * 0.25))
    weak_raise = set(raise_h[:n_raise]) if len(raise_h) > 3 else set()
    n_call = max(1, round(len(call_h) * 0.3))
    weak_call = set(call_h[:n_call]) if len(call_h) > 3 else set()

    cells = []
    for c in base["cells"]:
        h, a = c["combo"], c["act"]
        if a == "raise":
            if h in weak_raise:
                cells.append({"combo": h, "act": "raise", "raise": 70, "call": 30, "fold": 0})
            else:
                cells.append({"combo": h, "act": "raise", "raise": 100, "call": 0, "fold": 0})
        elif a == "call":
            if h in weak_call:
                cells.append({"combo": h, "act": "call", "raise": 0, "call": 50, "fold": 50})
            else:
                cells.append({"combo": h, "act": "call", "raise": 0, "call": 100, "fold": 0})
        else:
            cells.append({"combo": h, "act": "fold", "raise": 0, "call": 0, "fold": 100})
    base["cells"] = cells
    base["note"] = "频率为推导值（范围边缘混合），非 solver 实测"
    return base


# ══ 混合策略该展示什么：聚合频率 + 边界，而不是每手牌精确百分比 ═══
# 依据：均衡价值唯一、策略不唯一。百分比常是任意的，
# 稳定的是「聚合频率」和「边界在哪」。所以展示层按这个原则输出。
def mix_display(cells: list, sizing_label: str = "") -> dict:
    """从 169 格算出该展示什么。

    边界手牌的判定不再是「频率在 20–80%」这种粗筛，而是：
      1. 按牌力排序
      2. 找到「该打」和「不该打」的转折点（频率从高跨到低的位置）
      3. 转折点附近的手牌才是真边界 —— 它们才是「怎么打都差不多」的那几手
    """
    acted, boundary = [], []
    alive = [c for c in cells
             if c.get("bucket") is not None and not c.get("impossible")]
    if not alive:
        return {"aggregate_freq": 0, "boundary": [], "acted_count": 0,
                "sizing": sizing_label, "note": ""}

    # 按「频率 + 牌力」排序，找转折点
    def _strength(c):
        try:
            from .eqr import from_board_cat
            return from_board_cat(c.get("cat") or "", True, 6.0)["eqr"]
        except Exception:
            return 1.0
    ordered = sorted(alive, key=lambda c: (-_strength(c), -int(c["bucket"])))
    freqs = [int(c["bucket"]) for c in ordered]
    # 转折点：连续两格频率差最大的位置
    cut, gap = 0, 0
    for i in range(len(freqs) - 1):
        d = freqs[i] - freqs[i + 1]
        if d > gap:
            gap, cut = d, i
    # 转折点前后各取几手 —— 这些才是真正的「边界」
    lo = max(0, cut - 2)
    hi = min(len(ordered), cut + 3)
    for c in ordered[lo:hi]:
        boundary.append({"hand": c["combo"], "freq": int(c["bucket"]),
                         "cat": c.get("cat"), "why": "处在「该打/不该打」的分界上"})
    for c in alive:
        if int(c["bucket"]) > 0:
            acted.append(c["combo"])
    agg = round(sum(c["bucket"] for c in cells
                    if c.get("bucket") is not None and not c.get("impossible"))
                / max(1, len([c for c in cells
                              if c.get("bucket") is not None and not c.get("impossible")])), 1)
    return {
        "aggregate_freq": agg,                 # 聚合频率：真信息
        "boundary": boundary[:8],              # 边界手牌：真信息
        "acted_count": len(acted),
        "sizing": sizing_label,
        "note": "百分比常不唯一（均衡策略不唯一）；稳定的只有聚合频率和边界手牌",
    }


def size_pref(bucket: float, sizes: list) -> str:
    """给单手提一个「偏大/中/小」的倾向，不报精确百分比。"""
    if not sizes or bucket is None:
        return "—"
    import re as _r
    nums = []
    for s in sizes:
        m = _r.findall(r"(\d{1,3})\s*%", s or "")
        if m:
            nums.append((int(max(m, key=int)), s))
    if not nums:
        return str(sizes[0])
    nums.sort()
    hi = nums[-1][0] if len(nums) > 1 else 100
    lo = nums[0][0]
    if bucket >= 65:
        return "偏大" if hi > 60 else "标准"
    if bucket <= 25:
        return "偏小"
    return "中"
