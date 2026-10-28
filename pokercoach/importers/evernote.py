"""印象笔记（Evernote）导入：解析 .enex 导出文件。

.exen 是 XML：<en-export><note><title/><content/><tag/>…</note></en-export>
content 里是 ENML（一种 XHTML），需要转成纯 markdown 文本。
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from xml.etree import ElementTree as ET


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1].lower()


def enml_to_text(enml: str) -> str:
    """ENML/HTML → 纯文本。保留段落、列表和标题的层级感。"""
    if not enml:
        return ""
    s = re.sub(r"<\?xml[^>]*\?>", "", enml)
    s = re.sub(r"<!DOCTYPE[^>]*>", "", s, flags=re.I)
    s = re.sub(r"<en-note[^>]*>", "", s, flags=re.I)
    s = re.sub(r"</en-note>", "", s, flags=re.I)

    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(div|p|tr|blockquote)>", "\n", s, flags=re.I)
    s = re.sub(r"</(h1|h2|h3|h4|h5|h6)>", "\n\n", s, flags=re.I)
    s = re.sub(r"<(h1|h2|h3)[^>]*>", "\n## ", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "\n- ", s, flags=re.I)
    s = re.sub(r"<td[^>]*>", " | ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)

    s = html.unescape(s)
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _note_to_markdown(note: ET.Element) -> dict:
    fields = {_local(child.tag): child for child in note}
    title = (fields["title"].text or "").strip() if "title" in fields else "未命名"
    content = fields["content"].text if "content" in fields else ""
    body = enml_to_text(content or "")
    tags = [t.text.strip() for t in note if _local(t.tag) == "tag" and t.text]
    created = fields["created"].text if "created" in fields else ""
    guid = fields["guid"].text if "guid" in fields else ""
    if tags:
        body = f"标签：{', '.join(tags)}\n\n{body}"
    return {"title": title, "body": body, "tags": tags, "created": created, "guid": guid}


def parse_enex(path: str | Path) -> list[dict]:
    path = Path(path)
    tree = ET.parse(path)
    root = tree.getroot()
    if _local(root.tag) != "en-export":
        raise ValueError("不是印象笔记的 .enex 文件")
    return [_note_to_markdown(n) for n in root if _local(n.tag) == "note"]


_SAFE = re.compile(r'[\\/:*?"<>|\n\r\t]+')


def safe_name(text: str, limit: int = 80) -> str:
    name = _SAFE.sub("-", text).strip(" .-")
    return (name or "未命名")[:limit]


def import_enex(path: str | Path, out_dir: str | Path, log=print) -> dict:
    """把 .enex 里的每条笔记写成一个 .md 文件。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    notes = parse_enex(path)
    written = 0
    for n in notes:
        if not n["body"].strip():
            continue
        suffix = n["guid"][:8] if n["guid"] else str(abs(hash(n["title"])) % 10**8)
        target = out / f"{safe_name(n['title'])}-{suffix}.md"
        header = f"# {n['title']}\n\n"
        target.write_text(header + n["body"] + "\n", encoding="utf-8")
        written += 1
    log(f"印象笔记：{len(notes)} 条，写入 {written} 篇 → {out}")
    return {"notes": len(notes), "written": written, "out": str(out)}
