"""手牌上传：存文件 + 记元信息（平台/级别/时间跨度）+ 重新导入。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .hh import gg as hh_gg
from .hh import spotdb
from .hh.analysis import analyze as hh_analyze
from .hh.analysis import hero_flags
from .store import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS hh_uploads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created TEXT, platform TEXT, stakes TEXT,
  period_from TEXT, period_to TEXT, filename TEXT,
  hands INTEGER, note TEXT
);
"""


def ensure_schema(store):
    store.conn.executescript(SCHEMA)
    store.conn.commit()


def _safe(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z._\u4e00-\u9fa5-]+", "_", name or "upload")[:80]


def save_and_import(store, root: Path, *, platform: str, stakes: str,
                    period_from: str, period_to: str,
                    filename: str, text: str) -> dict:
    ensure_schema(store)
    raw_dir = root / "hh" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = now().replace(":", "").replace("-", "")[:15]
    fname = f"{_safe(platform or 'unknown')}-{_safe(stakes or 'na')}-{stamp}-{_safe(filename or 'hh.txt')}"
    if not fname.endswith(".txt"):
        fname += ".txt"
    path = raw_dir / fname
    path.write_text(text, encoding="utf-8")

    # 重新解析整个 raw 目录（增量安全：hh 按 hand_id 去重）
    hands, info = hh_gg.parse_paths([raw_dir])
    rows = []
    for h in hands:
        rows.append({
            "hand_id": h.hand_id, "played_at": h.played_at,
            "stakes": f"{h.sb:g}/{h.bb:g}", "hero": h.hero,
            "board": " ".join(h.board), "pot": h.pot, "net": h.hero_net(),
            "bb": h.bb, "flags": hero_flags(h), "data": h.to_dict(),
        })
    store.add_hh(rows)
    store.clear_spots()
    from run import _player_types  # 复用命令行里的分类逻辑
    ptypes = _player_types(hands)
    spot_rows = [sp for hnd in hands for sp in spotdb.extract_spots(hnd, ptypes)]
    store.add_spots(spot_rows)
    result = hh_analyze(store.all_hh_flags())
    (root / "leaks.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    store.conn.execute(
        "INSERT INTO hh_uploads(created,platform,stakes,period_from,period_to,filename,hands,note) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (now(), platform, stakes, period_from, period_to, fname, len(hands), ""),
    )
    store.conn.commit()
    return {"ok": True, "saved": fname, "files": info["files"],
            "hands_total": len(hands), "spots": len(spot_rows),
            "hands_in_file": info["hands"]}


def list_uploads(store) -> list[dict]:
    ensure_schema(store)
    return [dict(r) for r in store.conn.execute(
        "SELECT * FROM hh_uploads ORDER BY id DESC LIMIT 50")]
