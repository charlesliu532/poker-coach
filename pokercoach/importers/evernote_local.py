"""从本机印象笔记客户端的数据目录直接导入（不需要导出 .enex，不需要联网）。

目录结构（macOS）：
    ~/Library/Application Support/com.yinxiang.Mac/accounts/app.yinxiang.com/<账号ID>/
        localNoteStore/LocalNoteStore.sqlite   # 笔记元数据（Core Data）
        content/<笔记GUID>/content.enml        # 正文（ENML）
        content/<笔记GUID>/*.mp4 / *.jpg       # 附件

国际版 Evernote 是 com.evernote.Evernote，路径结构一样。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..topics import is_poker
from .evernote import enml_to_text, safe_name

_ROOTS = [
    Path.home() / "Library/Application Support/com.yinxiang.Mac/accounts",
    Path.home() / "Library/Application Support/com.evernote.Evernote/accounts",
    Path.home() / "Library/Containers/com.evernote.Evernote/Data/Library/Application Support/com.evernote.Evernote/accounts",
]

_MEDIA_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg"}
_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def find_stores() -> list[Path]:
    """找出所有账号的 LocalNoteStore.sqlite。"""
    found: list[Path] = []
    for root in _ROOTS:
        if not root.exists():
            continue
        found.extend(root.glob("*/*/localNoteStore/LocalNoteStore.sqlite"))
    return sorted(set(found))


def _since_2001(value) -> str:
    if not value:
        return ""
    try:
        return (_EPOCH + timedelta(seconds=float(value))).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


def load_notes(store: Path) -> list[dict]:
    account = store.parents[1]  # .../<账号ID>
    content_root = account / "content"
    conn = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    notebooks = {r["Z_PK"]: r["ZNAME"] for r in conn.execute("SELECT Z_PK, ZNAME FROM ZENNOTEBOOK")}
    rows = conn.execute(
        "SELECT ZGUID, ZLOCALUUID, ZTITLE, ZDATECREATED, ZDATEUPDATED, ZNOTEBOOK, ZACTIVE FROM ZENNOTE"
    ).fetchall()
    conn.close()

    notes = []
    for r in rows:
        guid = r["ZGUID"]
        if not guid:
            continue
        # 正文目录用的是 ZLOCALUUID（大写），不是 ZGUID
        note_dir = content_root / (r["ZLOCALUUID"] or guid)
        if not note_dir.exists():
            note_dir = content_root / guid
        enml = note_dir / "content.enml"
        if not enml.exists():
            continue
        try:
            raw = enml.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        body = enml_to_text(raw)
        if not body.strip():
            continue
        media = [str(p) for p in note_dir.iterdir() if p.suffix.lower() in _MEDIA_EXT]
        notes.append(
            {
                "guid": guid,
                "title": (r["ZTITLE"] or "未命名笔记").strip(),
                "notebook": notebooks.get(r["ZNOTEBOOK"], ""),
                "created": _since_2001(r["ZDATECREATED"]),
                "updated": _since_2001(r["ZDATEUPDATED"]),
                "active": r["ZACTIVE"],
                "body": body,
                "media": media,
            }
        )
    return notes


def import_evernote_local(
    out_dir: str | Path,
    *,
    store: str | Path | None = None,
    force: bool = False,
    only_poker: bool = True,
    log=print,
) -> dict:
    stores = [Path(store)] if store else find_stores()
    if not stores:
        raise FileNotFoundError("找不到印象笔记的本地数据库，请先打开客户端同步一次")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    media_index: list[dict] = []
    total_notes = 0

    for st in stores:
        notes = load_notes(st)
        total_notes += len(notes)
        for n in notes:
            if n["active"] == 0:
                continue
            if only_poker:
                blob = f"{n['notebook']} {n['title']} {n['body'][:2000]}"
                if not is_poker(blob, 3):
                    skipped += 1
                    continue
            target = out / f"{safe_name(n['title'])}-{n['guid'][:8]}.md"
            if target.exists() and not force:
                skipped += 1
                continue
            head = f"# {n['title']}\n\n"
            meta = []
            if n["notebook"]:
                meta.append(f"笔记本：{n['notebook']}")
            if n["updated"]:
                meta.append(f"更新：{n['updated'][:10]}")
            if meta:
                head += f"> {' · '.join(meta)}\n\n"
            target.write_text(head + n["body"] + "\n", encoding="utf-8")
            written += 1
            for m in n["media"]:
                media_index.append({"note": n["title"], "path": m, "guid": n["guid"]})

    if media_index:
        manifest = out.parent / "media-index.json"
        old = {}
        if manifest.exists():
            try:
                old = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                old = {}
        merged = media_index + [x for x in old.get("evernote", []) if x not in media_index]
        old["evernote"] = merged
        manifest.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")

    log(f"印象笔记本地：{total_notes} 条笔记 → 写入 {written}，跳过 {skipped}；附件 {len(media_index)} 个 → {out}")
    return {"notes": total_notes, "written": written, "skipped": skipped, "media": len(media_index), "out": str(out)}
