"""翻后决策点数据库：每个"你做了一个决定"的瞬间存一行。

一行 = 一条街 + 一个牌面类型 + 一个位置对抗 + 一个动作。
有了这张表，才能既做多维聚合，又能下钻到具体手牌。
"""

from __future__ import annotations

from collections import defaultdict

from ..cards import parse_card, rank_of, suit_of
from .gg import Hand

BROADWAY = {8, 9, 10, 11, 12}  # T J Q K A
STREET_CN = {"flop": "翻牌", "turn": "转牌", "river": "河牌"}


def _board_class(flop: list[int]) -> str:
    """A高 / 双高 / 单高 / 低牌 —— 按翻牌的高张结构分。"""
    ranks = [rank_of(c) for c in flop]
    if 12 in ranks:
        return "A高"
    broad = [r for r in ranks if r in BROADWAY]
    if len(broad) >= 2:
        return "双高"
    if len(broad) == 1:
        return "单高"
    return "低牌"


def _suited_class(cards: list[int]) -> str:
    n = len({suit_of(c) for c in cards})
    if n == 1:
        return "单色面"
    return "双花面" if n == 2 else "彩虹面"


def _connected(cards: list[int]) -> bool:
    uniq = sorted({rank_of(c) for c in cards})
    if len(uniq) < 3:
        return False
    if 12 in uniq:
        uniq = [-1] + uniq  # A 当 1
    return uniq[-1] - uniq[0] <= 4


def _has_straight(ranks: list[int], need: int = 3) -> bool:
    s = set(ranks)
    if 12 in s:
        s.add(-1)
    run = 0
    for r in range(-1, 13):
        if r in s:
            run += 1
            if run >= need:
                return True
        else:
            run = 0
    return False


def runout_class(board_before: list[int], card: int) -> str:
    """这张转牌/河牌改变了什么。"""
    ranks_before = [rank_of(c) for c in board_before]
    r = rank_of(card)
    suits = [suit_of(c) for c in board_before] + [suit_of(card)]
    tags = []
    if r in ranks_before:
        tags.append("公对面")
    if r > max(ranks_before):
        tags.append("超张")
    if suits.count(suit_of(card)) >= 3:
        tags.append("成花")
    if _has_straight(ranks_before + [r], need=4):
        tags.append("成顺")
    return tags[0] if tags else "白板"


# 公开 GTO 图表里 SRP 单挑底池、翻牌圈 cbet 频率的近似值（不同 solver 会有 ±5% 差异）
REFERENCE_CBET = {"A高": 80, "双高": 65, "单高": 72, "低牌": 45}

SIZE_BUCKETS = ("≤1/3池", "1/3~1/2池", "1/2~2/3池", "2/3~1池", "1~1.3池", "超池")


def size_bucket(frac: float) -> str:
    if frac <= 0.28:
        return "≤1/3池"
    if frac <= 0.42:
        return "1/3~1/2池"
    if frac <= 0.62:
        return "1/2~2/3池"
    if frac <= 0.88:
        return "2/3~1池"
    if frac <= 1.3:
        return "1~1.3池"
    return "超池"


def _pot_walk(h: Hand):
    """边推进边算底池，产出 (动作, 动作前的底池, 该玩家本街已投入)。"""
    pot = 0.0
    inv: dict = {}
    for a in h.actions:
        if a.street == "showdown":
            continue
        key = (a.street, a.player)
        before = pot
        if a.kind == "post":
            pot += a.amount
            inv[key] = inv.get(key, 0) + a.amount
        elif a.kind in ("calls", "bets"):
            pot += a.amount
            inv[key] = inv.get(key, 0) + a.amount
        elif a.kind == "raises":
            prev = inv.get(key, 0)
            delta = max(0.0, a.to - prev)
            pot += delta
            inv[key] = a.to
        elif a.kind == "is all-in":
            prev = inv.get(key, 0)
            delta = max(0.0, a.amount - prev)
            pot += delta
            inv[key] = a.amount
        yield a, before, inv.get(key, 0.0)


# 行动线：玩家真正会说的那套词
LINE_CN = {
    "CB": "CB 持续下注",
    "B": "B 下注",
    "X": "X 过牌到底",
    "XF": "XF 过牌弃牌",
    "XC": "XC 过牌跟注",
    "XR": "XR 过牌加注",
    "F": "F 弃牌",
    "C": "C 跟注",
    "R": "R 加注",
}


def hero_line(acts: list, hero_index: int, role: str, street: str) -> str:
    """把英雄在这条街的动作序列压成一个行动线标签。"""
    if hero_index is None or hero_index >= len(acts):
        return ""
    first = acts[hero_index]
    later = [a for a in acts[hero_index + 1 :] if a.player == first.player]
    kind = first.kind
    if kind == "checks":
        nxt = later[0].kind if later else ""
        return {"folds": "XF", "calls": "XC", "raises": "XR"}.get(nxt, "X")
    if kind == "folds":
        return "F"
    if kind == "calls":
        return "C"
    if kind == "raises":
        return "R"
    if kind == "bets":
        return "CB" if (role == "进攻" and street == "flop") else "B"
    return ""


def opponent_line(acts: list, hero: str) -> str:
    """对手在这条街的行动线：下注 / 过牌 / 过牌加注 / 跟注…"""
    seq = [a for a in acts if a.player != hero]
    if not seq:
        return ""
    first = seq[0]
    later = [a for a in seq[1:] if a.player == first.player]
    if first.kind == "checks":
        nxt = later[0].kind if later else ""
        return {"raises": "XR", "calls": "XC", "folds": "XF"}.get(nxt, "X")
    return {"bets": "B", "raises": "R", "calls": "C", "folds": "F"}.get(first.kind, "")


def _pot_type(raises: int) -> str:
    if raises <= 1:
        return "SRP"
    if raises == 2:
        return "3bet底池"
    return "4bet+"


def extract_spots(h: Hand, player_types: dict | None = None) -> list[dict]:
    """把一手牌拆成若干个决策点。只记英雄自己的动作。"""
    if len(h.board) < 3:
        return []
    board = [parse_card(c) for c in h.board]
    pre = [a for a in h.actions if a.street == "preflop" and a.kind != "post"]
    raises = [a for a in pre if a.kind == "raises"]
    pot_type = _pot_type(len(raises))
    hero_pos = h.seats.get(h.hero, {}).get("pos", "?")

    # 翻牌时还在牌局里的人（没弃牌、也不是英雄）
    folded = {a.player for a in pre if a.kind == "folds"}
    alive = [n for n in h.seats if n not in folded and n != h.hero]
    if len(alive) == 1:
        villain_pos = h.seats.get(alive[0], {}).get("pos", "?")
        matchup = f"{hero_pos} vs {villain_pos}"
    elif len(alive) >= 2:
        matchup = f"{hero_pos} vs 多人"
    else:
        return []

    role = "进攻" if raises and raises[-1].player == h.hero else "防守"

    spots = []
    streets = [("flop", 0, 3), ("turn", 3, 4), ("river", 4, 5)]
    for st, lo, hi in streets:
        if len(board) <= lo:
            break
        acts = [a for a in h.actions if a.street == st]
        if not acts:
            continue
        hero_idx = next((i for i, a in enumerate(acts) if a.player == h.hero), None)
        if hero_idx is None:
            continue

        before = acts[:hero_idx]
        bet_before = [a for a in before if a.kind in ("bets", "raises")]
        if not bet_before:
            facing = "无人下注"
        elif bet_before[-1].kind == "raises":
            facing = "面对加注"
        else:
            facing = "面对下注"

        acted = acts[hero_idx]
        action = {"folds": "弃牌", "checks": "过牌", "calls": "跟注", "bets": "下注", "raises": "加注"}.get(acted.kind, acted.kind)

        # 尺度：自己下注就看自己下的，面对下注就看对手下的
        size = ""
        try:
            walk = {id(a): (before, inv) for a, before, inv in _pot_walk(h)}
            if acted.kind in ("bets", "raises"):
                before, _ = walk[id(acted)]
                amt = acted.to if acted.kind == "raises" else acted.amount
                if before > 0:
                    size = size_bucket(amt / before)
            elif bet_before:
                fb = bet_before[-1]
                before, _ = walk[id(fb)]
                amt = fb.to if fb.kind == "raises" else fb.amount
                if before > 0:
                    size = size_bucket(amt / before)
        except Exception:
            size = ""

        # check-raise：本街先过牌，之后又加注
        later = acts[hero_idx + 1 :]
        if acted.kind == "checks" and any(a.player == h.hero and a.kind == "raises" for a in later):
            action = "过牌加注"

        flop3 = board[:3]
        texture = _board_class(flop3)
        suit = _suited_class(flop3)
        paired = len({rank_of(c) for c in flop3}) < 3
        connected = _connected(flop3)
        if st == "flop":
            runout = ""
        else:
            runout = runout_class(board[: hi - 1], board[hi - 1])

        from .analysis import hand_class

        spots.append(
            {
                "hand_id": h.hand_id,
                "street": st,
                "role": role,
                "pot_type": pot_type,
                "hero_pos": hero_pos,
                "villain_pos": villain_pos if len(alive) == 1 else "多人",
                "matchup": matchup,
                "high": texture,
                "suit": suit,
                "extra": suit,
                "paired": int(paired),
                "connected": int(connected),
                "runout": runout,
                "size": size,
                "board": " ".join(h.board[:hi]),
                "hand": hand_class(h.hero_cards),
                "facing": facing,
                "action": action,
                "line": hero_line(acts, hero_idx, role, st),
                "oline": opponent_line(acts, h.hero),
                "vtype": (player_types or {}).get(alive[0], "") if len(alive) == 1 else "",
                "pot": h.pot,
                "net": round(h.hero_net(), 4),
                "bb": h.bb,
            }
        )
    return spots


DIMS = {
    "high": "牌面结构（翻牌）",
    "matchup": "位置对抗",
    "role": "进攻 / 防守",
    "pot_type": "底池类型",
    "runout": "转牌河牌出张",
    "size": "下注尺度",
    "suit": "同花结构",
    "paired": "对子面",
    "connected": "连牌面",
    "facing": "面对的动作",
    "line": "行动线",
    "oline": "对手行动线",
    "vtype": "对手类型",
    "hand": "手牌类型",
}

ACTIONS = ["下注", "过牌", "跟注", "弃牌", "加注", "过牌加注"]


def _where(filters: dict) -> tuple[str, list]:
    clauses, args = [], []
    for k, v in filters.items():
        if v in (None, "", "全部"):
            continue
        clauses.append(f"{k} = ?")
        args.append(v)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def aggregate(conn, filters: dict, group_by: str, field: str = "action") -> list[dict]:
    """按某个维度聚合，返回每个取值的动作（或行动线）分布。"""
    if group_by not in DIMS:
        raise ValueError(f"不支持的分组: {group_by}")
    if field not in ("action", "line"):
        raise ValueError(field)
    where, args = _where(filters)
    rows = conn.execute(
        f"SELECT {group_by} AS k, {field} AS a, COUNT(*) AS n FROM hh_spots{where} "
        f"GROUP BY k, a HAVING a IS NOT NULL AND a != ''",
        args,
    ).fetchall()
    bucket: dict[str, dict] = {}
    for r in rows:
        k = r["k"] or ""
        if not k:
            continue
        b = bucket.setdefault(k, {"label": k, "n": 0, "actions": {}})
        b["n"] += r["n"]
        b["actions"][r["a"]] = r["n"]
    if group_by in ("paired", "connected"):
        for b in bucket.values():
            b["label"] = {"1": "有", "0": "无"}.get(str(b["label"]), b["label"])

    out = []
    for b in bucket.values():
        acts = b["actions"]
        top = max(acts, key=acts.get)
        b["top_action"] = top
        b["top_pct"] = round(acts[top] / b["n"] * 100, 1)
        out.append(b)
    out.sort(key=lambda x: -x["n"])
    return out


def hands(conn, filters: dict, limit: int = 60) -> list[dict]:
    where, args = _where(filters)
    rows = conn.execute(
        f"""SELECT hand_id, street, board, hand, action, facing, matchup, pot, net, bb
            FROM hh_spots{where} ORDER BY RANDOM() LIMIT ?""",
        args + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def findings(rows: list[dict], street: str, role: str, group: str = "high") -> list[dict]:
    """从聚合结果里挑出"值得说一句"的偏离，不需要模型。"""
    out = []
    big = [r for r in rows if r["n"] >= 30]
    if len(big) >= 3 and group != "size":
        bets = [(r["label"], r["actions"].get("下注", 0) / r["n"] * 100) for r in big]
        bets.sort(key=lambda x: -x[1])
        hi, lo = bets[0], bets[-1]
        if hi[1] - lo[1] < 12:
            out.append({
                "level": "warn",
                "text": f"你在 {hi[0]} 和 {lo[0]} 的下注率几乎一样（{hi[1]:.0f}% vs {lo[1]:.0f}%），说明 cbet 频率没有跟着牌面走。",
            })
        else:
            out.append({
                "level": "ok",
                "text": f"下注率最高的是 {hi[0]}（{hi[1]:.0f}%），最低是 {lo[0]}（{lo[1]:.0f}%），方向是对的。",
            })

    total = sum(r["n"] for r in rows)
    if total:
        fold = sum(r["actions"].get("弃牌", 0) for r in rows) / total * 100
        xr = sum(r["actions"].get("过牌加注", 0) for r in rows) / total * 100
        if street == "flop" and role == "防守" and fold < 30:
            out.append({"level": "warn", "text": f"面对下注只弃 {fold:.0f}%，低于 30%：翻牌跟得太宽，转牌会很难受。"})
        if group != "size" and role != "进攻" and xr < 3:
            out.append({"level": "warn", "text": f"过牌加注只有 {xr:.1f}%：你过牌之后基本等于放弃，没有保护过牌范围。"})
        elif group != "size" and role != "进攻" and xr > 12:
            out.append({"level": "warn", "text": f"过牌加注 {xr:.1f}% 偏高，容易被对手用强牌设陷阱。"})
    # 与公开基准比：只在"翻牌 + 进攻 + 牌面结构"这一组合下有意义
    if group == "high" and street == "flop" and role == "进攻":
        parts, worst = [], 0.0
        for r in rows:
            ref = REFERENCE_CBET.get(r["label"])
            if not ref or r["n"] < 30:
                continue
            actual = r["actions"].get("下注", 0) / r["n"] * 100
            diff = actual - ref
            worst = max(worst, abs(diff))
            mark = "✓" if abs(diff) < 8 else ("↑" if diff > 0 else "↓")
            parts.append(f"{r['label']} 你{actual:.0f}%/基准{ref}%{mark}")
        if parts:
            out.append({
                "level": "warn" if worst >= 12 else "ok",
                "text": "对比公开 GTO 近似值：" + " · ".join(parts)
                        + "。差 12 个点以上才值得改，基准是 SRP 单挑的近似值。",
            })

    # 尺度：大尺度占比过高
    sized = [r for r in rows if r["label"] in SIZE_BUCKETS]
    if len(sized) >= 3:
        tot = sum(r["n"] for r in sized)
        big = sum(r["n"] for r in sized if r["label"] in ("2/3~1池", "1~1.3池", "超池"))
        small = sum(r["n"] for r in sized if r["label"] in ("≤1/3池", "1/3~1/2池"))
        if tot:
            if big / tot > 0.45:
                out.append({"level": "warn", "text": f"大尺度（≥2/3 池）占你下注的 {big/tot*100:.0f}%，现代 GTO 在这个池型下更常用小尺度，大尺度会让你的范围变窄、更容易被读。"})
            elif small / tot > 0.4:
                out.append({"level": "ok", "text": f"小尺度（≤1/2 池）占 {small/tot*100:.0f}%，方向符合现代打法。"})

    thin = [r["label"] for r in rows if r["n"] < 30]
    if thin:
        out.append({"level": "muted", "text": "样本少于 30 的场景：" + "、".join(thin[:4]) + "（看趋势，别当结论）"})
    return out


def render_table(rows: list[dict], dim: str) -> str:
    if not rows:
        return "没有数据。"
    lines = [f"{DIMS.get(dim, dim)}" + " " * 6 + "手数   最常做的动作"]
    for r in rows:
        shares = " / ".join(
            f"{a} {r['actions'][a]/r['n']*100:.0f}%" for a in ACTIONS if r["actions"].get(a)
        )
        lines.append(f"  {r['label']:16s} {r['n']:5d}   {shares}")
    return "\n".join(lines)


def render_hand_detail(hand: dict) -> str:
    """把一手牌渲染成可读的战斗记录。"""
    from ..cards import pretty_cards, parse_cards

    def fmt(cards):
        try:
            return pretty_cards(parse_cards(" ".join(cards)))
        except Exception:
            return " ".join(cards)

    seats = hand.get("seats", {})
    hero = hand.get("hero", "")
    pos = seats.get(hero, {}).get("pos", "")
    lines = [
        f"{hand.get('hand_id')} · {hand.get('played_at')} · {hand.get('sb')}/{hand.get('bb')}",
        f"{pos} · {hero} [{fmt(hand.get('hero_cards', []))}]"
        + (f" · 牌面 {fmt(hand.get('board', []))}" if hand.get("board") else ""),
        "",
    ]
    street_cn = {"preflop": "翻前", "flop": "翻牌", "turn": "转牌", "river": "河牌"}
    for a in hand.get("actions", []):
        if a["street"] not in street_cn:
            continue
        name = a["player"]
        tag = "★" if name == hero else " "
        kind = {"folds": "弃牌", "checks": "过牌", "calls": "跟注", "bets": "下注",
                "raises": "加注", "post": "下盲注"}.get(a["kind"], a["kind"])
        amt = f" {a['to']:g}" if a["kind"] == "raises" else (f" {a['amount']:g}" if a["amount"] else "")
        lines.append(f"  {street_cn[a['street']]:2s} {tag} {name:12s} {kind}{amt}")
    net = hand.get("collected", {}).get(hero, 0) + hand.get("returned", {}).get(hero, 0)
    lines.append("")
    lines.append(f"结果：赢 {net:g} · 底池 {hand.get('pot', 0):g}")
    return "\n".join(lines)


def combo_findings(conn, street: str, role: str = "", pot_type: str = "", min_n: int = 40,
                   top: int = 3, filters: dict | None = None) -> list[dict]:
    """在"牌面 × 同花 × 对子 × 连牌"的组合里找偏离最大的几个。

    filters 里已经固定的维度会作为 WHERE 条件带进来，保证结果服从当前筛选。
    """
    where = ["street = ?"]
    args: list = [street]
    if role:
        where.append("role = ?")
        args.append(role)
    if pot_type:
        where.append("pot_type = ?")
        args.append(pot_type)
    for k in ("high", "suit", "paired", "connected", "size", "matchup"):
        v = (filters or {}).get(k)
        if v:
            where.append(f"{k} = ?")
            args.append(v)
    w = " AND ".join(where)

    base = conn.execute(
        f"SELECT COUNT(*) n, SUM(action='下注') b, SUM(action='弃牌') f FROM hh_spots WHERE {w}", args
    ).fetchone()
    if not base["n"]:
        return []
    base_bet = (base["b"] or 0) / base["n"] * 100
    base_fold = (base["f"] or 0) / base["n"] * 100

    rows = conn.execute(
        f"""SELECT high, suit, paired, connected, COUNT(*) n,
                   SUM(action='下注') b, SUM(action='弃牌') f
            FROM hh_spots WHERE {w}
            GROUP BY high, suit, paired, connected HAVING n >= ?""",
        args + [min_n],
    ).fetchall()

    out = []
    for r in rows:
        parts = [r["high"], r["suit"]]
        if r["paired"]:
            parts.append("对子")
        if r["connected"]:
            parts.append("连牌")
        label = "·".join(x for x in parts if x)
        if role == "防守":
            pct = r["f"] / r["n"] * 100
            ref, kind = base_fold, "你自己的平均弃牌率"
        else:
            ref = REFERENCE_CBET.get(r["high"]) if role == "进攻" else None
            kind = "公开 GTO 近似值"
            if ref is None:
                ref, kind = base_bet, "你自己的平均下注率"
            pct = r["b"] / r["n"] * 100
        out.append({"label": label, "n": r["n"], "pct": round(pct, 1), "ref": round(ref, 1), "dev": round(pct - ref, 1), "kind": kind})
    out.sort(key=lambda x: -abs(x["dev"]))
    return out[:top]
