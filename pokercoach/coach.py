"""教练层：检索 + 计算 + 可选的 LLM 解释。

没有 API Key 也能用：返回引用片段、算好的数字，以及一份可以直接粘贴给任何模型的提问包。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from . import odds as odds_mod
from .equity import equity as equity_fn
from .index import BM25, snippet

SYSTEM_PROMPT = """你是我的私人扑克复盘教练，我打线上现金局。

严格遵守：
1. 只依据【资料】回答，引用处用 [1][2] 标注。资料没覆盖的，直接说"你的资料里没有这块"，再给通用建议并明确标注是通用建议，不要编造我的笔记内容。
2. 所有胜率、EV、赔率数字只能引用【计算】里的结果。没有给计算结果的，就说需要先用计算器算，禁止自己心算或估算。
3. 回答按这个结构，简短、不客套：
   - 结论（1~2 句）
   - 依据（引用资料，指出和我笔记哪条对应/冲突）
   - 具体动作（翻前/翻牌/转牌/河牌分别怎么做，给尺度和频率）
   - 一个练习（我下一场能立刻执行的一个检查点）
4. 如果我笔记里的说法和主流 GTO 有冲突，指出来并说明差在哪。"""


def _fmt_ts(sec) -> str:
    if sec is None:
        return ""
    sec = float(sec)
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


class Coach:
    def __init__(self, store, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.store = store
        self.api_key = (
            api_key
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("POKERCOACH_API_KEY")
            or store.get_setting("api_key", "")
        )
        self.model = model or store.get_setting("model", os.environ.get("POKERCOACH_MODEL", "deepseek-chat"))
        self.base_url = (base_url or store.get_setting("base_url", os.environ.get("POKERCOACH_BASE_URL", "https://api.deepseek.com"))).rstrip("/")
        self.bm25 = None
        self.rebuild()

    def configure(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        """运行时改配置：立刻生效，并存进本地设置（下次启动还在）。"""
        if api_key is not None:
            self.api_key = api_key.strip()
            self.store.set_setting("api_key", self.api_key)
        if model:
            self.model = model.strip()
            self.store.set_setting("model", self.model)
        if base_url:
            self.base_url = base_url.strip().rstrip("/")
            self.store.set_setting("base_url", self.base_url)

    def config_info(self) -> dict:
        key = self.api_key or ""
        return {
            "configured": bool(key),
            "model": self.model,
            "base_url": self.base_url,
            "key_tail": ("…" + key[-4:]) if len(key) >= 4 else "",
        }

    # ---------------- 索引 ----------------

    def rebuild(self) -> int:
        rows = self.store.all_chunks()
        docs = [
            {
                "chunk_id": r["id"],
                "doc_id": r["doc_id"],
                "text": r["text"],
                "heading": r["heading"],
                "title": r["title"],
                "path": r["path"],
                "kind": r["kind"],
                "start": r["start"],
                "end": r["end"],
            }
            for r in rows
        ]
        self.bm25 = BM25(docs)
        return len(docs)

    def search(self, query: str, k: int = 6) -> list[dict]:
        if not self.bm25 or not self.bm25.docs:
            return []
        out = []
        for score, d in self.bm25.search(query, limit=max(k * 3, 12)):
            out.append(
                {
                    "score": score,
                    "chunk_id": d["chunk_id"],
                    "doc_id": d["doc_id"],
                    "title": d["title"],
                    "kind": d["kind"],
                    "heading": d["heading"],
                    "text": d["text"],
                    "preview": snippet(d["text"], query),
                    "start": d["start"],
                    "end": d["end"],
                    "time": _fmt_ts(d["start"]),
                }
            )
        # 汇总/摘要类资料信息密度更高，同等相关度下优先给它
        for h in out:
            if _is_summary(h["title"]):
                h["boosted"] = True
        out.sort(key=lambda h: h["score"] * (1.25 if h.get("boosted") else 1.0), reverse=True)
        return out[:k]

    # ---------------- 学习地图 / 计划 ----------------

    def outline(self) -> list[dict]:
        rows = self.store.all_chunks()
        docs: dict[int, dict] = {}
        for r in rows:
            d = docs.setdefault(
                r["doc_id"],
                {"doc_id": r["doc_id"], "title": r["title"], "kind": r["kind"], "chunks": 0, "sections": []},
            )
            d["chunks"] += 1
            head = (r["heading"] or "").split(" / ")[-1]
            if head and head not in d["sections"] and len(d["sections"]) < 40:
                d["sections"].append(head)
        counts = {
            row["doc_id"]: row["n"]
            for row in self.store.conn.execute("SELECT doc_id, COUNT(*) AS n FROM cards GROUP BY doc_id")
        }
        for d in docs.values():
            d["cards"] = counts.get(d["doc_id"], 0)
        return sorted(docs.values(), key=lambda d: (-d["cards"], -d["chunks"]))

    def plan(self, minutes: int = 25) -> dict:
        """不用模型、不花 token 的每日计划：先复习到期卡片，再精读薄弱章节。"""
        due = [dict(r) for r in self.store.due_cards(limit=20)]
        docs = self.outline()
        reading = []
        for d in docs:
            if not d["sections"]:
                continue
            for head in d["sections"][:2]:
                reading.append({"doc_id": d["doc_id"], "title": d["title"], "heading": head})
            if len(reading) >= 4:
                break
        card_min = max(5, min(minutes - 10, len(due) * 1))
        return {
            "minutes": minutes,
            "cards": due[:12],
            "due_total": len(due),
            "reading": reading,
            "split": {"cards": card_min, "reading": max(10, minutes - card_min)},
            "note": "先做卡片再看资料：回忆比重读有效。读的时候只读你答错的那一节。",
        }

    # ---------------- 从问题里自动抓计算 ----------------

    def auto_math(self, question: str) -> dict | None:
        q = question.replace("１０", "10")
        pot = _num_after(q, r"底池\s*[:：]?\s*")
        bet = _num_after(q, r"(?:对手)?下注\s*[:：]?\s*")
        win = _num_after(q, r"(?:胜率|equity)\s*[:：]?\s*([0-9.]+)\s*%")

        hand_like = re.findall(r"(?<![2-9TJQKA])[2-9TJQKA]{2}[SO]?(?![2-9TJQKA])", q.upper())
        specific = re.findall(r"(?:[2-9TJQKA][shdc]){2}", q, flags=re.IGNORECASE)
        board = _find_board(q)
        result: dict = {}
        if pot is not None and bet is not None:
            pct = win / 100 if win is not None else None
            result["odds"] = odds_mod.analyze(pot, bet, pct)

        def looks_like_range(tok: str) -> bool:
            return bool(re.fullmatch(r"[2-9TJQKA]{2}[SO]?", tok)) and tok[0] != tok[1]

        a = b = None
        if len(specific) >= 4:
            a, b = "".join(specific[:2]), "".join(specific[2:4])
        elif len(specific) == 2:
            a, b = specific[0], specific[1]
        elif len(hand_like) >= 2:
            cleaned = [t for t in hand_like if looks_like_range(t) or re.fullmatch(r"([2-9TJQKA])\1", t)]
            if len(cleaned) >= 2:
                a, b = cleaned[0], cleaned[1]
        if a and b:
            try:
                res = equity_fn(a, b, board or (), n_samples=20000)
                result["equity"] = res.to_dict()
                result["equity"]["hero"] = a
                result["equity"]["villain"] = b
            except Exception as e:  # 解析失败就算了，不影响回答
                result["equity_error"] = str(e)
        return result or None

    # ---------------- 提问 ----------------

    def ask(self, question: str, k: int = 6) -> dict:
        sources = self.search(question, k=k)
        math = self.auto_math(question)
        prompt = self._build_prompt(question, sources, math)
        base = {"question": question, "sources": sources, "math": math, "prompt": prompt}

        if not self.api_key:
            return {**base, "mode": "offline", "answer": _offline_answer(sources, math)}
        try:
            answer = self._call_llm(prompt)
            return {**base, "mode": "llm", "answer": answer}
        except Exception as e:
            return {**base, "mode": "error", "error": str(e), "answer": _offline_answer(sources, math)}

    def _build_prompt(self, question: str, sources: list[dict], math: dict | None) -> str:
        ctx = []
        for i, s in enumerate(sources, 1):
            where = s["title"]
            if s["heading"]:
                where += f" / {s['heading']}"
            if s["time"]:
                where += f" @{s['time']}"
            ctx.append(f"[{i}] {where}\n{s['text']}")
        math_txt = json.dumps(math, ensure_ascii=False, indent=2) if math else "（无）"
        return (
            f"【资料】\n" + ("\n\n".join(ctx) if ctx else "（我的资料库里没有相关内容）") + "\n\n"
            f"【计算】\n{math_txt}\n\n"
            f"【问题】\n{question}"
        )

    def chat(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 1500) -> str:
        """通用调用：给审题、改写这类工具用。"""
        if not self.api_key:
            raise RuntimeError("未配置 API Key")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"].strip()

    def _call_llm(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 1200,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"].strip()


_SUMMARY_HINTS = ("总结", "摘要", "大纲", "笔记汇总", "提炼", "AI 总结", "课程笔记")


def _is_summary(title: str) -> bool:
    t = (title or "").lower()
    return any(h.lower() in t for h in _SUMMARY_HINTS)


def _num_after(text: str, pattern: str) -> float | None:
    m = re.search(pattern + r"([0-9]+(?:\.[0-9]+)?)", text)
    return float(m.group(1)) if m else None


_BOARD_RE = re.compile(r"(?:牌面|翻牌|转牌|河牌|board)\s*[:：]?\s*((?:[2-9TJQKA][shdc]\s*){3,5})", re.IGNORECASE)


def _find_board(q: str) -> str:
    m = _BOARD_RE.search(q)
    if m:
        return "".join(m.group(1).split())
    return ""


def _offline_answer(sources: list[dict], math: dict | None) -> str:
    if not sources:
        return (
            "没有配置模型，而资料库里也没检索到相关内容。\n"
            "把笔记放进 data/notes/ 再运行 python run.py ingest，或者设置 DEEPSEEK_API_KEY 让模型用通用知识回答。"
        )
    head = (
        f"没有配置模型，所以这里只做检索和计算：命中 {len(sources)} 段资料，按相关度排在下面。"
        "引用时看 [1][2] 的编号。\n"
    )
    if math:
        head += "数字已经算好了，见下方「自动计算」。\n"
    head += (
        "\n想把这几段整理成结论：展开最下面的「提问包」复制给任何模型，"
        "或者设置 DEEPSEEK_API_KEY 后重启，让它直接对着你的笔记回答。"
    )
    return head
