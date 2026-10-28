"""从本机 Notion 客户端的离线缓存直接导入（不需要 token、不需要联网）。

Notion 桌面版会把看过的页面存在
    ~/Library/Application Support/Notion/notion.db
的 block 表里，字段结构和官方 API 很像：
    id / type / properties(JSON) / content(子 block id 列表) / parent_id / alive

注意：只有客户端缓存过的页面才在库里。没打开过的页面需要联网后才会有。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

_NOTION_DIR = Path.home() / "Library/Application Support/Notion"
_NOTION_DIR_WIN = Path(os.environ.get("APPDATA", "")) / "Notion"


def default_db() -> Path | None:
    for p in (_NOTION_DIR / "notion.db", _NOTION_DIR_WIN / "notion.db"):
        if p.exists():
            return p
    return None


def _copy_db(src: Path) -> tuple[Path, tempfile.TemporaryDirectory]:
    """拷一份再读：避免和正在运行的 Notion 抢锁、也绝不改动原库。"""
    tmp = tempfile.TemporaryDirectory()
    dst = Path(tmp.name) / "notion.db"
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        side = src.with_name(src.name + suffix)
        if side.exists():
            shutil.copy2(side, dst.with_name(dst.name + suffix))
    return dst, tmp


_SAFE = re.compile(r'[\\/:*?"<>|\n\r\t]+')
_HASH = re.compile(r"\s+[0-9a-f]{32}$")

_HEADINGS = {
    "header": "#",
    "sub_header": "##",
    "sub_sub_header": "###",
    "header_4": "####",
}


def safe_name(text: str, limit: int = 80) -> str:
    name = _SAFE.sub("-", (text or "").strip()).strip(" .-")
    return (name or "未命名")[:limit]


def plain(segments) -> str:
    """Notion 的 rich text：[[文本, [装饰...]], ...]，取出纯文本。"""
    if not segments:
        return ""
    if isinstance(segments, str):
        return segments
    out = []
    for seg in segments:
        if isinstance(seg, str):
            out.append(seg)
            continue
        if not isinstance(seg, (list, tuple)) or not seg:
            continue
        text = seg[0] if isinstance(seg[0], str) else ""
        if text == "‣":  # 链接/提及占位符，文本在别处，直接跳过
            continue
        out.append(text)
    return "".join(out)


def prop_text(props: dict, key: str = "title") -> str:
    if not props:
        return ""
    return plain(props.get(key))


def block_title(props: dict) -> str:
    return prop_text(props, "title").strip()


class Page:
    __slots__ = ("id", "type", "props", "children", "parent_id", "parent_table", "alive")

    def __init__(self, row):
        self.id = row["id"]
        self.type = row["type"]
        self.props = _loads(row["properties"])
        self.children = _loads(row["content"]) or []
        self.parent_id = row["parent_id"]
        self.parent_table = row["parent_table"]
        self.alive = row["alive"]


def _loads(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def render_block(page: Page, lookup: dict[str, Page], depth: int = 0, seen: set | None = None) -> str:
    """把一个 block 渲染成 markdown（含子块）。"""
    seen = seen or set()
    if page.id in seen or depth > 8:
        return ""
    seen.add(page.id)

    t = page.type
    text = block_title(page.props)
    kids = [lookup[c] for c in page.children if c in lookup]
    child_md = "\n".join(filter(None, (render_block(k, lookup, depth + 1, seen) for k in kids)))

    if t in _HEADINGS:
        return f"{_HEADINGS[t]} {text}" + (f"\n\n{child_md}" if child_md else "")
    if t == "text":
        return text + (f"\n\n{child_md}" if child_md else "")
    if t == "bulleted_list":
        body = text + (("\n" + child_md) if child_md else "")
        return "- " + body.replace("\n", "\n  ")
    if t == "numbered_list":
        body = text + (("\n" + child_md) if child_md else "")
        return "1. " + body.replace("\n", "\n   ")
    if t == "to_do":
        checked = "x" if plain(page.props.get("checked")).strip().lower() in ("yes", "true", "1") else " "
        return f"- [{checked}] {text}"
    if t in ("quote", "callout"):
        return f"> {text}" + (f"\n> {child_md}" if child_md else "")
    if t == "toggle":
        return f"> **{text}**" + (f"\n> {child_md}" if child_md else "")
    if t == "code":
        return f"```\n{text}\n```"
    if t == "equation":
        return f"$$\n{text}\n$$"
    if t == "divider":
        return "---"
    if t == "table_row":
        cells = [plain(v) for v in (page.props or {}).values()]
        return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"
    if t == "table":
        return child_md
    if t == "bookmark":
        url = plain(page.props.get("link")) or text
        return f"[{text or url}]({url})" if url else ""
    if t == "page":
        return f"- 子页面：{text}"
    if t == "video":
        return f"[视频] {text}"
    if t == "image":
        return ""
    if t == "collection_view":
        return "[数据库视图]"
    if t in ("column_list", "column"):
        return child_md
    return text or child_md


def load_pages(db_path: Path) -> tuple[dict[str, Page], list[Page]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, type, properties, content, parent_id, parent_table, alive "
        "FROM block WHERE alive = 1"
    ).fetchall()
    conn.close()
    pages = {r["id"]: Page(r) for r in rows}
    return pages, list(pages.values())


def page_docs(pages: dict[str, Page]) -> list[dict]:
    """每个页面一篇文档：只渲染自己的直接子块，子页面单独成篇（避免重复入库）。"""
    docs = []
    for page in pages.values():
        if page.type != "page":
            continue
        title = block_title(page.props) or "未命名页面"
        kids = [pages[c] for c in page.children if c in pages]
        content_kids = [k for k in kids if k.type != "page"]
        subpages = [block_title(k.props) for k in kids if k.type == "page"]
        body = "\n".join(filter(None, (render_block(k, pages) for k in content_kids)))
        links = "\n".join(f"- 子页面：{t}" for t in subpages if t)
        full = (body + ("\n\n## 子页面\n" + links if links else "")).strip()
        if not full:
            continue
        docs.append(
            {
                "id": page.id,
                "title": title,
                "body": full,
                "excerpt": " ".join(full.split())[:400],
                "parent_id": page.parent_id,
                "parent_table": page.parent_table,
                "videos": [
                    block_title(k.props) for k in kids if k.type == "video" and block_title(k.props)
                ],
            }
        )
    return docs


def import_notion_local(
    out_dir: str | Path,
    *,
    db_path: str | Path | None = None,
    force: bool = False,
    log=print,
) -> dict:
    src = Path(db_path) if db_path else default_db()
    if not src or not Path(src).exists():
        raise FileNotFoundError("找不到 Notion 本地缓存 notion.db，请先打开 Notion 桌面版并浏览一次课程")
    copy, tmp = _copy_db(Path(src))
    try:
        pages, _ = load_pages(copy)
        docs = page_docs(pages)
    finally:
        tmp.cleanup()

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    videos: list[dict] = []
    for d in docs:
        # 视频引用和页面摘要要单独记下来，和文件是否重写无关
        for v in d["videos"]:
            videos.append({"page": d["title"], "video": v, "page_id": d["id"], "excerpt": d.get("excerpt", "")})
        target = out / f"{safe_name(d['title'])}-{d['id'][:8]}.md"
        if target.exists() and not force:
            skipped += 1
            continue
        header = f"# {d['title']}\n\n<!-- notion-page: {d['id']} -->\n\n"
        target.write_text(header + d["body"] + "\n", encoding="utf-8")
        written += 1

    if videos:
        manifest = out.parent / "media-index.json"
        old = []
        if manifest.exists():
            try:
                old = json.loads(manifest.read_text(encoding="utf-8")).get("notion", [])
            except Exception:
                old = []
        seen = {(x.get("page_id"), x.get("video")) for x in videos}
        merged = videos + [x for x in old if (x.get("page_id"), x.get("video")) not in seen]
        manifest.write_text(json.dumps({"notion": merged}, ensure_ascii=False, indent=1), encoding="utf-8")

    log(f"Notion 本地：{len(docs)} 个页面 → 写入 {written}，跳过 {skipped}；视频引用 {len(videos)} 条 → {out}")
    return {"pages": len(docs), "written": written, "skipped": skipped, "videos": len(videos), "out": str(out)}
