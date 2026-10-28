"""题库：把复习卡变成选择题。

三类题：
- 定义题：「Blocker」是什么意思？  干扰项是别的术语的解释
- 数字题：面对 1/2 池下注，MDF 是 ____？  干扰项是同单位的其他数字
- 结论题：这一节最重要的结论是？  干扰项是别节的结论

全部由卡片确定性生成（同一张卡每次选项顺序一致），所以不需要存题目表。
"""

from __future__ import annotations

import random
import re
from collections import defaultdict

from . import facts, topics

LEVELS = topics.topic_names()  # 翻前基础 … 心理与资金，本身就是课程顺序


def level_of_topic(topic: str) -> int:
    try:
        return LEVELS.index(topic) + 1
    except ValueError:
        return len(LEVELS) + 1


def _doc_topics(store) -> dict[int, str]:
    out = {}
    for row in store.conn.execute("SELECT id, title FROM docs"):
        out[row["id"]] = topics.best_topic(row["title"]) or "其他"
    return out


def _cards(store) -> list[dict]:
    doc_topic = _doc_topics(store)
    rows = store.conn.execute(
        "SELECT id, doc_id, front, back, tags, kind, quality, options FROM cards "
        "WHERE kind IN ('def','num','principle','spot') AND (quality IS NULL OR quality >= 6)"
    ).fetchall()
    out = []
    for r in rows:
        topic = doc_topic.get(r["doc_id"], "其他")
        out.append(
            {
                "id": r["id"], "front": r["front"], "back": r["back"], "tags": r["tags"],
                "kind": r["kind"], "topic": topic, "level": level_of_topic(topic),
                "options": r["options"],
            }
        )
    return out


def _unit(text: str) -> str:
    if "%" in text or "％" in text:
        return "%"
    if "bb" in text.lower():
        return "bb"
    return ""


_STEM_NOISE = re.compile(r"(?:\s*9{3,}|\s*0{4,})")


def _clean_stem(text: str) -> str:
    s = re.sub(r"^\s*\d+[\.、]\s*", "", text or "")
    s = _STEM_NOISE.sub("", s)
    return s.strip()


def _opt_key(text: str) -> str:
    """把选项归一化后比较，避免出现 60BB / 60bb 这种"看起来一样"的干扰项。"""
    v, u = _value(text), _unit(text)
    if v is not None and u:
        return f"num:{v}:{u}"
    return re.sub(r"[\s，。、]+", "", text).lower()


def _pick(rng: random.Random, pool: list[dict], correct: dict, k: int = 3) -> list[dict]:
    """挑干扰项：长度接近、答案不重复、尽量来自不同主题。"""
    target_len = len(correct["back"])
    base_key = _opt_key(correct["back"])
    cands = [
        c for c in pool
        if _opt_key(c["back"]) != base_key
        and abs(len(c["back"]) - target_len) <= max(25, target_len * 0.6)
    ]
    # 优先不同主题，不够再放宽
    preferred = [c for c in cands if c["topic"] != correct["topic"]]
    for group in (preferred, cands):
        rng.shuffle(group)
        seen, out = set(), []
        for c in group:
            key = _opt_key(c["back"])
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
            if len(out) >= k:
                return out
        if len(out) >= k:
            return out
    return []


def _def_question(rng, card, pool) -> dict | None:
    # 干扰项只能是"定义"：不能混进数字卡、花括号、箭头
    cands = [
        c for c in pool
        if c["kind"] == "def"
        and not any(ch in c["back"] for ch in "{}|→")
        and 0.5 <= len(c["back"]) / max(len(card["back"]), 1) <= 2.0
    ]
    ds = _pick(rng, cands, card, 3)
    if len(ds) < 3:
        return None
    options = [card["back"]] + [d["back"] for d in ds]
    order = list(range(4))
    rng.shuffle(order)
    return {
        "id": card["id"],
        "level": card["level"],
        "topic": card["topic"],
        "kind": "def",
        "q": card["front"],
        "options": [options[i] for i in order],
        "answer": order.index(0),
        "explain": f"出自《{card['tags'].split(' / ')[-1] or card['topic']}》",
    }


def _short_value(text: str) -> bool:
    """答案是不是"纯数值"，比如 33% / 30BB，而不是一整句话。"""
    return len(text) <= 8 and bool(re.search(r"\d", text))


def _value(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def _num_question(rng, card, pool) -> dict | None:
    unit = _unit(card["back"])
    mine = _value(card["back"]) or 0
    # 首选：从正确答案本身推导干扰项（同单位、数量级接近）
    if mine and unit:
        correct = card["back"].strip()
        options = [correct] + facts.numeric_options(mine, unit, rng)
        order = list(range(4))
        rng.shuffle(order)
        return {
            "id": card["id"],
            "level": card["level"],
            "topic": card["topic"],
            "kind": "num",
            "q": _clean_stem(card["front"]),
            "options": [options[i] for i in order],
            "answer": order.index(0),
            "explain": f"出自《{card['tags'].split(' / ')[-1] or card['topic']}》",
        }
    short = [
        c for c in pool
        if c["kind"] == "num" and _unit(c["back"]) == unit
        and c["back"] != card["back"] and _short_value(c["back"])
    ]
    # 干扰项要"像"：数量级接近，别拿 1bb 和 100bb 放一起
    near = [
        c for c in short
        if _value(c["back"]) and mine and 0.4 * mine <= _value(c["back"]) <= 2.5 * mine
    ]
    ds = _pick(rng, near, card, 3) if len(near) >= 3 else _pick(rng, short, card, 3)
    if len(ds) < 3:
        return None
    options = [card["back"]] + [d["back"] for d in ds]
    order = list(range(4))
    rng.shuffle(order)
    return {
        "id": card["id"],
        "level": card["level"],
        "topic": card["topic"],
        "kind": "num",
        "q": card["front"] if len(card["front"]) <= 110 else card["front"][:108] + "…",
        "options": [options[i] for i in order],
        "answer": order.index(0),
        "explain": f"出自《{card['tags'].split(' / ')[-1] or card['topic']}》",
    }


def _principle_question(rng, card, pool) -> dict | None:
    ds = _pick(rng, [c for c in pool if c["kind"] == "principle"], card, 3)
    if len(ds) < 3:
        ds = _pick(rng, pool, card, 3)
    if len(ds) < 3:
        return None
    options = [card["back"]] + [d["back"] for d in ds]
    order = list(range(4))
    rng.shuffle(order)
    return {
        "id": card["id"],
        "level": card["level"],
        "topic": card["topic"],
        "kind": "principle",
        "q": card["front"],
        "options": [options[i] for i in order],
        "answer": order.index(0),
        "explain": "出自你自己的笔记",
    }


_BUILDERS = {"def": _def_question, "num": _num_question, "principle": _principle_question}


def _valid(q: dict) -> bool:
    """最后一道闸：选项重复、长度悬殊、答案能被关键词直接对上，都不收。"""
    opts = q["options"]
    if len({_opt_key(o) for o in opts}) != 4:
        return False
    lens = [len(o) for o in opts]
    if max(lens) > min(lens) * 3.5 + 20:
        return False
    stem = q["q"]
    tokens = {t.lower() for t in re.findall(r"[A-Za-z]{3,}", stem)}
    if tokens:
        hits = [sum(1 for t in tokens if t in o.lower()) for o in opts]
        # 只有正确答案提到题干里的英文术语 → 白送分
        if hits[q["answer"]] == 1 and sum(1 for h in hits if h) == 1:
            return False
    return True


def make_question(store, card_id: int) -> dict | None:
    """按 card_id 重建同一道题（选项顺序可复现）。负数 id 是内置事实题。"""
    if card_id < 0:
        return facts.fact_question(-1000 - card_id)
    cards = _cards(store)
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        return None
    rng = random.Random(f"q{card_id}")
    # 模型生成的卡自带 4 个选项（第一个是正确答案），直接用
    if card.get("options"):
        import json as _json
        try:
            opts = _json.loads(card["options"])
        except Exception:
            opts = None
        if opts and len(opts) == 4 and len(set(opts)) == 4:
            order = list(range(4))
            rng.shuffle(order)
            return {
                "id": card["id"],
                "level": card["level"],
                "topic": card["topic"],
                "kind": card["kind"],
                "q": card["front"],
                "options": [opts[i] for i in order],
                "answer": order.index(0),
                "explain": f"出自《{card['tags'].split(' / ')[-1] or card['topic']}》",
            }
    builder = _BUILDERS.get(card["kind"])
    q = builder(rng, card, cards) if builder else None
    return q if q and _valid(q) else None


def questions_for_level(store, level: int, n: int = 10, fresh: bool = True) -> list[dict]:
    cards = [c for c in _cards(store) if c["level"] == level]
    done = set()
    if fresh:
        done = {
            r["card_id"]
            for r in store.conn.execute("SELECT card_id FROM quiz_attempts WHERE correct = 1 AND level = ?", (level,))
        }
        remaining = [c for c in cards if c["id"] not in done]
        if len(remaining) >= 4:  # 剩下的太少就放回全部，避免没题可出
            cards = remaining
    rng = random.Random(f"lvl{level}")
    rng.shuffle(cards)
    out = facts.facts_for_level(level, limit=3, exclude=done)
    seen = set()
    for c in cards:
        if c["id"] in seen:
            continue
        q = make_question(store, c["id"])
        if not q:
            continue
        seen.add(c["id"])
        out.append({k: v for k, v in q.items() if k != "answer"})
        if len(out) >= n:
            break
    return out



# ══ 关卡归属：按内容关键词判定，比文档标题更准 ══════════════════
LEVEL_KEYWORDS = {
    "翻前基础": ["rfI", "开池", "vpip", "pfr", "limp", "位置", "翻前", "open"],
    "3bet 与 4bet": ["3bet", "4bet", "3-bet", "冷跟", "squeeze", "挤压", "再加注"],
    "翻牌持续下注": ["cbet", "持续下注", "翻牌", "flop", "c-bet", "check-raise", "过牌加注"],
    "转牌与双枪": ["转牌", "turn", "双枪", "二次开火", "barrel"],
    "河牌与抓诈唬": ["河牌", "river", "抓诈", "摊牌", "blocker", "阻断", "价值下注"],
    "多人底池": ["多人", "三人", "multiway", "3-way", "3人", "4人", "squeeze"],
    "剥削与调整": ["剥削", "调整", "玩家类型", "鱼", "常客", "读牌", "倾向", "偏离"],
    "心理与资金": ["心态", "情绪", "tilt", "资金", "波动", "bankroll", "止损", "上头"],
}


def card_level_by_content(card: dict, fallback: int) -> int:
    """按题干+答案里的关键词判定关卡；判不出来就用文档主题。"""
    text = f"{card.get('front') or ''} {card.get('back') or ''} {card.get('tags') or ''}".lower()
    best, best_hits = fallback, 0
    for i, topic in enumerate(LEVELS, 1):
        hits = sum(1 for kw in LEVEL_KEYWORDS.get(topic, []) if kw.lower() in text)
        if hits > best_hits:
            best, best_hits = i, hits
    return best if best_hits else fallback


TARGET_PER_LEVEL = 50       # 每关目标题量
MAX_PER_LEVEL = 70          # 超过这个数就把多余的挪去「其他」

def level_summary(store) -> list[dict]:
    cards = _cards(store)
    # 先用内容关键词重判每张卡的关卡
    for c in cards:
        c["_lv"] = card_level_by_content(c, c["level"])

    # 配额：超过上限的挪到「其他」，不足的从「其他」借（按关键词已归好的优先）
    by_lv = defaultdict(list)
    for c in cards:
        by_lv[c["_lv"]].append(c)
    other = by_lv.get(len(LEVELS) + 1, [])
    for lv_i in range(1, len(LEVELS) + 1):
        lst = by_lv[lv_i]
        if len(lst) > MAX_PER_LEVEL:
            other.extend(lst[MAX_PER_LEVEL:])
            by_lv[lv_i] = lst[:MAX_PER_LEVEL]
    for lv_i in range(1, len(LEVELS) + 1):
        need = TARGET_PER_LEVEL - len(by_lv[lv_i])
        if need > 0 and other:
            topic = LEVELS[lv_i - 1]
            # 优先借「关键词也能沾上边」的卡
            scored = []
            for c in other:
                text = f"{c.get('front') or ''} {c.get('back') or ''}".lower()
                hits = sum(1 for kw in LEVEL_KEYWORDS.get(topic, []) if kw.lower() in text)
                scored.append((hits, c))
            scored.sort(key=lambda x: -x[0])
            take = [c for h, c in scored[:need]]
            for c in take:
                other.remove(c)
                by_lv[lv_i].append(c)

    per = defaultdict(int)
    for lv_i, lst in by_lv.items():
        per[lv_i] = len(lst)
    done = defaultdict(int)
    correct_ids = {
        r["card_id"] for r in store.conn.execute("SELECT DISTINCT card_id FROM quiz_attempts WHERE correct = 1")
    }
    for c in cards:
        if c["id"] in correct_ids:
            done[c["_lv"]] += 1

    out = []
    for i, topic in enumerate(LEVELS + ["其他"], 1):
        total = per.get(i, 0)
        out.append(
            {
                "level": i,
                "topic": topic,
                "total": total,
                "solved": done.get(i, 0),
                "pct": round(done.get(i, 0) / total * 100) if total else 0,
            }
        )
    return out


def questions_by_scene(store, scene: str, n: int = 10) -> list[dict]:
    rows = store.conn.execute(
        "SELECT id FROM cards WHERE kind = 'spot' AND tags LIKE ? ORDER BY id DESC LIMIT ?",
        (f"%{scene}%", n * 2),
    ).fetchall()
    out = []
    for r in rows:
        q = make_question(store, r["id"])
        if q:
            out.append({k: v for k, v in q.items() if k != "answer"})
        if len(out) >= n:
            break
    return out


def scenes(store) -> list[dict]:
    rows = store.conn.execute(
        "SELECT tags, COUNT(*) AS n FROM cards WHERE kind = 'spot' GROUP BY tags ORDER BY n DESC"
    ).fetchall()
    return [{"scene": r["tags"], "n": r["n"]} for r in rows]
