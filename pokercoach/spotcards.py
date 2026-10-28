"""把真实手牌的决策点（hh_spots）变成练习题。

和 scenecards 的区别：
  scenecards  → 题库概念题（从策略树生成，无具体牌面）
  spotcards   → 真实牌局题（用你打过的牌面/手牌当题面，答案是策略树给的打法）
"""
from __future__ import annotations

import random
from collections import Counter

RANK = "23456789TJQKA"
POT_MAP = {"3bet底池": "3BP", "3BP": "3BP", "单加注": "SRP", "SRP": "SRP",
           "4bet底池": "4BP", "4BP": "4BP", "4bet+": "4BP"}
# 没人下注 = 对手过牌；面对下注默认按小注处理（有 size 时再细分）
FACING_MAP = {"无人下注": "对手过牌", "面对下注": "对手小注", "": "对手过牌"}
STREET_MAP = {"flop": "翻牌", "turn": "转牌", "river": "河牌"}
SIZE_POOL = ["过牌", "下注 25% 池", "下注 33% 池", "下注 50% 池",
             "下注 66% 池", "下注 75% 池", "下注 100% 池", "下注 120% 池"]


def to_board_text(raw: str) -> str | None:
    """'3c 9c Ks' → 'K93tt'（tree 认识的紧凑写法）"""
    parts = [p for p in (raw or "").split() if len(p) >= 2]
    if len(parts) < 3:
        return None
    try:
        cards = [(p[0].upper(), p[1].lower()) for p in parts]
    except Exception:
        return None
    if any(c[0] not in RANK for c in cards):
        return None
    cards.sort(key=lambda c: -RANK.index(c[0]))
    ranks = "".join(c[0] for c in cards)
    for c in cards:
        ranks = ranks.replace("10", "T")
    suits = [c[1] for c in cards]
    n = len(set(suits))
    pat = "m" if n == 1 else ("tt" if n == 2 else "r")
    return ranks.replace("T", "T") + pat if len(parts) == 3 else ranks + pat


def role_of(row) -> str | None:
    """把「进攻/防守 + 位置」映射到策略树的角色"""
    r = (row["role"] or "").strip()
    hp, vp = (row["hero_pos"] or ""), (row["villain_pos"] or "")
    if not hp:
        return None
    if hp in ("SB",) or hp in ("BB",):
        # 盲注对盲注
        if vp in ("SB", "BB"):
            return "BvB-SB" if hp == "SB" else "BvB-BB"
    ip = _is_ip(hp, vp)
    if r == "进攻":
        return "IP-PFR" if ip else "OOP-PFR"
    if r == "防守":
        return "IP-caller" if ip else "OOP-caller"
    return None


# 翻后行动顺序（和翻前不同！BTN 是最后一个，所以最有利）
POSTFLOP = ["SB", "BB", "UTG", "HJ", "CO", "BTN"]
def _is_ip(hero: str, villain: str) -> bool:
    try:
        return POSTFLOP.index(hero) > POSTFLOP.index(villain)
    except ValueError:
        return False


def _norm_size(s: str) -> str | None:
    s = (s or "").strip()
    if not s or s in ("—", "-"):
        return None
    low = s.replace(" ", "")
    if "过牌" in low or "不下注" in low:
        return "过牌"
    if "全下" in low or "allin" in low:
        return "全下"
    if "%" in low and ("–" in low or "-" in low):
        return None
    if "%" in low:
        import re
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", low)
        if m:
            return f"下注 {m.group(1)}% 池"
    return None


def build_cards(store, tree_mod, tree_dir, limit: int = 60) -> list[dict]:
    rows = store.conn.execute(
        """SELECT street, role, pot_type, hero_pos, villain_pos, matchup,
                  board, hand, facing, action, size, net
           FROM hh_spots ORDER BY id DESC LIMIT 4000"""
    ).fetchall()
    out, seen = [], set()
    for row in rows:
        # 只出「轮到我主动决策」的题；面对下注的正确答案是跟/加/弃，
        # 不是下注尺度，混进来会给出错误答案。
        if (row["facing"] or "").strip() != "无人下注":
            continue
        pot = POT_MAP.get((row["pot_type"] or "").strip())
        street = STREET_MAP.get((row["street"] or "").strip())
        role = role_of(row)
        board_txt = to_board_text(row["board"])
        if not (pot and street and role and board_txt and row["hand"]):
            continue
        try:
            res = tree_mod.grid(tree_dir, pot, role, board_txt, street,
                                FACING_MAP.get((row["facing"] or "").strip(), "对手过牌"))
        except Exception:
            continue
        if not res.get("ok"):
            continue
        rule = res["rule"]
        size = _norm_size(rule.get("sizing"))
        if not size:
            continue
        key = f"{board_txt}|{row['hand']}|{street}|{pot}|{role}"
        if key in seen:
            continue
        seen.add(key)
        scene = f"真实牌局：{street}·{pot}·{role}"
        front = (f"{row['matchup'] or ''} · {pot} · {street} {row['board']} · "
                 f"你持 {row['hand']}，轮到你 → 打什么？").strip()
        pool = [x for x in SIZE_POOL if x != size]
        if "过牌" not in size and random.random() < 0.6:
            pool = ["过牌"] + [x for x in pool if x != "过牌"]
        opts = [size] + random.sample(pool, 3)
        random.shuffle(opts)
        out.append(dict(scene=scene, front=front,
                        back=f"{size}（策略树 {rule['rule_id']}：频率 {rule.get('freq') or '—'}）",
                        answer=size, options=opts, key=f"spot:{key}"))
        if len(out) >= limit:
            break
    return out
