"""资料入库：笔记（md/txt/pdf）、字幕（srt/vtt）、课程录屏（自动转录）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .flashcards import generate_cards, merge_cards
from .store import Store

NOTE_EXT = {".md", ".markdown", ".txt"}
PDF_EXT = {".pdf"}
SUB_EXT = {".srt", ".vtt"}
MEDIA_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg"}
SKIP_NAMES = {"README.md", "笔记模板.md", "如何整理笔记.md"}

_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;\n])")
_SRT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})")
_VTT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})")


# ---------------------------------------------------------------- 切片


def _split_sections(text: str) -> list[tuple[str, str]]:
    """按 markdown 标题切节，返回 [(标题路径, 正文)]。"""
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    current = ""

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append((current, body))

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            buf = []
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            current = " / ".join(t for _, t in stack)
        else:
            buf.append(line)
    flush()
    if not sections:
        sections = [("", text)]
    return sections


def chunk_text(text: str, heading: str = "", size: int = 700, overlap: int = 60) -> list[dict]:
    """按句子把长文切成 ~size 字的片段，带少量重叠，保留标题。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if len(cur) + len(p) + 1 <= size:
            cur = f"{cur}\n{p}".strip()
            continue
        if cur:
            chunks.append(cur)
        if len(p) <= size:
            cur = p
        else:
            sents = [s for s in _SENT_SPLIT.split(p) if s.strip()]
            cur = ""
            for s in sents:
                if len(cur) + len(s) > size and cur:
                    chunks.append(cur)
                    cur = cur[-overlap:] + s
                else:
                    cur += s
    if cur.strip():
        chunks.append(cur.strip())
    return [{"text": c, "heading": heading} for c in chunks if c.strip()]


def chunk_subtitle(segments: list[dict], heading: str = "", window: float = 45.0) -> list[dict]:
    """把带时间轴的字幕合并成 ~45 秒一段，保留起止时间（用于跳回视频）。"""
    chunks: list[dict] = []
    buf: list[str] = []
    t0 = None
    t1 = None
    for seg in segments:
        if t0 is None:
            t0 = seg["start"]
        buf.append(seg["text"].strip())
        t1 = seg["end"]
        if t1 - t0 >= window:
            chunks.append({"text": " ".join(buf), "heading": heading, "start": t0, "end": t1})
            buf, t0, t1 = [], None, None
    if buf:
        chunks.append({"text": " ".join(buf), "heading": heading, "start": t0, "end": t1})
    return chunks


# ---------------------------------------------------------------- 解析


def parse_subtitle(text: str) -> list[dict]:
    segs: list[dict] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        idx = 0
        if lines[0].strip().isdigit():
            idx = 1
        if idx >= len(lines):
            continue
        m = _SRT_TIME.search(lines[idx]) or _VTT_TIME.search(lines[idx])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        body = " ".join(lines[idx + 1 :]).strip()
        body = re.sub(r"<[^>]+>", "", body)
        if body:
            segs.append({"start": start, "end": end, "text": body})
    return segs


def parse_vtt(text: str) -> list[dict]:
    return parse_subtitle(text)


def read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("读 PDF 需要 pypdf：.venv/bin/pip install pypdf") from e
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


# ---------------------------------------------------------------- 概念卡

_QA_PATTERNS = [
    (re.compile(r"^\s*(?:Q|问)\s*[:：]\s*(.+)$"), re.compile(r"^\s*(?:A|答)\s*[:：]\s*(.+)$")),
]


def extract_cards(text: str, heading: str = "") -> list[dict]:
    """从笔记里抽 Q/A 卡片，以及"原则/结论/记住"这种一句话要点。"""
    cards: list[dict] = []
    lines = [l.strip() for l in text.splitlines()]
    seen = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        for qre, are in _QA_PATTERNS:
            qm = qre.match(line)
            if qm and i + 1 < len(lines):
                am = are.match(lines[i + 1])
                if am:
                    front, back = qm.group(1).strip(), am.group(1).strip()
                    key = front.lower()
                    if front and back and key not in seen:
                        seen.add(key)
                        cards.append({"front": front, "back": back, "tags": heading, "kind": "qa"})
                    i += 2
                    break
        else:
            m = re.match(r"^\s*(?:原则|结论|记住|要点|一句话)\s*[:：]\s*(.+)$", line)
            if m:
                back = m.group(1).strip()
                front = f"{heading} 的核心原则是什么？" if heading else f"这条原则是什么：{back[:18]}…"
                key = ("p", back[:40])
                if len(back) > 6 and key not in seen:
                    seen.add(key)
                    cards.append({"front": front, "back": back, "tags": heading, "kind": "qa"})
            i += 1
    return cards


# ---------------------------------------------------------------- 转录


_MODEL_CACHE: dict[str, object] = {}


def transcribe(path: Path, model_size: str = "small") -> list[dict]:
    """用 faster-whisper 转录音视频，返回带时间轴的片段。"""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "没有安装 faster-whisper。安装：.venv/bin/pip install faster-whisper（首次会自动下载模型）"
        ) from e

    if model_size not in _MODEL_CACHE:
        _MODEL_CACHE[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
    model = _MODEL_CACHE[model_size]
    segments, info = model.transcribe(
        str(path), language="zh", vad_filter=True, beam_size=5, condition_on_previous_text=False
    )
    out = []
    for s in segments:
        txt = s.text.strip()
        if txt:
            out.append({"start": float(s.start), "end": float(s.end), "text": txt})
    return out


def write_srt(segments: list[dict], path: Path) -> None:
    def fmt(t: float) -> str:
        h = int(t // 3600)
        m = int(t % 3600 // 60)
        s = int(t % 60)
        ms = int(round((t - int(t)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines += [str(i), f"{fmt(seg['start'])} --> {fmt(seg['end'])}", seg["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _card_term(front: str) -> str:
    """卡片问的是哪个概念，用来统计全库重复度。"""
    m = re.match(r"^「(.+?)」是什么意思？$", front or "")
    return m.group(1) if m else re.sub(r"\s+", "", front or "")


def rebuild_cards(store: Store, limit: int = 8, refine: bool = True, log=print) -> dict:
    """不重新读文件，直接从已有切片重建卡片（key 稳定，复习进度不会丢）。

    refine=True 时做两道全库级的清洗：
    1. 模板词：同一个"概念"在 5 篇以上文档里都当术语出现，说明它是小节名（误区/纠偏/行动线），删
    2. 重复卡：同一个问题在多篇笔记里都有，只保留答案最完整的那一张
    """
    import hashlib
    from collections import Counter, defaultdict

    docs = store.conn.execute("SELECT id, title FROM docs").fetchall()
    per_doc: dict[int, list[dict]] = {}
    for d in docs:
        rows = store.conn.execute(
            "SELECT text, heading FROM chunks WHERE doc_id = ? ORDER BY ord", (d["id"],)
        ).fetchall()
        cards: list[dict] = []
        cards += extract_cards("\n".join(r["text"] for r in rows), d["title"])
        for r in rows:
            cards += generate_cards(r["text"], r["heading"] or d["title"], limit=4)
        per_doc[d["id"]] = merge_cards(cards, limit=max(limit * 2, 12))

    dropped_template = dropped_dupe = 0
    if refine:
        df = Counter()
        for d_id, cards in per_doc.items():
            for term in {_card_term(c["front"]) for c in cards}:
                df[term] += 1

        for d_id, cards in list(per_doc.items()):
            kept = []
            for c in cards:
                if df[_card_term(c["front"])] >= 5 and not re.search(r"\d", _card_term(c["front"])):
                    dropped_template += 1
                    continue
                kept.append(c)
            per_doc[d_id] = kept

        # 同一问题只留一张：优先带英文/括号、答案更完整的
        best: dict[str, tuple[int, dict]] = {}
        for d_id, cards in per_doc.items():
            for c in cards:
                k = c["key"]
                score = (("（" in c["front"]) or ("(" in c["front"])) * 3 + min(len(c["back"]), 160) / 160
                if k not in best or score > best[k][0]:
                    best[k] = (score, c)
        winners = {k: v[1] for k, v in best.items()}

        new_per_doc: dict[int, list[dict]] = defaultdict(list)
        for d_id, cards in per_doc.items():
            for c in cards:
                if winners.get(c["key"]) is c:
                    new_per_doc[d_id].append(c)
                else:
                    dropped_dupe += 1
        per_doc = dict(new_per_doc)

    added = removed = 0
    for d in docs:
        a, rm = store.sync_cards(d["id"], per_doc.get(d["id"], [])[:limit])
        added += a
        removed += rm
    store.conn.commit()
    log(
        f"卡片重建：{len(docs)} 篇，新增 {added}，移除 {removed}"
        + (f"（模板词 {dropped_template}，重复卡 {dropped_dupe}）" if refine else "")
    )
    return {"docs": len(docs), "added": added, "removed": removed,
            "template": dropped_template, "dupe": dropped_dupe}


# ---------------------------------------------------------------- 主流程


def ingest(
    root: Path,
    store: Store,
    *,
    transcribe_media: bool = True,
    model_size: str = "small",
    log=print,
) -> dict:
    root = Path(root)
    notes_dir = root / "notes"
    transcript_dir = root / "transcripts"
    media_dirs = [root / "recordings", notes_dir]
    transcript_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)

    stats = {"docs": 0, "chunks": 0, "cards": 0, "skipped": 0, "transcribed": 0, "failed": []}

    def save_doc(path: Path, kind: str, title: str, chunks: list[dict], cards: list[dict] | None = None, meta=None):
        rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        doc_id, rebuild = store.upsert_doc(rel, kind, title, mtime=path.stat().st_mtime if path.exists() else 0, meta=meta)
        if rebuild:
            store.replace_chunks(doc_id, chunks)
            if cards is not None:
                store.sync_cards(doc_id, cards)
        stats["docs"] += 1
        if rebuild:
            stats["chunks"] += len(chunks)
            stats["cards"] += len(cards or [])
        return doc_id

    # 1) 笔记
    for d in sorted(notes_dir.rglob("*")):
        if not d.is_file() or d.name in SKIP_NAMES:
            continue
        suf = d.suffix.lower()
        if suf in NOTE_EXT:
            text = d.read_text(encoding="utf-8", errors="ignore")
            title = d.stem
            chunks: list[dict] = []
            cards: list[dict] = []
            for heading, body in _split_sections(text):
                chunks += chunk_text(body, heading or title)
                cards += extract_cards(body, heading or title)
                cards += generate_cards(body, heading or title, limit=5)
            cards = merge_cards(cards, limit=16)
            save_doc(d, "note", title, chunks, cards)
        elif suf in PDF_EXT:
            try:
                text = read_pdf(d)
            except Exception as e:
                stats["failed"].append(f"{d.name}: {e}")
                continue
            chunks = chunk_text(text, d.stem)
            save_doc(d, "pdf", d.stem, chunks, merge_cards(extract_cards(text, d.stem) + generate_cards(text, d.stem, limit=10), limit=16))

    # 2) 字幕
    for d in sorted(transcript_dir.glob("*")):
        if not d.is_file():
            continue
        suf = d.suffix.lower()
        if suf in SUB_EXT:
            segs = parse_subtitle(d.read_text(encoding="utf-8", errors="ignore"))
            if segs:
                save_doc(d, "transcript", d.stem, chunk_subtitle(segs, d.stem), [],
                         meta={"segments": len(segs)})
        elif suf == ".json":
            try:
                data = json.loads(d.read_text(encoding="utf-8"))
            except Exception:
                continue
            segs = data.get("segments") or []
            if segs and "text" in segs[0]:
                save_doc(d, "transcript", d.stem, chunk_subtitle(segs, d.stem), [],
                         meta={"segments": len(segs)})
        elif suf == ".txt":
            # 纯文本转写（形如 "[00:12] 内容"）：按时间戳切段，没有就用整段
            import re as _re
            raw = d.read_text(encoding="utf-8", errors="ignore")
            def _mmss(m):
                return int(m.group(1)) * 60 + int(m.group(2))
            segs = []
            for ln in raw.splitlines():
                m = _re.match(r"\[(\d{1,2}):(\d{2})\]\s*(.+)", ln.strip())
                if m:
                    t = float(_mmss(m))
                    segs.append({"start": t, "end": t + 5.0, "text": m.group(3).strip()})
            if not segs:
                t = 0.0
                for ln in raw.splitlines():
                    if ln.strip():
                        segs.append({"start": t, "end": t + 5.0, "text": ln.strip()})
                        t += 5.0
            if segs:
                save_doc(d, "transcript", d.stem, chunk_subtitle(segs, d.stem), [],
                         meta={"segments": len(segs)})

    # 3) 录屏 -> 转录
    for base in media_dirs:
        if not base.exists():
            continue
        for d in sorted(base.rglob("*")):
            if not d.is_file() or d.suffix.lower() not in MEDIA_EXT:
                continue
            out_json = transcript_dir / f"{d.stem}.json"
            if out_json.exists():
                continue
            if not transcribe_media:
                stats["skipped"] += 1
                continue
            try:
                log(f"  转录中: {d.name} …")
                segs = transcribe(d, model_size)
                out_json.write_text(json.dumps({"source": str(d), "segments": segs}, ensure_ascii=False), encoding="utf-8")
                write_srt(segs, transcript_dir / f"{d.stem}.srt")
                stats["transcribed"] += 1
                save_doc(out_json, "transcript", d.stem, chunk_subtitle(segs, d.stem), [],
                         meta={"source": str(d), "segments": len(segs)})
            except Exception as e:
                stats["failed"].append(f"{d.name}: {e}")
    store.conn.commit()
    # 1.9) 从策略树重建「场景练习」题库
    try:
        from .scenecards import build_cards

        scene_cards = build_cards(root / "tree")
        if scene_cards:
            sid, _ = store.upsert_doc("tree/scene-cards", "tree", "策略树场景题", mtime=0)
            store.replace_chunks(sid, [{"heading": "场景题", "text": "由策略树自动生成，随树更新", "start": 0}])
            added, _ = store.sync_cards(sid, [
                {"front": c["front"], "back": c["back"], "tags": c["scene"],
                 "kind": "spot", "key": c["key"], "options": c["options"]}
                for c in scene_cards
            ])
            store.conn.commit()      # 前面的 commit 在本段之前，这里必须自己提交
            stats["cards"] += len(scene_cards)
            stats["scene_cards"] = len(scene_cards)
            log(f"场景题库：{len(scene_cards)} 道（由策略树生成）")
    except Exception as e:  # 生成失败不能挡住主流程
        stats["failed"].append(f"场景题库: {e}")

    # 2.0) 真实牌局题：用 hh_spots 的牌面/手牌当题面，答案是策略树的打法
    try:
        from . import tree as _tree
        from .spotcards import build_cards as build_spot_cards

        st_cards = build_spot_cards(store, _tree, root / "tree")
        if st_cards:
            sid, _ = store.upsert_doc("tree/spot-cards", "tree", "真实牌局题", mtime=0)
            store.replace_chunks(sid, [{"heading": "真实牌局", "text": "由 hh_spots + 策略树生成", "start": 0}])
            store.sync_cards(sid, [
                {"front": c["front"], "back": c["back"], "tags": c["scene"],
                 "kind": "spot", "key": c["key"], "options": c["options"]}
                for c in st_cards
            ])
            store.conn.commit()
            stats["spot_cards"] = len(st_cards)
            log(f"真实牌局题：{len(st_cards)} 道（hh_spots × 策略树）")
    except Exception as e:
        stats["failed"].append(f"真实牌局题: {e}")

    # 2.1) 复习卡改成从策略树出（替换掉笔记抽取的截断题/词典题）
    try:
        from .rulecards import build_cards as build_rule_cards

        rc = build_rule_cards(root / "tree")
        if rc:
            rid, _ = store.upsert_doc("tree/rule-cards", "tree", "策略树复习卡", mtime=0)
            store.replace_chunks(rid, [{"heading": "复习卡", "text": "由策略树规则生成", "start": 0}])
            store.sync_cards(rid, [
                {"front": c["front"], "back": c["back"], "tags": c["tags"],
                 "kind": c["kind"], "key": c["key"]}
                for c in rc
            ])
            store.conn.commit()
            stats["rule_cards"] = len(rc)
            log(f"策略树复习卡：{len(rc)} 张")
    except Exception as e:
        stats["failed"].append(f"策略树复习卡: {e}")

    return stats
