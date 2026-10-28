"""按主题批量转录：先排计划，再只转你要的那一批。

视频来源有两类：
- 本机 data/recordings/ 下的文件（含从印象笔记附件里拷出来的）
- Notion 页面里引用的视频（只有文件名，需要你先下载到 data/recordings/）

Notion 的视频是云端的，本地没有缓存，所以这里默认给出"要下载哪些"的清单。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import topics
from .ingest import MEDIA_EXT, transcribe, write_srt


def media_index(root: Path) -> list[dict]:
    """读导入阶段生成的 media-index.json：知道哪个视频属于哪个页面/笔记。"""
    path = Path(root) / "notes" / "media-index.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for v in data.get("notion", []):
        out.append(
            {
                "name": v.get("video", ""),
                "page": v.get("page", ""),
                "source": "notion",
                "path": None,
                "attachment": v.get("page_id", ""),
                "page_text": v.get("excerpt", ""),
            }
        )
    for v in data.get("evernote", []):
        out.append({"name": Path(v.get("path", "")).name, "page": v.get("note", ""), "source": "evernote", "path": v.get("path")})
    return out


def local_recordings(root: Path) -> list[dict]:
    rec = Path(root) / "recordings"
    if not rec.exists():
        return []
    return [
        {"name": p.name, "page": "", "source": "local", "path": str(p)}
        for p in sorted(rec.rglob("*"))
        if p.is_file() and p.suffix.lower() in MEDIA_EXT
    ]


def _attach_topic(entry: dict) -> dict:
    # 文件名往往看不出主题，靠所在页面的标题和正文判断
    extra = f"{entry.get('page', '')} {entry.get('page_text', '')}"
    t = topics.match_media(entry["name"], extra)
    entry["topic"] = t or "未分类"
    return entry


def plan_batch(root: Path, topic: str | None = None, limit: int | None = None) -> dict:
    entries = [_attach_topic(e) for e in media_index(root)] + [_attach_topic(e) for e in local_recordings(root)]
    # 同名去重：本地文件覆盖云端条目
    seen: dict[str, dict] = {}
    for e in entries:
        key = Path(e["name"]).stem.lower()
        if key in seen and seen[key].get("path") and not e.get("path"):
            continue
        seen[key] = e
    entries = list(seen.values())

    if topic:
        terms = [t.lower() for t in topics.search_terms(topic)]
        picked = [
            e for e in entries
            if any(t in (e["name"] + e.get("page", "") + e.get("page_text", "")).lower() for t in terms)
            or e["topic"] == topic
        ]
    else:
        picked = entries

    ready = [e for e in picked if e.get("path") and Path(e["path"]).exists()]
    missing = [e for e in picked if not (e.get("path") and Path(e["path"]).exists())]
    if limit:
        ready = ready[:limit]
        missing = missing[:limit]
    by_topic: dict[str, int] = {}
    for e in picked:
        by_topic[e["topic"]] = by_topic.get(e["topic"], 0) + 1
    return {
        "topic": topic or "全部",
        "total": len(picked),
        "ready": ready,
        "missing": missing,
        "by_topic": dict(sorted(by_topic.items(), key=lambda kv: -kv[1])),
    }


def run_batch(root: Path, entries: list[dict], model: str = "small", log=print) -> dict:
    root = Path(root)
    out_dir = root / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    done = failed = 0
    for e in entries:
        src = Path(e["path"])
        target = out_dir / f"{src.stem}.json"
        if target.exists():
            log(f"  跳过（已转录）：{src.name}")
            continue
        try:
            log(f"  转录中：{src.name} …")
            segs = transcribe(src, model)
            target.write_text(json.dumps({"source": str(src), "segments": segs}, ensure_ascii=False), encoding="utf-8")
            write_srt(segs, out_dir / f"{src.stem}.srt")
            done += 1
        except Exception as ex:
            failed += 1
            log(f"  ! {src.name}: {ex}")
    return {"transcribed": done, "failed": failed}


def render_plan(plan: dict) -> str:
    lines = [f"主题：{plan['topic']}，命中 {plan['total']} 个视频"]
    if plan["by_topic"]:
        lines.append("分布：" + " · ".join(f"{k} {v}" for k, v in plan["by_topic"].items()))
    lines.append("")
    if plan["ready"]:
        lines.append(f"可以立刻转录（本地已有文件）：{len(plan['ready'])} 个")
        for e in plan["ready"][:20]:
            lines.append(f"  - [{e['topic']}] {e['name']}")
        lines.append("")
    if plan["missing"]:
        lines.append(f"需要先把文件放到 data/recordings/：{len(plan['missing'])} 个")
        for e in plan["missing"][:25]:
            src = f"（来自《{e['page']}》）" if e.get("page") else ""
            lines.append(f"  - [{e['topic']}] {e['name']} {src}")
        if len(plan["missing"]) > 25:
            lines.append(f"  … 还有 {len(plan['missing']) - 25} 个")
    return "\n".join(lines)
