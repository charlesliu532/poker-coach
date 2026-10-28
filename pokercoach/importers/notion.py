"""Notion 导入：两条路

1) API（推荐，增量）：在 Notion 建一个 internal integration，拿到 token，
   把要学的页面 share 给它，然后 `run.py import notion --token ...`。
2) 导出包：Notion「Export → Markdown & CSV」得到的 zip，直接喂给
   `run.py import notion-zip export.zip`，不需要 token。

两条路都会把页面写成 markdown，落到 data/notes/notion/ 下。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


# ---------------------------------------------------------------- 渲染


def rich_text(items: list[dict]) -> str:
    out = []
    for it in items or []:
        txt = it.get("plain_text", "")
        if not txt:
            continue
        ann = it.get("annotations") or {}
        if ann.get("code"):
            txt = f"`{txt}`"
        elif ann.get("bold"):
            txt = f"**{txt}**"
        elif ann.get("italic"):
            txt = f"*{txt}*"
        if it.get("href"):
            txt = f"[{txt}]({it['href']})"
        out.append(txt)
    return "".join(out)


def _indent(text: str, prefix: str) -> str:
    lines = text.splitlines() or [""]
    return "\n".join(prefix + l if l.strip() else l for l in lines)


def block_to_markdown(block: dict) -> str:
    """单个 block → markdown 文本（不递归）。"""
    t = block.get("type")
    data = block.get(t, {}) if t else {}

    if t == "paragraph":
        return rich_text(data.get("rich_text", []))
    if t in ("heading_1", "heading_2", "heading_3"):
        level = {"heading_1": "#", "heading_2": "##", "heading_3": "###"}[t]
        return f"{level} {rich_text(data.get('rich_text', []))}"
    if t == "bulleted_list_item":
        return "- " + _indent(rich_text(data.get("rich_text", [])), "  ").lstrip()
    if t == "numbered_list_item":
        return "1. " + _indent(rich_text(data.get("rich_text", [])), "   ").lstrip()
    if t == "to_do":
        mark = "x" if data.get("checked") else " "
        return f"- [{mark}] {rich_text(data.get('rich_text', []))}"
    if t == "toggle":
        return "- " + rich_text(data.get("rich_text", []))
    if t == "quote":
        return "> " + rich_text(data.get("rich_text", []))
    if t == "callout":
        emoji = (data.get("icon") or {}).get("emoji", "")
        return f"> {emoji} {rich_text(data.get('rich_text', []))}".strip()
    if t == "code":
        lang = data.get("language", "")
        return f"```{lang}\n{rich_text(data.get('rich_text', []))}\n```"
    if t == "equation":
        return f"$$\n{data.get('expression', '')}\n$$"
    if t == "divider":
        return "---"
    if t == "child_page":
        return f"## {data.get('title', '子页面')}"
    if t == "table_row":
        cells = [rich_text(c) for c in data.get("cells", [])]
        return "| " + " | ".join(cells) + " |"
    if t == "bookmark":
        return f"[{data.get('url', '')}]({data.get('url', '')})"
    if t == "image":
        return ""  # 图片里的文字需要 OCR，先跳过
    return ""


def blocks_to_markdown(blocks: list[dict]) -> str:
    """按顺序拼接，处理表格分隔行和相邻列表项之间的空行。"""
    out: list[str] = []
    prev = None
    for b in blocks:
        line = block_to_markdown(b)
        if line is None:
            continue
        t = b.get("type")
        if t == "table" and prev != "table":
            out.append("")
        if line.strip() == "" and prev in (None, "paragraph"):
            continue
        out.append(line)
        prev = t
    text = "\n\n".join(x for x in out if x is not None)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- API


class NotionError(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token: str, *, version: str = NOTION_VERSION, pause: float = 0.34):
        if not token:
            raise NotionError("缺少 Notion token")
        self.token = token
        self.version = version
        self.pause = pause

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{API}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": self.version,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            hint = {
                401: "token 不对或已失效",
                403: "这个页面没有分享给 integration（在页面右上角 ··· → Connections 里添加）",
                404: "页面不存在，或没分享给 integration",
                429: "被限流，稍等再试",
            }.get(e.code, "")
            raise NotionError(f"Notion API {e.code}: {hint} {detail}") from e

    def search(self, query: str = "") -> list[dict]:
        """搜索 integration 能访问的所有页面。"""
        pages: list[dict] = []
        cursor = None
        while True:
            body = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
            if query:
                body["query"] = query
            if cursor:
                body["start_cursor"] = cursor
            data = self._call("POST", "/search", body)
            pages.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            time.sleep(self.pause)
        return pages

    def children(self, block_id: str) -> list[dict]:
        out: list[dict] = []
        cursor = None
        while True:
            path = f"/blocks/{block_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            data = self._call("GET", path)
            out.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            time.sleep(self.pause)
        return out

    def page_title(self, page: dict) -> str:
        props = page.get("properties") or {}
        for v in props.values():
            if v.get("type") == "title":
                txt = "".join(x.get("plain_text", "") for x in v.get("title", []))
                if txt.strip():
                    return txt.strip()
        for key in ("title", "name"):
            if isinstance(page.get(key), str):
                return page["key"]
        return "未命名页面"

    def page_to_markdown(self, page_id: str, depth: int = 0, max_depth: int = 4) -> str:
        """递归把一个页面的所有 block 转成 markdown。"""
        blocks = self.children(page_id)
        parts: list[str] = []
        for b in blocks:
            line = block_to_markdown(b)
            if line and line.strip():
                parts.append(line)
            # 子页面/折叠块/同步块：递归
            if b.get("has_children") and b.get("type") in ("toggle", "child_page", "synced_block", "column_list", "column"):
                if depth < max_depth:
                    sub = self.page_to_markdown(b["id"], depth + 1, max_depth)
                    if sub.strip():
                        parts.append(_indent(sub, "> " if b.get("type") == "toggle" else ""))
        return "\n\n".join(parts)


_SAFE = re.compile(r'[\\/:*?"<>|\n\r\t]+')
_HASH_SUFFIX = re.compile(r"\s+[0-9a-f]{32}$")


def safe_name(text: str, limit: int = 80) -> str:
    name = _SAFE.sub("-", text).strip(" .-")
    return (name or "未命名")[:limit]


def import_notion(
    token: str,
    out_dir: str | Path,
    *,
    query: str = "",
    force: bool = False,
    log=print,
) -> dict:
    """把 integration 能访问的页面全部导出成 markdown。已有的文件默认跳过，保证增量。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    client = NotionClient(token)
    pages = client.search(query)
    log(f"Notion：找到 {len(pages)} 个页面")
    written = skipped = failed = 0
    for i, page in enumerate(pages, 1):
        pid = page["id"]
        title = client.page_title(page)
        target = out / f"{safe_name(title)}-{pid.replace('-', '')[:8]}.md"
        if target.exists() and not force:
            skipped += 1
            continue
        try:
            body = client.page_to_markdown(pid)
        except NotionError as e:
            failed += 1
            log(f"  ! {title}: {e}")
            continue
        if not body.strip():
            skipped += 1
            continue
        meta = {
            "source": "notion",
            "page_id": pid,
            "url": page.get("url", ""),
            "last_edited": page.get("last_edited_time", ""),
        }
        header = f"# {title}\n\n<!-- notion-meta: {json.dumps(meta, ensure_ascii=False)} -->\n\n"
        target.write_text(header + body + "\n", encoding="utf-8")
        written += 1
        if i % 20 == 0:
            log(f"  已导出 {written} 页…")
    log(f"Notion：写入 {written} 篇，跳过 {skipped}，失败 {failed} → {out}")
    return {"pages": len(pages), "written": written, "skipped": skipped, "failed": failed, "out": str(out)}


# ---------------------------------------------------------------- 导出包


def import_notion_zip(zip_path: str | Path, out_dir: str | Path, log=print) -> dict:
    """解析 Notion 的 Markdown 导出包（zip）。"""
    zip_path = Path(zip_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".md"):
                continue
            raw_name = Path(info.filename).stem
            try:
                text = zf.read(info).decode("utf-8", errors="ignore")
            except KeyError:
                continue
            # 文件名形如 "翻前 3bet 策略 3f2a...32位hash"
            title = raw_name
            m = _HASH_SUFFIX.search(raw_name)
            page_key = ""
            if m:
                page_key = m.group(0).strip()
                title = raw_name[: m.start()]
            first = next((l for l in text.splitlines() if l.startswith("# ")), "")
            if first:
                title = first[2:].strip()
            if not text.strip():
                skipped += 1
                continue
            suffix = f"-{page_key[:8]}" if page_key else ""
            target = out / f"{safe_name(title)}{suffix}.md"
            if target.exists():
                skipped += 1
                continue
            target.write_text(text if text.startswith("#") else f"# {title}\n\n{text}", encoding="utf-8")
            written += 1
    log(f"Notion 导出包：写入 {written} 篇，跳过 {skipped} → {out}")
    return {"written": written, "skipped": skipped, "out": str(out)}
