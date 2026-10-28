"""用模型给题库打分，把「出得很差」的题筛掉。

一批一批问（默认 6 题一次），让模型按四个标准打分：
  1 题干自洽可回答  2 答案正确  3 干扰项似是而非  4 没有送分线索

分数写进 cards.quality，出题时只取 quality >= 阈值的卡。
没打分的（NULL）仍然可用，这样离线状态下一切照旧。
"""

from __future__ import annotations

import json
import re

from .quiz import make_question

SYSTEM = """你是扑克教学题库的审稿人。给你一批选择题，逐题打分（0-10）。

评分标准：
1. 题干是否自洽、可回答？残句、章节名、"XX：____"这种标签，直接 0-2 分。
2. 正确答案是否确实正确？按标准扑克理论判断，错了给 0 分。
3. 干扰项是否"似是而非"？同类型、同量级、懂一半的人会选错的，给高分；
   明显无关、跨类混搭（定义题里出现数字）给低分。
4. 有没有送分线索？题干里的关键词只出现在正确选项里 → 扣到 4 分以下。

只输出 JSON 数组，不要解释：
[{"id": 123, "score": 8, "reason": "干扰项同量级"}]
reason 不超过 15 个字。"""


def _extract_json(text: str):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def build_item(store, card) -> dict | None:
    q = make_question(store, card["id"])
    if not q:
        return None
    return {
        "id": card["id"],
        "q": q["q"],
        "options": q["options"],
        "answer": q["options"][q["answer"]],
        "kind": card["kind"],
    }


def score_cards(store, coach, *, batch: int = 6, limit: int | None = None, log=print) -> dict:
    rows = store.conn.execute(
        "SELECT id, kind, front, back FROM cards WHERE quality IS NULL ORDER BY random()"
    ).fetchall()
    if limit:
        rows = rows[:limit]

    items = []
    skipped = 0
    for r in rows:
        it = build_item(store, r)
        if it:
            items.append(it)
        else:
            skipped += 1

    log(f"待审 {len(rows)} 张，可出题 {len(items)} 张，出不了题 {skipped} 张")
    scored = 0
    failed = 0
    for chunk in _batches(items, batch):
        payload = json.dumps(chunk, ensure_ascii=False)
        try:
            raw = coach.chat(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": payload}],
                temperature=0,
                max_tokens=1200,
            )
            data = _extract_json(raw)
            if not data:
                failed += 1
                continue
            for row in data:
                cid, score = row.get("id"), row.get("score")
                if isinstance(cid, int) and isinstance(score, (int, float)):
                    store.set_quality(cid, int(max(0, min(10, score))))
                    scored += 1
            store.conn.commit()
            log(f"  已审 {scored}/{len(items)}")
        except Exception as e:
            failed += 1
            log(f"  ! 一批失败：{e}")

    # 出不了题的卡直接标 0 分，别让它们混进题库
    for r in rows:
        if not any(it["id"] == r["id"] for it in items):
            store.set_quality(r["id"], 0)
    store.conn.commit()
    return {"total": len(rows), "scored": scored, "unscorable": skipped, "failed_batches": failed}


def report(store) -> dict:
    rows = store.conn.execute(
        "SELECT quality, COUNT(*) AS n FROM cards GROUP BY quality ORDER BY quality"
    ).fetchall()
    dist = {r["quality"]: r["n"] for r in rows}
    good = store.conn.execute("SELECT COUNT(*) AS n FROM cards WHERE quality >= 6").fetchone()["n"]
    return {"distribution": dist, "good": good}


GEN_SYSTEM = """你是扑克教练，负责把课程笔记做成单选题。给你一段笔记，请出 1~2 道题。

硬性要求：
- 只考这段笔记里明确写了的内容，不要引入外部知识
- 题干必须能独立看懂：不能是"XX：____"这种残句，也不能依赖上下文
- 4 个选项，只有 1 个正确；干扰项要和正确项同类型、同量级（数字题就给同单位的数字）
- 正确答案放在第一个位置，其余三个是干扰项
- 题干和选项都不要太长（选项 ≤ 60 字）

只输出 JSON，不要解释：
{"cards":[{"q":"题干","options":["正确答案","干扰1","干扰2","干扰3"],"kind":"def","why":"依据笔记的哪一句"}]}
kind 取 def（概念）/ num（数字）/ principle（原则）。"""


def _chunks(store, limit: int, topics_filter: list[str] | None = None) -> list:
    """只取扑克相关、长度合适的片段——别把「时光机思维」这类笔记也拿来出题。"""
    from .topics import is_poker

    rows = store.conn.execute(
        """SELECT c.id, c.doc_id, c.text, c.heading, d.title
           FROM chunks c JOIN docs d ON d.id = c.doc_id
           WHERE length(c.text) BETWEEN 280 AND 1200
           ORDER BY RANDOM() LIMIT ?""",
        (limit * 6,),
    ).fetchall()
    picked = [r for r in rows if is_poker(f"{r['title']} {r['heading']} {r['text'][:600]}", 4)]
    if topics_filter:
        from .topics import best_topic
        picked = [r for r in picked if best_topic(r["title"]) in topics_filter]
    return picked[:limit]


def _valid_card(c: dict) -> bool:
    q = (c.get("q") or "").strip()
    opts = c.get("options") or []
    if not (10 <= len(q) <= 120) or len(opts) != 4:
        return False
    opts = [str(o).strip() for o in opts]
    if len(set(opts)) != 4 or any(not o or len(o) > 80 for o in opts):
        return False
    return True


def generate(store, coach, *, chunks: int = 40, topics_filter: list[str] | None = None, log=print) -> dict:
    """让模型读笔记片段，出题并自带干扰项；直接入库，质量分记 9。"""
    import hashlib
    import random

    from .store import now

    rows = _chunks(store, chunks, topics_filter)
    added = skipped = failed = 0
    for i, ch in enumerate(rows, 1):
        try:
            raw = coach.chat(
                [{"role": "system", "content": GEN_SYSTEM},
                 {"role": "user", "content": f"笔记标题：{ch['title']} / {ch['heading']}\n\n{ch['text'][:1200]}"}],
                temperature=0.2,
                max_tokens=900,
            )
            data = _extract_json(raw) if raw.strip().startswith("[") else None
            if data is None:
                m = re.search(r"\{.*\}", raw, re.S)
                data = json.loads(m.group(0)).get("cards", []) if m else []
        except Exception as e:
            failed += 1
            log(f"  ! {ch['heading'][:20]}: {e}")
            continue

        for c in data[:2]:
            if not _valid_card(c):
                skipped += 1
                continue
            q = c["q"].strip()
            opts = [str(o).strip() for o in c["options"]]
            key = hashlib.sha1(re.sub(r"[\s\W_]+", "", q).lower().encode()).hexdigest()[:16]
            exists = store.conn.execute("SELECT 1 FROM cards WHERE key = ?", (key,)).fetchone()
            if exists:
                skipped += 1
                continue
            store.conn.execute(
                "INSERT INTO cards(doc_id, front, back, tags, key, kind, quality, options, created) "
                "VALUES (?, ?, ?, ?, ?, ?, 9, ?, ?)",
                (ch["doc_id"], q, opts[0], ch["heading"] or ch["title"], key,
                 c.get("kind", "def"), json.dumps(opts, ensure_ascii=False), now()),
            )
            added += 1
        if i % 10 == 0:
            store.conn.commit()
            log(f"  {i}/{len(rows)} 段，已生成 {added} 题")
    store.conn.commit()
    return {"chunks": len(rows), "added": added, "skipped": skipped, "failed": failed}


RULE_SYSTEM = """你是扑克教练，从课程笔记里抽取"针对具体场景的建议"。

只抽取笔记里明确写了的内容，不要补充常识。每条规则填这些字段（没有的留空）：
street: flop|turn|river
role: 只能填 进攻 或 防守（进攻=我是翻前加注者，防守=我是跟注者）
high: A高|双高|单高|低牌
suit: 单色面|双花面|彩虹面
paired: 1|0
connected: 1|0
runout: 超张|成花|成顺|公对面|白板
oline: B|X|XR|XC
pot_type: SRP|3bet底池|4bet+
freq: 例如「下注 60~70%」「弃牌 80%+」
size: 例如「33% 池」「2/3 池」
why: 一句话原理（≤30字）
avoid: 一句话常见错误（≤30字）

输出 JSON：{"rules":[{...}]}
如果这段笔记没有具体的场景建议（只是概念解释），输出 {"rules":[]}。"""


def extract_rules(store, coach, *, chunks: int = 40, doc_filter: str = "", log=print) -> dict:
    """让模型把课程笔记变成结构化规则，存进 note_rules。"""
    from .store import now
    from .topics import is_poker

    sql = """SELECT c.id AS chunk_id, c.text, c.heading, d.title FROM chunks c JOIN docs d ON d.id = c.doc_id
             WHERE length(c.text) BETWEEN 300 AND 1100"""
    args: list = []
    if doc_filter:
        sql += " AND d.title LIKE ?"
        args.append(f"%{doc_filter}%")
    sql += " ORDER BY RANDOM() LIMIT ?"
    args.append(chunks * 5)
    rows = store.conn.execute(sql, args).fetchall()
    rows = [r for r in rows if is_poker(f"{r['title']} {r['heading']} {r['text'][:500]}", 5)][:chunks]

    added = skipped = failed = 0
    seen = set()
    for i, r in enumerate(rows, 1):
        try:
            raw = coach.chat(
                [{"role": "system", "content": RULE_SYSTEM},
                 {"role": "user", "content": f"《{r['title']}》/ {r['heading']}\n\n{r['text'][:1100]}"}],
                temperature=0, max_tokens=700,
            )
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0)) if m else {}
        except Exception as e:
            failed += 1
            log(f"  ! {e}")
            continue

        def norm(v) -> str:
            v = str(v or "").strip()
            if v in ("-", "无", "any", "全部", "null", "None"):
                return ""
            if "进攻" in v:
                return "进攻"
            if "防守" in v:
                return "防守"
            return v

        for rule in data.get("rules", [])[:2]:
            if not (rule.get("freq") and (rule.get("street") or rule.get("role"))):
                skipped += 1
                continue
            key = tuple(str(rule.get(k, "")) for k in
                        ("street", "role", "high", "suit", "paired", "connected", "runout", "oline", "pot_type", "freq"))
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            store.add_note_rule({**{k: norm(rule.get(k, "")) for k in
                                    ("street", "role", "high", "suit", "paired", "connected", "runout", "oline", "pot_type",
                                     "freq", "size", "why", "avoid")},
                                 "source_title": r["title"], "source_heading": r["heading"],
                                 "source_chunk": r["chunk_id"]})
            added += 1
        if i % 10 == 0:
            log(f"  {i}/{len(rows)} 段，已抽 {added} 条规则")
    return {"chunks": len(rows), "rules": added, "skipped": skipped, "failed": failed}
