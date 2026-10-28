"""从策略树生成「场景练习」题。

逻辑：每条有明确尺度的规则 → 一道题（问这个节点的建议动作/尺度）。
这样练习就不再依赖手写，策略树一改，题库跟着变。
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

ROLE_CN = {"IP-PFR": "进攻方·有位置", "OOP-PFR": "进攻方·无位置",
           "IP-caller": "跟注方·有位置", "OOP-caller": "跟注方·无位置",
           "BvB-SB": "小盲", "BvB-BB": "大盲"}
POT_CN = {"SRP": "单加注池", "3BP": "3bet 池", "3BP多人": "3bet 多人池",
          "4BP": "4bet 池", "多人池": "多人池", "翻前": "翻前"}
STREET_CN = {"翻牌": "翻牌", "转牌": "转牌", "河牌": "河牌", "翻前": "翻前"}

# 尺度池：用来造干扰项
SIZE_POOL = ["过牌", "下注 25% 池", "下注 33% 池", "下注 50% 池", "下注 66% 池",
             "下注 75% 池", "下注 100% 池", "下注 120% 池", "下注 150% 池"]

def _clean_size(s: str) -> str | None:
    """把规则里的尺度统一成选项文案；归一不了的宁可跳过，也不出烂题。"""
    s = (s or "").strip()
    if not s or s in ("—", "-") or len(s) > 40:
        return None
    low = s.replace(" ", "")
    if "过牌" in low or low.startswith("不下注") or "只打价值" in low:
        return "过牌"
    if "全下" in low or "all-in" in low.lower():
        return "全下"
    if "极化" in low and "%" in low:
        return None                       # 区间型极化尺度，不适合做单选
    if "%" in low and ("–" in low or "-" in low):
        return None                       # 区间型，跳过
    if "%" in low:
        import re as _re
        m = _re.search(r"(\d+(?:\.\d+)?)\s*%", low)
        if m:
            return f"下注 {m.group(1)}% 池"
    return None

def build_cards(tree_dir: Path, limit: int = 400) -> list[dict]:
    path = Path(tree_dir) / "rules.csv"
    if not path.exists():
        return []
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8"))
            if r.get("status") == "active" and (r.get("conf") or "") != "低"]
    out, seen = [], set()
    for r in rows:
        size = _clean_size(r.get("sizing"))
        if not size:
            continue
        street = r["street"]
        pot = r["pot_type"]
        role = r["role"]
        if street == "翻前" or pot not in POT_CN:
            continue
        scene = f"场景练习：{street}·{role}·{pot}"
        board = r.get("board_class") or "*"
        btxt = board if board != "*" else "任意牌面"
        q = f"{STREET_CN.get(street, street)}·{POT_CN.get(pot, pot)}·{ROLE_CN.get(role, role)}｜{btxt}，建议怎么打？"
        # 正确答案就是规则给的尺度；干扰项从尺度池里取
        opts = [size]
        pool = [x for x in SIZE_POOL if x != size]
        random.shuffle(pool)
        opts += pool[:3]
        random.shuffle(opts)
        if q in seen:          # 同一题面只出一道，避免「同题不同答案」
            continue
        seen.add(q)
        out.append(dict(scene=scene, front=q, back=f"{size}｜频率 {r.get('freq') or '—'}",
                        answer=size, options=opts,
                        note=r.get("note") or "", rule_id=r["rule_id"],
                        key=f"scene:{r['rule_id']}:{(r.get('board_class') or '*')}"))
        if len(out) >= limit:
            break
    return out
