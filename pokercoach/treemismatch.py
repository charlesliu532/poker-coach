"""按策略树检查真实决策的对错，找出错最多的节点。"""
from __future__ import annotations

import time
from collections import defaultdict

from . import tree as T
from .spotcards import POT_MAP, STREET_MAP, role_of, to_board_text

# 判定阈值：树给出该手牌类别的下注率
BET   = 60   # ≥60% 该下注
CHECK = 40   # ≤40% 该过牌

_GRID_CACHE: dict = {}     # grid 结果按 (pot, role, board, street) 缓存
_RESULT_CACHE: dict = {}   # 整份分析缓存 60 秒
_TTL = 60


def analyze(store, tree_dir, min_n: int = 12, limit: int = 40) -> dict:
    key = (str(tree_dir), min_n, limit)
    hit = _RESULT_CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    result = _analyze(store, tree_dir, min_n, limit)
    _RESULT_CACHE[key] = (time.time(), result)
    return result


def _analyze(store, tree_dir, min_n: int, limit: int) -> dict:
    rows = store.conn.execute(
        """SELECT street, role, pot_type, hero_pos, villain_pos, matchup,
                  board, hand, facing, action, size
           FROM hh_spots WHERE facing = '无人下注'"""
    ).fetchall()

    cache = {}
    agg = defaultdict(lambda: {"n": 0, "bad": 0, "miss_bet": 0, "over_bet": 0})
    examples = defaultdict(list)

    for row in rows:
        pot = POT_MAP.get((row["pot_type"] or "").strip())
        street = STREET_MAP.get((row["street"] or "").strip())
        role = role_of(row)
        board_txt = to_board_text(row["board"])
        act = (row["action"] or "").strip()
        if not (pot and street and role and board_txt) or act not in ("下注", "过牌"):
            continue
        key = (pot, role, board_txt, street)
        res = _GRID_CACHE.get(key)
        if res is None:
            try:
                res = T.grid(tree_dir, pot, role, board_txt, street, "对手过牌")
            except Exception:
                res = {"ok": False}
            _GRID_CACHE[key] = res
        if not res.get("ok"):
            continue
        # 找这手牌在桶表里的类别
        bucket = None
        for c in res["cells"]:
            if c.get("combo") == row["hand"]:
                bucket = c.get("bucket")
                break
        if bucket is None:
            continue

        node = (pot, street, role, res["rule"]["rule_id"])
        a = agg[node]
        a["n"] += 1
        wrong = None
        if bucket >= BET and act == "过牌":
            wrong = "miss_bet"
        elif bucket <= CHECK and act == "下注":
            wrong = "over_bet"
        if wrong:
            a["bad"] += 1
            a[wrong] += 1
            if len(examples[node]) < 3:
                examples[node].append({
                    "board": row["board"], "hand": row["hand"],
                    "action": act, "should": f"{bucket}% 下注率",
                    "matchup": row["matchup"] or "",
                })

    out = []
    for node, a in agg.items():
        if a["n"] < min_n:
            continue
        pot, street, role, rid = node
        out.append({
            "pot": pot, "street": street, "role": role, "rule": rid,
            "n": a["n"], "bad": a["bad"],
            "rate": round(a["bad"] / a["n"] * 100, 1),
            "miss_bet": a["miss_bet"], "over_bet": a["over_bet"],
            "examples": examples[node],
        })
    out.sort(key=lambda x: (-x["rate"], -x["n"]))
    return {"total_spots": len(rows), "nodes": out[:limit],
            "min_n": min_n, "bet_th": BET, "check_th": CHECK}
