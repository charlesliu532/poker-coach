"""SQLite 存储层：资料、切片、卡片、复习记录、复盘手牌。"""

from __future__ import annotations

import json

import sqlite3
import threading

# sqlite3 连接被 ThreadingHTTPServer 多线程共用，必须串行化
_DB_LOCK = threading.RLock()


class _FrozenRows:
    """已取回的结果集：fetchone/fetchall 不再碰数据库连接。"""

    def __init__(self, rows):
        self._rows = rows
        self._i = 0

    def fetchone(self):
        if self._i < len(self._rows):
            r = self._rows[self._i]
            self._i += 1
            return r
        return None

    def fetchall(self):
        r = self._rows[self._i:]
        self._i = len(self._rows)
        return r

    def __iter__(self):
        return iter(self.fetchall())

    def __len__(self):
        return len(self._rows)


class _LockedConn:
    """给 sqlite3 连接套一层全局锁。任何模块用 store.conn.execute 都自动串行化。"""

    def __init__(self, conn):
        self._c = conn

    def execute(self, *a, **kw):
        with _DB_LOCK:
            cur = self._c.execute(*a, **kw)
            rows = cur.fetchall()
        return _FrozenRows(rows)

    def executescript(self, *a, **kw):
        with _DB_LOCK:
            return self._c.executescript(*a, **kw)

    def commit(self):
        with _DB_LOCK:
            return self._c.commit()

    def close(self):
        with _DB_LOCK:
            return self._c.close()

    def __setattr__(self, name, value):
        if name == "_c":
            object.__setattr__(self, name, value)
        else:
            setattr(self._c, name, value)

    def __getattr__(self, name):
        return getattr(self._c, name)
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    mtime REAL NOT NULL DEFAULT 0,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    text TEXT NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    start REAL,
    end REAL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER REFERENCES docs(id) ON DELETE CASCADE,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    key TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    quality INTEGER,
    options TEXT,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
    ease REAL NOT NULL DEFAULT 2.5,
    interval REAL NOT NULL DEFAULT 0,
    due TEXT NOT NULL,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    last TEXT
);
CREATE TABLE IF NOT EXISTS hands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TEXT NOT NULL,
    stake TEXT NOT NULL DEFAULT '',
    hero TEXT NOT NULL DEFAULT '',
    villain TEXT NOT NULL DEFAULT '',
    position TEXT NOT NULL DEFAULT '',
    board TEXT NOT NULL DEFAULT '',
    pot REAL NOT NULL DEFAULT 0,
    action TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS hh (
    hand_id TEXT PRIMARY KEY,
    played_at TEXT NOT NULL DEFAULT '',
    stakes TEXT NOT NULL DEFAULT '',
    hero TEXT NOT NULL DEFAULT '',
    board TEXT NOT NULL DEFAULT '',
    pot REAL NOT NULL DEFAULT 0,
    net REAL NOT NULL DEFAULT 0,
    bb REAL NOT NULL DEFAULT 0,
    flags TEXT NOT NULL DEFAULT '{}',
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_hh_date ON hh(played_at);
CREATE TABLE IF NOT EXISTS hh_spots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hand_id TEXT NOT NULL,
    street TEXT NOT NULL,
    role TEXT NOT NULL,
    pot_type TEXT NOT NULL,
    hero_pos TEXT, villain_pos TEXT, matchup TEXT,
    high TEXT, extra TEXT, paired INTEGER, connected INTEGER,
    runout TEXT, size TEXT, suit TEXT, line TEXT, oline TEXT, vtype TEXT, board TEXT, hand TEXT,
    facing TEXT, action TEXT,
    pot REAL, net REAL, bb REAL
);
CREATE INDEX IF NOT EXISTS idx_spots ON hh_spots(street, role, pot_type);
CREATE INDEX IF NOT EXISTS idx_spots_key ON hh_spots(street, high, matchup);
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quiz_level ON quiz_attempts(level);
CREATE TABLE IF NOT EXISTS profile (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS note_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    street TEXT DEFAULT '', role TEXT DEFAULT '', high TEXT DEFAULT '', suit TEXT DEFAULT '',
    paired TEXT DEFAULT '', connected TEXT DEFAULT '', runout TEXT DEFAULT '',
    oline TEXT DEFAULT '', pot_type TEXT DEFAULT '',
    freq TEXT DEFAULT '', size TEXT DEFAULT '', why TEXT DEFAULT '', avoid TEXT DEFAULT '',
    source_title TEXT DEFAULT '', source_heading TEXT DEFAULT '',
    source_chunk INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1,
    game_type TEXT DEFAULT 'cash', updated TEXT DEFAULT '', scope TEXT DEFAULT '',
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_note_rules ON note_rules(street, role, high);

CREATE TABLE IF NOT EXISTS rule_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL, field TEXT, old TEXT, new TEXT, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_history ON rule_history(rule_id);

CREATE TABLE IF NOT EXISTS sim_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TEXT NOT NULL,
    street TEXT, board TEXT, hero TEXT,
    facing REAL DEFAULT 0, action TEXT, advice_freq TEXT, advice_size TEXT,
    equity REAL DEFAULT 0, pot REAL DEFAULT 0, style TEXT, agree INTEGER
);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """sqlite 封装。所有写/读都过 _DB_LOCK，避免并发 500。"""

    def _exec(self, *a, **kw):
        """执行并「立即取回」结果。

        关键：锁必须覆盖 execute + fetch。只锁 execute 的话，
        游标返回后另一个线程再执行会重置它，fetchone() 就变成 None，
        并发请求就会 500。
        """
        with _DB_LOCK:
            cur = self._raw.execute(*a, **kw)
            rows = cur.fetchall()
        return _FrozenRows(rows)

    def execute(self, *a, **kw):
        with _DB_LOCK:
            return self._exec(*a, **kw)

    def commit(self):
        with _DB_LOCK:
            return self.conn.commit()

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._raw = sqlite3.connect(self.path, check_same_thread=False)
        self.conn = _LockedConn(self._raw)
        self.conn.row_factory = sqlite3.Row
        self._exec("PRAGMA foreign_keys = ON")
        self._exec("PRAGMA busy_timeout = 4000")
        try:
            self._exec("PRAGMA journal_mode = WAL")  # 让命令行和服务能同时读
        except sqlite3.OperationalError:
            pass  # 拿不到锁就用默认模式，不影响使用
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """老库补列/补 key，保证卡片 id 稳定、复习记录不丢。"""
        import hashlib
        import re

        cols = {r[1] for r in self._exec("PRAGMA table_info(cards)")}
        if "key" not in cols:
            self._exec("ALTER TABLE cards ADD COLUMN key TEXT NOT NULL DEFAULT ''")
        if "kind" not in cols:
            self._exec("ALTER TABLE cards ADD COLUMN kind TEXT NOT NULL DEFAULT ''")
        if "quality" not in cols:
            self._exec("ALTER TABLE cards ADD COLUMN quality INTEGER")
        if "options" not in cols:
            self._exec("ALTER TABLE cards ADD COLUMN options TEXT")

        spot_cols = {r[1] for r in self._exec("PRAGMA table_info(hh_spots)")}
        if "size" not in spot_cols:
            self._exec("ALTER TABLE hh_spots ADD COLUMN size TEXT")
        if "suit" not in spot_cols:
            self._exec("ALTER TABLE hh_spots ADD COLUMN suit TEXT")
        if "line" not in spot_cols:
            self._exec("ALTER TABLE hh_spots ADD COLUMN line TEXT")
        if "vtype" not in spot_cols:
            self._exec("ALTER TABLE hh_spots ADD COLUMN vtype TEXT")
        nr = {r["name"] for r in self._exec("PRAGMA table_info(note_rules)")}
        if nr:
            for col, ddl in (("source_chunk", "INTEGER DEFAULT 0"), ("enabled", "INTEGER DEFAULT 1"),
                             ("game_type", "TEXT DEFAULT 'cash'"), ("updated", "TEXT DEFAULT ''"),
                             ("scope", "TEXT DEFAULT ''")):
                if col not in nr:
                    self._exec(f"ALTER TABLE note_rules ADD COLUMN {col} {ddl}")
        if "oline" not in spot_cols:
            self._exec("ALTER TABLE hh_spots ADD COLUMN oline TEXT")

        rows = self._exec("SELECT id, doc_id, front, key FROM cards").fetchall()
        seen = {}
        for r in rows:
            k = r["key"] or hashlib.sha1(re.sub(r"[\s\W_]+", "", r["front"]).encode()).hexdigest()[:16]
            dup = (r["doc_id"], k)
            if dup in seen:
                self._exec("DELETE FROM cards WHERE id = ?", (r["id"],))
                continue
            seen[dup] = r["id"]
            if not r["key"]:
                self._exec("UPDATE cards SET key = ? WHERE id = ?", (k, r["id"]))
        self._exec("CREATE UNIQUE INDEX IF NOT EXISTS idx_cards_key ON cards(doc_id, key)")

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---------------- docs / chunks ----------------

    def upsert_doc(self, path: str, kind: str, title: str, mtime: float = 0, meta: dict | None = None) -> tuple[int, bool]:
        """返回 (doc_id, 是否需要重建切片)。路径或 mtime 变了就需要重建。"""
        row = self._exec("SELECT id, mtime FROM docs WHERE path = ?", (path,)).fetchone()
        if row:
            if abs((row["mtime"] or 0) - mtime) < 1e-6:
                return row["id"], False
            self._exec(
                "UPDATE docs SET kind=?, title=?, mtime=?, meta=? WHERE id=?",
                (kind, title, mtime, json.dumps(meta or {}, ensure_ascii=False), row["id"]),
            )
            self._exec("DELETE FROM chunks WHERE doc_id = ?", (row["id"],))
            return row["id"], True
        cur = self._exec(
            "INSERT INTO docs(path, kind, title, mtime, meta) VALUES (?, ?, ?, ?, ?)",
            (path, kind, title, mtime, json.dumps(meta or {}, ensure_ascii=False)),
        )
        return int(cur.lastrowid), True

    def replace_chunks(self, doc_id: int, chunks: list[dict]) -> None:
        self._exec("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        for i, c in enumerate(chunks):
            self._exec(
                "INSERT INTO chunks(doc_id, ord, text, heading, start, end) VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, i, c["text"], c.get("heading", ""), c.get("start"), c.get("end")),
            )

    def replace_cards(self, doc_id: int, cards: list[dict]) -> None:
        self._exec("DELETE FROM cards WHERE doc_id = ?", (doc_id,))
        for c in cards:
            self._exec(
                "INSERT INTO cards(doc_id, front, back, tags, key, kind, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doc_id, c["front"], c["back"], c.get("tags", ""), c.get("key", ""), c.get("kind", ""), now()),
            )

    def sync_cards(self, doc_id: int, cards: list[dict]) -> tuple[int, int]:
        """增量同步：key 相同的保留（复习进度跟着走），只增删真正变化的卡。"""
        existing = {
            r["key"]: r["id"] for r in self._exec("SELECT id, key FROM cards WHERE doc_id = ?", (doc_id,))
        }
        keep, added = set(), 0
        for c in cards:
            k = c.get("key") or ""
            if not k:
                continue
            keep.add(k)
            if k in existing:
                # 卡片内容可能被重新生成过（换了 kind/答案），同步一下，但不动复习记录
                self._exec(
                    "UPDATE cards SET back = ?, tags = ?, kind = ?, options = ? WHERE doc_id = ? AND key = ?",
                    (c["back"], c.get("tags", ""), c.get("kind", ""),
                     json.dumps(c["options"], ensure_ascii=False) if c.get("options") else None,
                     doc_id, k),
                )
                continue
            self._exec(
                "INSERT INTO cards(doc_id, front, back, tags, key, kind, options, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, c["front"], c["back"], c.get("tags", ""), k, c.get("kind", ""),
                 json.dumps(c["options"], ensure_ascii=False) if c.get("options") else None,
                 now()),
            )
            added += 1
        stale = [cid for k, cid in existing.items() if k not in keep]
        for cid in stale:
            self._exec("DELETE FROM cards WHERE id = ?", (cid,))
        return added, len(stale)

    def all_chunks(self) -> list[sqlite3.Row]:
        return self._exec(
            """SELECT c.id, c.doc_id, c.text, c.heading, c.start, c.end, d.title, d.path, d.kind
               FROM chunks c JOIN docs d ON d.id = c.doc_id ORDER BY d.title, c.ord"""
        ).fetchall()

    def doc(self, doc_id: int):
        return self._exec("SELECT * FROM docs WHERE id = ?", (doc_id,)).fetchone()

    def stats(self) -> dict:
        q = lambda sql: self._exec(sql).fetchone()[0]
        return {
            "docs": q("SELECT COUNT(*) FROM docs"),
            "chunks": q("SELECT COUNT(*) FROM chunks"),
            "cards": q("SELECT COUNT(*) FROM cards"),
            "hands": q("SELECT COUNT(*) FROM hands"),
            "hh": q("SELECT COUNT(*) FROM hh"),
            "due": self.due_count(),
            "hidden_cards": q("SELECT COUNT(*) FROM cards WHERE quality IS NOT NULL AND quality < 6"),
            "card_kinds": {
                r["kind"]: r["n"]
                for r in self._exec("SELECT kind, COUNT(*) AS n FROM cards GROUP BY kind")
            },
        }

    # ---------------- 卡片 / 复习 ----------------

    def due_cards(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._exec(
            """SELECT c.*, r.ease, r.interval, r.reps, r.lapses, r.due
               FROM cards c LEFT JOIN reviews r ON r.card_id = c.id
               WHERE (c.quality IS NULL OR c.quality >= 6)
                 AND (r.due IS NULL OR r.due <= ?)
               ORDER BY CASE WHEN c.tags LIKE '策略树%' THEN 0 ELSE 1 END,
                        CASE WHEN c.kind IN ('rule','principle','spot') THEN 0 ELSE 1 END,
                        COALESCE(r.due, '') ASC LIMIT ?""",
            (now(), limit),
        ).fetchall()

    def due_count(self) -> int:
        """真实待复习数量。due_cards 有 limit，不能拿 len() 当总数。"""
        row = self._exec(
            """SELECT COUNT(*) FROM cards c LEFT JOIN reviews r ON r.card_id = c.id
               WHERE (c.quality IS NULL OR c.quality >= 6)
                 AND (r.due IS NULL OR r.due <= ?)""",
            (now(),),
        ).fetchone()
        return int(row[0]) if row else 0

    def all_cards(self, limit: int = 200) -> list[sqlite3.Row]:
        return self._exec("SELECT * FROM cards ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def review(self, card_id: int, grade: int) -> dict:
        """grade: 0=忘了 1=勉强 2=记得 3=太简单。SM-2 简化版。"""
        row = self._exec("SELECT * FROM reviews WHERE card_id = ?", (card_id,)).fetchone()
        ease = row["ease"] if row else 2.5
        interval = row["interval"] if row else 0.0
        reps = row["reps"] if row else 0
        lapses = row["lapses"] if row else 0

        if grade == 0:
            ease = max(1.3, ease - 0.2)
            interval = 1.0
            lapses += 1
        elif grade == 1:
            ease = max(1.3, ease - 0.1)
            interval = max(1.0, interval * 1.2)
        elif grade == 2:
            interval = 1.0 if interval < 1 else interval * ease
        else:
            ease = min(2.9, ease + 0.1)
            interval = 1.0 if interval < 1 else interval * ease * 1.3

        reps += 1
        due = datetime.now(timezone.utc) + timedelta(days=interval)
        self._exec(
            """INSERT INTO reviews(card_id, ease, interval, due, reps, lapses, last)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(card_id) DO UPDATE SET
                 ease=excluded.ease, interval=excluded.interval, due=excluded.due,
                 reps=excluded.reps, lapses=excluded.lapses, last=excluded.last""",
            (card_id, ease, interval, due.isoformat(timespec="seconds"), reps, lapses, now()),
        )
        self.conn.commit()
        return {"card_id": card_id, "ease": round(ease, 2), "interval_days": round(interval, 1), "due": due.isoformat(timespec="seconds"), "reps": reps}

    def set_quality(self, card_id: int, score: int) -> None:
        self._exec("UPDATE cards SET quality = ? WHERE id = ?", (score, card_id))

    def delete_card(self, card_id: int) -> bool:
        cur = self._exec("DELETE FROM cards WHERE id = ?", (card_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ---------------- 手牌历史 ----------------

    def add_hh(self, rows: list[dict]) -> int:
        cur = self.conn.executemany(
            """INSERT OR REPLACE INTO hh(hand_id, played_at, stakes, hero, board, pot, net, bb, flags, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    r["hand_id"], r["played_at"], r["stakes"], r["hero"], r["board"],
                    r["pot"], r["net"], r["bb"], json.dumps(r["flags"], ensure_ascii=False),
                    json.dumps(r["data"], ensure_ascii=False),
                )
                for r in rows
            ],
        )
        self.conn.commit()
        return len(rows)

    def add_spots(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        cols = ("hand_id", "street", "role", "pot_type", "hero_pos", "villain_pos", "matchup",
                "high", "suit", "extra", "paired", "connected", "runout", "size", "line", "oline", "vtype",
                "board", "hand", "facing", "action", "pot", "net", "bb")
        self.conn.executemany(
            f"INSERT INTO hh_spots({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
            [tuple(r.get(c) for c in cols) for r in rows],
        )
        self.conn.commit()
        return len(rows)

    def clear_spots(self) -> None:
        self._exec("DELETE FROM hh_spots")
        self.conn.commit()

    def all_hh_flags(self) -> list[dict]:
        out = []
        for row in self._exec("SELECT flags FROM hh"):
            try:
                out.append(json.loads(row["flags"]))
            except Exception:
                continue
        return out

    def hh_stats(self) -> dict:
        row = self._exec(
            "SELECT COUNT(*) AS n, MIN(played_at) AS a, MAX(played_at) AS b, SUM(net) AS net FROM hh"
        ).fetchone()
        return {"hands": row["n"], "first": row["a"] or "", "last": row["b"] or "", "net": round(row["net"] or 0, 2)}

    def clear_hh(self) -> None:
        self._exec("DELETE FROM hh")
        self.conn.commit()

    # ---------------- 复盘手牌 ----------------

    def add_hand(self, data: dict) -> int:
        cur = self._exec(
            """INSERT INTO hands(created, stake, hero, villain, position, board, pot, action, notes, tags, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now(), data.get("stake", ""), data.get("hero", ""), data.get("villain", ""),
                data.get("position", ""), data.get("board", ""), float(data.get("pot", 0) or 0),
                data.get("action", ""), data.get("notes", ""), data.get("tags", ""),
                json.dumps(data.get("data", {}), ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def hands(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._exec("SELECT * FROM hands ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # ---------------- 闯关 / 成就 ----------------

    def record_attempt(self, card_id: int, level: int, correct: bool) -> None:
        self._exec(
            "INSERT INTO quiz_attempts(card_id, level, correct, created) VALUES (?, ?, ?, ?)",
            (card_id, level, 1 if correct else 0, now()),
        )
        self.conn.commit()

    def attempt_rows(self) -> list:
        return self._exec("SELECT * FROM quiz_attempts ORDER BY id").fetchall()

    def level_stats(self) -> dict:
        rows = self._exec(
            "SELECT level, COUNT(*) AS n, SUM(correct) AS ok, COUNT(DISTINCT card_id) AS cards FROM quiz_attempts GROUP BY level"
        ).fetchall()
        return {r["level"]: {"n": r["n"], "ok": r["ok"] or 0, "cards": r["cards"]} for r in rows}

    def list_note_rules(self, street: str = "", role: str = "", limit: int = 500) -> list[dict]:
        where, args = [], []
        if street:
            where.append("(street = ? OR street = '')")   # 通用规则也带出来
            args.append(street)
        if role:
            where.append("role = ?")
            args.append(role)
        sql = "SELECT * FROM note_rules"
        if where:
            sql += " WHERE " + " AND ".join(where)
        # 按街道筛选时，把"通用"规则排前面，免得被埋在后面看不见
        sql += " ORDER BY (street = '') DESC, id DESC LIMIT ?" if street else " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._exec(sql, args)]

    def update_note_rule(self, rid: int, fields: dict) -> None:
        allowed = ("freq", "size", "why", "avoid", "street", "role", "high", "suit",
                   "paired", "connected", "runout", "oline", "pot_type", "enabled", "game_type", "scope")
        old = self._exec("SELECT * FROM note_rules WHERE id = ?", (rid,)).fetchone()
        if not old:
            return
        sets, args = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = ?")
            args.append(v)
            if str(old[k]) != str(v):   # 留痕：谁改了什么
                self._exec(
                    "INSERT INTO rule_history(rule_id, field, old, new, at) VALUES (?, ?, ?, ?, ?)",
                    (rid, k, str(old[k]), str(v), now()),
                )
        if sets:
            sets.append("updated = ?")
            args.extend([now(), rid])
            self._exec(f"UPDATE note_rules SET {','.join(sets)} WHERE id = ?", args)
            self.conn.commit()

    def rule_history(self, limit: int = 50) -> list[dict]:
        return [
            dict(r) for r in self._exec(
                "SELECT h.*, r.freq AS rule_freq FROM rule_history h "
                "LEFT JOIN note_rules r ON r.id = h.rule_id ORDER BY h.id DESC LIMIT ?",
                (limit,),
            )
        ]

    def delete_note_rule(self, rid: int) -> None:
        self._exec("DELETE FROM note_rules WHERE id = ?", (rid,))
        self.conn.commit()

    def add_note_rule(self, r: dict) -> None:
        cols = ("street", "role", "high", "suit", "paired", "connected", "runout",
                "oline", "pot_type", "freq", "size", "why", "avoid",
                "source_title", "source_heading", "source_chunk")
        self._exec(
            f"INSERT INTO note_rules({','.join(cols)}, created) VALUES ({','.join('?'*len(cols))}, ?)",
            [r.get(c, "") for c in cols] + [now()],
        )
        self.conn.commit()

    def match_note_rule(self, filters: dict) -> dict | None:
        keys = ("street", "role", "high", "suit", "paired", "connected", "runout", "oline", "pot_type")
        where = ["enabled = 1", "COALESCE(game_type, 'cash') != 'mtt'"]
        args = []
        for k in keys:
            if k == "street":
                # 没标街道的规则默认不参与匹配（除非人工标成通用）
                where.append("(street = ? OR scope = 'universal')")
                args.append(str(filters.get(k) or ""))
                continue
            where.append(f"({k} = '' OR {k} = ?)")
            args.append(str(filters.get(k) or ""))
        spec = " + ".join(f"CASE WHEN {k} != '' THEN 1 ELSE 0 END" for k in keys)
        row = self._exec(
            f"SELECT *, ({spec}) AS specificity FROM note_rules WHERE {' AND '.join(where)} "
            f"ORDER BY specificity DESC, id DESC LIMIT 1",
            args,
        ).fetchone()
        return dict(row) if row else None

    def note_rule_count(self) -> int:
        return self._exec("SELECT COUNT(*) c FROM note_rules").fetchone()["c"]

    def log_sim(self, row: dict) -> None:
        self._exec(
            "INSERT INTO sim_log(created, street, board, hero, facing, action, advice_freq, advice_size, equity, pot, style, agree) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now(), row.get("street"), row.get("board"), row.get("hero"), row.get("facing", 0),
                row.get("action"), row.get("advice_freq"), row.get("advice_size"),
                row.get("equity", 0), row.get("pot", 0), row.get("style"), row.get("agree"),
            ),
        )
        self.conn.commit()

    def sim_report(self) -> dict:
        row = self._exec(
            "SELECT COUNT(*) n, SUM(agree) ok FROM sim_log WHERE agree IS NOT NULL"
        ).fetchone()
        n, ok = row["n"] or 0, row["ok"] or 0
        by_street = [
            dict(r) for r in self._exec(
                "SELECT street, COUNT(*) n, SUM(agree) ok FROM sim_log WHERE agree IS NOT NULL GROUP BY street"
            )
        ]
        by_style = [
            dict(r) for r in self._exec(
                "SELECT style, COUNT(*) n, SUM(agree) ok FROM sim_log WHERE agree IS NOT NULL GROUP BY style"
            )
        ]
        recent = [
            dict(r) for r in self._exec(
                "SELECT street, board, hero, action, advice_freq, agree FROM sim_log ORDER BY id DESC LIMIT 8"
            )
        ]
        return {
            "hands": n,
            "agree_pct": round(ok / n * 100, 1) if n else None,
            "by_street": by_street,
            "by_style": by_style,
            "recent": recent,
        }

    def profile_get(self, k: str, default: str = "") -> str:
        row = self._exec("SELECT v FROM profile WHERE k = ?", (k,)).fetchone()
        return row["v"] if row else default

    def profile_set(self, k: str, v: str) -> None:
        self._exec(
            "INSERT INTO profile(k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, v)
        )
        self.conn.commit()

    def get_setting(self, k: str, default: str = "") -> str:
        row = self._exec("SELECT v FROM settings WHERE k = ?", (k,)).fetchone()
        return row["v"] if row else default

    def set_setting(self, k: str, v: str) -> None:
        self._exec(
            "INSERT INTO settings(k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v)
        )
        self.conn.commit()
