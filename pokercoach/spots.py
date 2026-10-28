"""从策略树生成「一定有效」的场景题。

核心原则：
  1. 场景从策略树的真实节点取 → 场景一定合法
  2. 答案由树算出 → 一定正确
  3. 干扰项由「邻近合法值」生成 → 一定似是而非
  4. 模型只负责润色题面，不碰答案（可选）

不依赖模型也能出题。
"""
from __future__ import annotations

import random
from pathlib import Path

from . import tree as T

# 出题用的代表牌面（覆盖主要牌面类别）
BOARDS = [
    ("As7h2c", "高A彩虹"), ("AhKh2h", "高A天花"), ("Kc8d4s", "高K彩虹"),
    ("9s8s7d", "中连两色"), ("2c3d4h", "低连彩虹"), ("QdJdTd", "高连天花"),
    ("AcAd2h", "A公对"), ("7c7d2s", "公对"), ("Td9d5c", "断张两色"),
]
ROLES = ["IP-PFR", "OOP-PFR", "IP-caller", "OOP-caller"]
POTS = ["SRP", "3BP", "3人池"]
ACTS = ["对手过牌", "对手小注", "对手大注"]


def _scene_label(pot, role, street, action, board_name):
    cn = {"IP-PFR": "进攻方·有位置", "OOP-PFR": "进攻方·没位置",
          "IP-caller": "跟注方·有位置", "OOP-caller": "跟注方·没位置"}
    return f"{street}·{pot}·{cn.get(role, role)}｜{board_name}·{action}"


def _sizing_options(right: str, pool: list) -> list:
    """用邻近的合法尺度做干扰项，保证似是而非。"""
    cands = [right]
    for v in ["25%", "33%", "50%", "66%", "75%", "100%", "120%", "150%"]:
        if v != right and v not in cands:
            cands.append(v)
    others = [c for c in cands[1:] if c != right]
    random.shuffle(others)
    return [right] + others[:3]


def _freq_band(pct: float) -> str:
    if pct >= 80:
        return "80–100%"
    if pct >= 60:
        return "60–80%"
    if pct >= 40:
        return "40–60%"
    if pct >= 20:
        return "20–40%"
    return "0–20%"


def _freq_options(pct: float) -> list:
    right = _freq_band(pct)
    allb = ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]
    others = [b for b in allb if b != right]
    random.shuffle(others)
    return [right] + others[:3]


_SCENE_CACHE = {"key": None, "data": None}
_CACHE_FILE = "data/tree/.scenes.json"


def collect_scenes(root: Path, limit: int = 400) -> list:
    """遍历策略树，收集所有能出题的合法节点（按 rules.csv 修改时间缓存）。"""
    try:
        mt = (root / "rules.csv").stat().st_mtime
    except Exception:
        mt = 0
    key = (str(root), mt, limit)
    if _SCENE_CACHE["key"] == key and _SCENE_CACHE["data"] is not None:
        return _SCENE_CACHE["data"]

    # 磁盘缓存：第二次启动直接读，不再重算（冷启 30 秒 → 0.05 秒）
    import json as _json
    cache_path = root / ".scenes.json"
    try:
        # 只要有缓存就用（不再比 mtime——打包版启动时会重拷数据，mtime 会变新）
        if cache_path.exists() and cache_path.stat().st_size > 1000:
            data = _json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                _SCENE_CACHE["key"] = key
                _SCENE_CACHE["data"] = data
                return data
    except Exception:
        pass

    out = []
    for pot in POTS:
        for role in ROLES:
            for bd, bname in BOARDS:
                for street in ("翻牌", "转牌", "河牌"):
                    for ac in ACTS:
                        r = T.grid(root, pot, role, bd, street, ac,
                                   hero_pos="BTN", opp_pos="BB")
                        if not r.get("ok"):
                            continue
                        out.append({
                            "pot": pot, "role": role, "board": bd, "board_name": bname,
                            "street": street, "action": ac,
                            "label": _scene_label(pot, role, street, ac, bname),
                            "rule_id": r["rule"]["rule_id"],
                            "sizing": (r["rule"].get("sizing") or "").strip(),
                            "freq": r["rule"].get("freq") or "",
                            "range_bet_pct": r.get("range_bet_pct") or 0,
                            "board_class": r.get("board_class"),
                        })
                        if len(out) >= limit:
                            _save(out, cache_path)
                            _SCENE_CACHE["key"] = key
                            _SCENE_CACHE["data"] = out
                            return out
    _save(out, cache_path)
    _SCENE_CACHE["key"] = key
    _SCENE_CACHE["data"] = out
    return out


def _save(data, path):
    try:
        import json as _json
        path.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def make_questions(root: Path, n: int = 3, filters: dict | None = None,
                   seed: int | None = None) -> list:
    """生成 n 道场景题。每题都带正确答案，且答案一定在选项里。"""
    if seed is not None:
        random.seed(seed)
    scenes = collect_scenes(root)
    if not scenes:
        return []

    f = filters or {}
    def match(s):
        for k in ("pot", "role", "street", "board"):
            if f.get(k) and s.get(k) != f[k]:
                return False
        return True
    pool = [s for s in scenes if match(s)] or scenes
    random.shuffle(pool)

    qs = []
    for s in pool:
        if len(qs) >= n:
            break
        # 只出「尺度题」和「频率题」——这两类答案能由树唯一确定
        kind = "size" if (s["sizing"] and any(c.isdigit() for c in s["sizing"])) else "freq"
        if kind == "size":
            right = s["sizing"]
            opts = _sizing_options(right, [])
            q = {
                "front": f"{s['label']}，这个节点该用多大尺度？",
                "options": opts, "answer": right,
                "kind": "size",
                "tags": f"{s['street']} / {s['pot']} / 尺度",
                "explain": f"树里这条线（{s['rule_id']}）给的尺度是 {right}，"
                           f"整体下注率 {s['range_bet_pct']}%。",
            }
        else:
            pct = float(s["range_bet_pct"] or 0)
            right = _freq_band(pct)
            opts = _freq_options(pct)
            q = {
                "front": f"{s['label']}，整体下注频率落在哪一档？",
                "options": opts, "answer": right,
                "kind": "freq",
                "tags": f"{s['street']} / {s['pot']} / 频率",
                "explain": f"树里这条线（{s['rule_id']}）的范围下注率是 {pct}%。",
            }
        q["scene"] = s
        qs.append(q)
    return qs


def validate_question(q: dict) -> bool:
    """题目自检：答案必须在选项里，选项不能重复，至少 3 个选项。"""
    opts = [str(o) for o in (q.get("options") or [])]
    ans = str(q.get("answer") or "")
    return (len(opts) >= 3 and len(set(opts)) == len(opts) and ans in opts)
