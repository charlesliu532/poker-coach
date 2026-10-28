"""翻前序列 → 翻后双方的真实范围。

为什么需要这个模块
------------------
策略树以前只看「位置 + 底池类型」猜范围，于是：
  BTN 开池、BB 跟注         → BTN 用开池范围        （对）
  BTN 开池、SB 3bet、BTN 跟 → BTN 还是用开池范围    （错，应该是跟注 3bet 范围）
  BB 跟注后翻牌             → BB 用「BB 对 BTN 的开池范围」倒是对的
同一个「3BP、BTN vs SB」，我是 3bet 方还是跟注方，翻后范围完全不同。

现在序列是唯一真源：前端把 Spot 的 [{pos, act}] 编码成
    ``BTN:open>SB:3bet>BTN:call``
后端 ``resolve()`` 逐步还原「谁最后做了什么」，再按动作取范围：

    动作          范围来源
    开池          preflop.get(pos)            （课程开池表）
    3bet          preflop.threebet(pos, 对手) （GTO 15 对位表）
    跟注开池      preflop.threebet_call(…)     （GTO 表里的 flat 部分）
    4bet          playertypes.FOURBET_RANGE
    跟注 3bet     playertypes.CALL_3BET_RANGE
    跟注 4bet     playertypes.CALL_4BET_RANGE
    5bet          playertypes.FIVEBET_RANGE

所有「解析 / 归一化 / 取范围」都只在这里做一次，tree.py 不许再自己猜。
"""
from __future__ import annotations

# 中文 / 前端 kind / 英文 → 统一动作码
_ACT = {
    "开池": "open", "open": "open", "raise": "open", "raises": "open",
    "3bet": "3bet", "3-bet": "3bet", "threebet": "3bet",
    "4bet": "4bet", "4-bet": "4bet", "fourbet": "4bet",
    "5bet": "5bet", "5-bet": "5bet", "5bet 全下": "5bet", "5bet全下": "5bet",
    "allin": "5bet", "全下": "5bet",
    "跟注": "call", "call": "call", "call_open": "call",
    "call3bet": "call", "call4bet": "call",
    "弃牌": "fold", "fold": "fold",
    "过牌": "check", "check": "check",
}
_RAISES = {"open", "3bet", "4bet", "5bet"}
_CN = {"open": "开池", "3bet": "3bet", "4bet": "4bet", "5bet": "5bet 全下",
       "call": "跟注", "fold": "弃牌", "check": "过牌"}


def _act(code: str) -> str:
    return _ACT.get(str(code or "").strip().lower(), _ACT.get(str(code or "").strip(), "fold"))


def parse(text: str) -> list[dict]:
    """``BTN:open>BB:call`` → [{'pos': 'BTN', 'act': 'open'}, …]。

    容错：支持 `>`、`,`、`|` 分隔，也支持 `BTN open`（空格）。
    """
    out: list[dict] = []
    raw = str(text or "").strip()
    if not raw:
        return out
    for chunk in raw.replace("|", ">").replace(",", ">").split(">"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            pos, act = chunk.split(":", 1)
        elif " " in chunk:
            pos, act = chunk.split(None, 1)
        else:
            continue
        pos = pos.strip().upper()
        if pos:
            out.append({"pos": pos, "act": _act(act.strip())})
    return out


def format(steps) -> str:
    """[{pos, act}] → 规范编码；前端 Spot 也按这个格式发。"""
    return ">".join(f"{str(s.get('pos', '')).upper()}:{_act(s.get('act', ''))}"
                    for s in (steps or []) if s.get("pos"))


def _raises_before(steps: list[dict], i: int) -> int:
    return sum(1 for s in steps[:i] if s["act"] in _RAISES)


def _pot_of(n_raises: int, players: int = 2) -> str:
    if n_raises >= 4:
        return "4BP"
    if n_raises == 3:
        return "4BP"
    if n_raises == 2:
        return "3BP多人" if players >= 3 else "3BP"
    if players >= 3:
        return "3人池"
    return "SRP"


# 8-max 的位置在开池表里没有单列，按最近的紧度取：UTG1/UTG2 ≈ UTG。
_POS_FALLBACK = {"UTG1": "UTG", "UTG2": "UTG", "MP": "HJ", "LJ": "HJ"}


def _spec_and_label(pos: str, act: str, opponent: str, raises_before: int,
                    vs_type: str) -> tuple[str | None, str, str]:
    """返回 (范围文本, 中文说明, 数据来源)。取不到返回 None。"""
    from . import preflop as _pf
    pos = (pos or "").upper()
    opponent = (opponent or "").upper()
    base_pos = _POS_FALLBACK.get(pos, pos)
    t = vs_type if vs_type not in (None, "", "*", "任意") else "标准"
    try:
        if act == "open":
            return _pf.get(base_pos, opponent), f"{pos} 开池范围", "课程开池表"
        if act == "3bet":
            spec = _pf.threebet(pos, opponent)
            if spec:
                return spec, f"{pos} 对 {opponent} 的 3bet 范围", "GTO 对位表"
        if act == "call":
            if raises_before <= 1:
                spec = _pf.threebet_call(pos, opponent)
                if spec:
                    return spec, f"{pos} 对 {opponent} 开池的跟注范围", "GTO 平跟表"
                return _pf.get(base_pos, opponent), f"{pos} 的对位范围（近似）", "按开池表近似"
            from .playertypes import CALL_3BET_RANGE, CALL_4BET_RANGE
            if raises_before == 2:
                spec = CALL_3BET_RANGE.get(t) or CALL_3BET_RANGE.get("标准")
                return spec, f"{pos} 跟注 3bet 的范围", "课程跟注 3bet 表"
            spec = CALL_4BET_RANGE.get(t) or CALL_4BET_RANGE.get("标准")
            return spec, f"{pos} 跟注 4bet 的范围", "课程跟注 4bet 表"
        if act == "4bet":
            from .playertypes import FOURBET_RANGE
            spec = FOURBET_RANGE.get(t) or FOURBET_RANGE.get("标准")
            return spec, f"{pos} 的 4bet 范围", "课程 4bet 表"
        if act == "5bet":
            from .playertypes import FIVEBET_RANGE
            spec = FIVEBET_RANGE.get(t) or FIVEBET_RANGE.get("标准")
            return spec, f"{pos} 5bet 全下的范围", "课程 5bet 表"
    except Exception:
        return None, "", ""
    return None, "", ""


def _combo_set(spec: str | None):
    if not spec:
        return None
    try:
        from .ranges import parse_range
        return {(c[0], c[1]) for c in parse_range(spec)}
    except Exception:
        return None


def _pct(spec: str | None) -> float | None:
    s = _combo_set(spec)
    if s is None:
        return None
    return round(len(s) / 1326 * 100, 1)


def resolve(hero: str, villain: str, line: str,
            vs_type: str = "标准") -> dict:
    """把一条翻前序列还原成翻后双方的精确范围。

    返回 dict：
      ok           序列是否可用（False → 调用方回退到旧的位置启发式）
      pot          从加注轮次推出的池型
      hero_range / villain_range   范围文本（可能为空）
      hero_set / villain_set       具体组合集合（可能为 None）
      hero_action / villain_action 各自最后的动作码
      label / note 给 UI 的一句话
    """
    hero = (hero or "").upper()
    villain = (villain or "").upper()
    steps = parse(line)
    empty = {"ok": False, "pot": "", "hero_range": None, "villain_range": None,
             "hero_set": None, "villain_set": None, "hero_action": "",
             "villain_action": "", "hero_spec_pct": None, "villain_spec_pct": None,
             "label": "", "note": "没有翻前序列，按位置启发式取范围",
             "hero_label": "", "villain_label": "", "hero_source": "",
             "villain_source": "", "line": format(steps)}
    if not steps or not hero:
        return empty

    # 每个位置最后一次动作。弃牌也要记 —— 「开池后被 3bet 弃牌」的 hero
    # 不能还被当成开池方，否则会给出一个根本不存在的翻后范围。
    last: dict[str, tuple[int, str]] = {}
    for i, s in enumerate(steps):
        last[s["pos"]] = (i, s["act"])

    if hero not in last:
        return dict(empty, line=format(steps),
                    note="序列里没有我，回退到位置启发式")

    # 对手：优先传入的 villain（且没弃牌）；否则取另一个还在局里的人
    alive_others = [p for p, (_i, a) in last.items() if p != hero and a != "fold"]
    if villain in last and last[villain][1] != "fold":
        vpos = villain
    elif alive_others:
        vpos = alive_others[0]
    else:
        vpos = villain
    n_raises = sum(1 for s in steps if s["act"] in _RAISES)
    # 人数只算还在牌局里的（弃牌的人不参与翻后，不能把 3bet 底池标成三人池）
    folded = {s["pos"] for s in steps if s["act"] == "fold"}
    players = len({s["pos"] for s in steps if s["pos"] not in folded})
    pot = _pot_of(n_raises, players)

    hi, hact = last[hero]
    if hact == "fold":
        # 我已经弃牌，没有翻后范围
        return dict(empty, pot=pot, line=format(steps), label=format(steps),
                    note="我在翻前已经弃牌，没有翻后范围")
    hero_before = _raises_before(steps, hi)
    hero_spec, hero_label, hero_src = _spec_and_label(hero, hact, vpos, hero_before, vs_type)

    v_spec = v_label = v_src = None
    v_act = ""
    if vpos and vpos in last:
        vi, v_act = last[vpos]
        v_before = _raises_before(steps, vi)
        v_spec, v_label, v_src = _spec_and_label(vpos, v_act, hero, v_before, vs_type)
    else:
        v_label = f"{vpos} 的范围（不在序列里，按位置近似）"

    if hact == "fold" or v_act == "fold":
        note = "序列里有人弃牌，翻后只有一方：范围仅供参考"
    elif n_raises >= 4:
        note = "翻前已经 5bet 全下，正常没有翻后"
    else:
        note = ""

    label = " → ".join(f"{s['pos']} {_CN.get(s['act'], s['act'])}" for s in steps)
    hp, vp = _pct(hero_spec), _pct(v_spec)
    bits = []
    if hp is not None:
        bits.append(f"我方 {round(hp)}% 组合")
    if vp is not None:
        bits.append(f"对手 {round(vp)}% 组合")
    summary = " · ".join(bits)

    ok = bool(hero_spec)
    return {
        "ok": ok,
        "pot": pot,
        "hero_range": hero_spec, "villain_range": v_spec,
        "hero_set": _combo_set(hero_spec), "villain_set": _combo_set(v_spec),
        "hero_action": hact, "villain_action": v_act,
        "hero_spec_pct": hp, "villain_spec_pct": vp,
        "hero_label": hero_label, "villain_label": v_label or "",
        "hero_source": hero_src, "villain_source": v_src or "",
        "label": label, "summary": summary, "note": note,
        "line": format(steps), "raises": n_raises, "players": players,
    }


def card_combos(spec: str | None, board_cards=None) -> list[tuple[int, int]]:
    """范围文本 → 具体组合（去掉公共牌占用的牌）。"""
    s = _combo_set(spec)
    if not s:
        return []
    dead = set(board_cards or [])
    return [(a, b) for (a, b) in s if a not in dead and b not in dead]
