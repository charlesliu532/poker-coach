"""本地 Web 服务：标准库实现，零额外依赖。只监听 127.0.0.1。"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import odds as odds_mod
from .coach import Coach
from .equity import equity as equity_fn
from .equity import equity_multi
from .ingest import ingest
from .store import Store
from .paths import data_path

WEB_DIR = Path(__file__).parent / "web"
_INGEST_LOCK = threading.Lock()
_LEAK_CACHE: dict = {"at": 0.0, "data": None}
_RANGE_CACHE: dict = {}
_COACH_CACHE: dict = {}
_SIM: dict = {"n": 0, "hands": {}}


def _sanitize(o):
    """把 NaN/Infinity/不可序列化对象转成安全值。"""
    import math
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_sanitize(v) for v in o]
    if isinstance(o, (str, int, bool)) or o is None:
        return o
    return str(o)


class Handler(BaseHTTPRequestHandler):
    store: Store = None  # type: ignore
    coach: Coach = None  # type: ignore
    protocol_version = "HTTP/1.1"

    # ---------------- 基础工具 ----------------

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        # NaN/Infinity 不是合法 JSON，前端 JSON.parse 会整页失败。
        # 用 default 把非序列化对象转成字符串，用 allow_nan=False 暴露真问题，
        # 但兜底一次：真的含 NaN 就整体清洗后重序列化，不让整个请求 500。
        try:
            body = json.dumps(data, ensure_ascii=False, allow_nan=False,
                              default=lambda o: None).encode()
        except (ValueError, TypeError):
            body = json.dumps(_sanitize(data), ensure_ascii=False,
                              allow_nan=False, default=str).encode()
        self._send(code, body)

    def _error(self, msg: str, code: int = 400):
        self._json({"error": msg}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            raise ValueError("请求体不是合法 JSON")

    # ---------------- 路由 ----------------

    def do_GET(self):
        url = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            # ── 只接受本机来源 ──
            _host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
            if _host not in ("127.0.0.1", "localhost", "::1", ""):
                return self._error("bad host", 403)
            _origin = self.headers.get("Origin")
            if _origin and not _origin.startswith(("http://127.0.0.1", "http://localhost")):
                return self._error("bad origin", 403)

            if url.path == "/":
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if url.path == "/api/rules/history":
                return self._json({"history": self.store.rule_history(int(qs.get("limit", 50)))})
            if url.path == "/api/adjustments":
                from . import config as _cfg
                return self._json({"cfg": _cfg.load(), "version": _cfg.version()})
            if url.path == "/api/debug/effective-config":
                from . import config as _cfg
                return self._json(_cfg.effective_report())
            if url.path == "/api/scenarios":
                from .playertypes import compare_scenarios
                return self._json(compare_scenarios(
                    qs.get("board", "A72r"), qs.get("type", "标准"),
                    qs.get("hero", "BTN"), qs.get("opp", "BB")))
            if url.path == "/api/vs-type":
                from .playertypes import analyze_vs
                return self._json(analyze_vs(
                    qs.get("board", "A72r"), qs.get("type", "紧凶"),
                    qs.get("hero", "BTN"), qs.get("opp", "BB"),
                    qs.get("pot", "SRP")))
            if url.path == "/api/player-types":
                from .playertypes import options
                return self._json({"types": options()})
            if url.path == "/api/rules":
                return self._json(self._tree_rules(qs))
            if url.path == "/api/library":
                return self._json(self._library())
            if url.path == "/api/rules/update":
                rid = int(data.get("id", 0))
                if not rid:
                    return self._error("缺少 id")
                self.store.update_note_rule(rid, data.get("fields") or {})
                return self._json({"ok": True})
            if url.path == "/api/rules/delete":
                rid = int(data.get("id", 0))
                if not rid:
                    return self._error("缺少 id")
                self.store.delete_note_rule(rid)
                return self._json({"ok": True})
            if url.path == "/api/sim/types/suggest":
                return self._json(self._suggest_range(data.get("id", "")))
            if url.path == "/api/sim/types":
                from .playertypes import combo_pct, options
                items = options(self.store)
                for it in items:
                    it["combo_pct"] = combo_pct(it["range"]) if it.get("range") else None
                return self._json({"types": items})
            if url.path == "/api/sim/report":
                return self._json(self.store.sim_report())
            if url.path == "/api/sim/new":
                from .sim import new_hand
                _SIM["n"] += 1
                sid = str(_SIM["n"])
                st = new_hand(pot_type=data.get("pot_type") or "SRP", style=data.get("style") or "通用")
                _SIM["hands"][sid] = st
                return self._json({"id": sid, "state": st})
            if url.path == "/api/sim/act":
                from .sim import act as sim_act
                sid = str(data.get("id"))
                st = _SIM["hands"].get(sid)
                if not st:
                    return self._error("这手牌已经结束了", 404)
                snapshot = dict(st)
                try:
                    out = sim_act(st, data.get("action", "check"), data.get("amount"), store=self.store)
                except ValueError as e:
                    return self._error(str(e))
                # 课程引用：按牌面 + 动作检索你的笔记
                try:
                    from .cards import card_str
                    board_txt = " ".join(card_str(c) for c in snapshot["board"])
                    act_cn = {"fold": "弃牌", "check": "过牌", "call": "跟注", "bet": "下注", "raise": "加注"}.get(data.get("action"), "")
                    hits = self.coach.search(f"{board_txt} {act_cn} 翻后 策略", k=1)
                    if hits:
                        out["note"] = {
                            "title": hits[0]["title"],
                            "heading": hits[0]["heading"],
                            "preview": hits[0]["preview"][:180],
                        }
                except Exception:
                    pass
                # 记录决策（用于"模拟漏洞"）
                adv = snapshot.get("advice") or {}
                aggressive = any(w in (adv.get("freq") or "") for w in ("下注", "加注", "领打"))
                passive = any(w in (adv.get("freq") or "") for w in ("弃牌", "过牌", "跟注"))
                act_dir = "ag" if data.get("action") in ("bet", "raise") else "pa"
                agree = None
                if aggressive and not passive:
                    agree = 1 if act_dir == "ag" else 0
                elif passive and not aggressive:
                    agree = 1 if act_dir == "pa" else 0
                try:
                    self.store.log_sim({
                        "street": snapshot.get("street"),
                        "board": " ".join(__import__("pokercoach.cards", fromlist=["card_str"]).card_str(c) for c in snapshot["board"]),
                        "hero": " ".join(__import__("pokercoach.cards", fromlist=["card_str"]).card_str(c) for c in snapshot["hero"]),
                        "facing": snapshot.get("facing", 0),
                        "action": data.get("action"),
                        "advice_freq": adv.get("freq"),
                        "advice_size": adv.get("size"),
                        "equity": snapshot.get("equity", {}).get("equity", 0),
                        "pot": snapshot.get("pot", 0),
                        "style": snapshot.get("style"),
                        "agree": agree,
                    })
                except Exception:
                    pass
                if out.get("state"):
                    _SIM["hands"][sid] = out["state"]
                return self._json(out)
            if url.path == "/api/postflop/practice":
                return self._json(self._practice(data))
            if url.path == "/api/config":
                return self._json(self.coach.config_info())
            if url.path == "/health":
                from . import __version__ as _appver
                return self._json({"ok": True, "port": getattr(self.server, "server_port", 8770),
                                   "version": "v10", "app_version": _appver})
            if url.path == "/api/status":
                return self._json(self._status())
            if url.path == "/api/search":
                q = (qs.get("q") or "").strip()
                if not q:
                    return self._error("缺少 q")
                return self._json({"results": self.coach.search(q, k=int(qs.get("k", 8)))})
            if url.path == "/api/preflop/range":
                from . import tree as _t
                fn = _t.preflop_freq_matrix if qs.get("freq") == "1" else _t.preflop_range_matrix
                return self._json(fn(qs.get("pos", "BTN"), qs.get("opp", "BB"),
                                     qs.get("kind", "open"), qs.get("vs_type", "*")))
            if url.path == "/api/locks":
                from . import locks as _lk
                ls = _lk.load()
                return self._json({"constraints": [a.__dict__ for a in ls.constraints],
                                   "semantics": ls.semantics, "describe": _lk.describe(ls)})
            if url.path == "/api/tree":
                from . import tree as tree_mod
                tdir = data_path("tree")
                if not (tdir / "rules.csv").exists():
                    tdir = data_path("tree")
                try:
                    out = tree_mod.grid(
                        tdir,
                        qs.get("pot", "SRP"), qs.get("role", "IP-PFR"),
                        qs.get("board", "A72r"), qs.get("street", "翻牌"),
                        qs.get("action", "对手过牌"),
                        qs.get("hero_pos", "*"), qs.get("opp_pos", "*"), qs.get("stack", "*"),
                        qs.get("runout", "*"), qs.get("line", "*"), qs.get("vs_type", "*"), qs.get("capped", "*"), qs.get("path", ""),
                        qs.get("hero_stack", "*"), qs.get("villain_stack", "*"),
                        multi=qs.get("multi", "0") in ("1", "true", "yes"),
                        simplify=qs.get("simplify", "0") in ("1", "true", "yes"),
                        locks=(__import__("pokercoach.locks", fromlist=["load"]).load()
                               if qs.get("locks", "1") != "0" else None),
                        preflop_line=qs.get("pf", ""),
                        vs_type2=qs.get("vs_type2", "*"),
                    )
                except ValueError as e:
                    return self._error(str(e))
                return self._json(out)
            if url.path == "/api/outline":
                return self._json({"docs": self.coach.outline()})
            if url.path == "/api/plan":
                return self._json(self.coach.plan(int(qs.get("minutes", 25))))
            if url.path == "/api/postflop/presets":
                from .hh.advice import presets_for
                return self._json({"presets": presets_for(qs.get("street", "flop"))})
            if url.path == "/api/postflop/options":
                rows = self.store.conn.execute(
                    "SELECT matchup, COUNT(*) AS n FROM hh_spots WHERE matchup != '' GROUP BY matchup ORDER BY n DESC LIMIT 15"
                ).fetchall()
                return self._json({"matchups": [{"v": r["matchup"], "n": r["n"]} for r in rows]})
            if url.path == "/api/postflop/coach":
                return self._json(self._postflop_coach(qs))
            if url.path == "/api/postflop/findings":
                from .hh.spotdb import aggregate, findings
                filters = {k: qs.get(k) for k in ("street", "role", "pot_type")}
                rows = aggregate(self.store.conn, filters, qs.get("group", "high"))
                lines = {r["label"]: r["actions"] for r in aggregate(self.store.conn, filters, qs.get("group", "high"), field="line")}
                for r in rows:
                    r["lines"] = lines.get(r["label"], {})
                from .hh.advice import advice_for
                from .hh.spotdb import combo_findings
                lvl = qs.get("street", "flop")
                adv = advice_for({k: qs.get(k) for k in ("street", "role", "high", "suit", "paired", "connected", "runout", "pot_type", "vtype", "line", "oline")}, self.store)
                combos = combo_findings(
                    self.store.conn, lvl, qs.get("role", ""), qs.get("pot_type", ""),
                    min_n=40 if lvl == "flop" else 25,
                    filters={k: qs.get(k) for k in ("high", "suit", "paired", "connected", "size", "matchup")},
                )
                return self._json({
                    "findings": findings(rows, lvl, qs.get("role", ""), qs.get("group", "high")),
                    "rows": rows,
                    "advice": adv,
                    "combos": combos,
                })
            if url.path == "/api/spot-hands":
                from .hh.spotdb import hands as spot_hands
                filters = {k: qs.get(k) for k in ("street", "role", "pot_type", "high", "matchup", "runout", "facing", "hand", "action")}
                return self._json({"hands": spot_hands(self.store.conn, filters, int(qs.get("limit", 60)))})
            if url.path == "/api/hand":
                import json as _json
                row = self.store.conn.execute("SELECT data FROM hh WHERE hand_id = ?", (qs.get("id", ""),)).fetchone()
                if not row:
                    return self._error("找不到这手牌", 404)
                from .hh.spotdb import render_hand_detail
                return self._json({"text": render_hand_detail(_json.loads(row["data"]))})
            if url.path == "/api/campaign":
                from .campaign import status
                return self._json(status(self.store))
            if url.path == "/api/practice":
                from .quiz import scenes

                # 个人样本（GG NL2 的 14798 手）不进公共练习区
                all_scenes = scenes(self.store)
                return self._json({
                    "scenes": [s for s in all_scenes if not s["scene"].startswith("真实牌局")],
                    "personal": [s for s in all_scenes if s["scene"].startswith("真实牌局")],
                })
            if url.path == "/api/quiz" and qs.get("scene"):
                from .quiz import questions_by_scene
                return self._json({"questions": questions_by_scene(self.store, qs["scene"], int(qs.get("n", 10))), "scene": qs["scene"]})
            if url.path == "/api/quiz":
                from .quiz import questions_for_level
                lv = int(qs.get("level", 1))
                fresh = qs.get("fresh", "1") != "0"
                qs_out = questions_for_level(self.store, lv, int(qs.get("n", 10)), fresh=fresh)
                return self._json({"questions": qs_out, "level": lv})
            if url.path == "/api/spots":
                from .hh.spotdb import DIMS, aggregate
                if qs.get("group"):
                    filters = {k: qs.get(k) for k in ("street", "role", "pot_type", "facing")}
                    rows = aggregate(self.store.conn, filters, qs["group"])
                    return self._json({"rows": rows, "dims": DIMS, "group": qs["group"]})
                from .hh.spots import summarize
                flags = self.store.all_hh_flags()
                return self._json(summarize(flags) if flags else {"flop": [], "turn": []})
            if url.path == "/api/range":
                from .hh.rangechart import find_gaps
                pos = qs.get("pos", "BTN").upper()
                key = (pos, self.store.hh_stats()["hands"])
                now = time.time()
                cached = _RANGE_CACHE.get(key)
                if cached and now - cached[0] < 30:
                    return self._json(cached[1])
                flags = self.store.all_hh_flags()
                data = find_gaps(flags, pos) if flags else {"pos": pos, "matrix": [], "missing": [], "extra": []}
                _RANGE_CACHE[key] = (now, data)
                return self._json(data)
            if url.path == "/api/uploads":
                from .upload import list_uploads
                return self._json({"uploads": list_uploads(self.store)})
            if url.path == "/api/plan-auto":
                from .evaluate import auto_plan
                from .treemismatch import analyze as _mm
                from pathlib import Path as _P
                tdir = data_path("tree")
                try:
                    mm = _mm(self.store, tdir, 10)
                except Exception:
                    mm = {"nodes": []}
                return self._json(auto_plan(self.store, tdir, self._leaks(), mm,
                                            int(qs.get("minutes", 25))))
            if url.path == "/api/evaluate":
                from .evaluate import evaluate
                from .treemismatch import analyze as _mm
                from pathlib import Path as _P
                tdir = data_path("tree")
                try:
                    mm = _mm(self.store, tdir, 10)
                except Exception:
                    mm = {"nodes": []}
                return self._json(evaluate(self.store, tdir, self._leaks(), mm))
            if url.path == "/api/tree-mismatch":
                from .treemismatch import analyze
                from pathlib import Path as _P
                tdir = data_path("tree")
                return self._json(analyze(self.store, tdir,
                                          int(qs.get("min_n", 12)), int(qs.get("limit", 40))))
            if url.path == "/api/leaks":
                return self._json(self._leaks())
            if url.path == "/api/progress":
                from .progress import overview
                return self._json(overview(self.store))
            if url.path == "/api/mistakes":
                from .progress import mistakes
                return self._json({"mistakes": mistakes(self.store, int(qs.get("limit", 12)))})
            if url.path == "/api/path":
                from .path import build_path
                priority = self._leaks().get("priority_topics", [])
                return self._json(
                    build_path(
                        self.store, weeks=int(qs.get("weeks", 4)), days_per_week=int(qs.get("days", 5)),
                        priority=priority,
                    )
                )
            if url.path == "/api/cards":
                topic = (qs.get("topic") or "").strip()
                rows = self.store.due_cards(limit=400 if topic else int(qs.get("limit", 100)))
                if topic:
                    from .progress import doc_topics
                    m = doc_topics(self.store)
                    rows = [r for r in rows if m.get(r["doc_id"]) == topic][: int(qs.get("limit", 100))]
                due_total = self.store.due_count()
                return self._json({"cards": [dict(r) for r in rows],
                                   "total": self.store.stats()["cards"],
                                   "due_total": due_total,
                                   "truncated": due_total > len(rows)})
            if url.path == "/api/hands":
                return self._json({"hands": [dict(r) for r in self.store.hands()]})
            if url.path == "/api/chunk":
                cid = int(qs.get("id", 0))
                row = self.store.conn.execute(
                    """SELECT c.id, c.text, c.heading, c.start, d.title, d.path
                       FROM chunks c JOIN docs d ON d.id = c.doc_id WHERE c.id = ?""",
                    (cid,),
                ).fetchone()
                if not row:
                    return self._error("找不到这段内容", 404)
                import re as _re
                raw = row["text"] or ""
                # notion 的页面 id 只在每篇的第一个切片里，回查一下
                first = self.store.conn.execute(
                    "SELECT text FROM chunks WHERE doc_id = (SELECT doc_id FROM chunks WHERE id = ?) ORDER BY ord LIMIT 1",
                    (cid,),
                ).fetchone()
                probe = (first["text"] if first else "") + raw
                m = _re.search(r"notion-page:\s*([0-9a-f-]{32,36})", probe)
                notion_url = ""
                if m:
                    notion_url = "https://www.notion.so/" + m.group(1).replace("-", "")
                text = _re.sub(r"<!--.*?-->", "", raw, flags=_re.S).strip()
                return self._json({"chunk": {**dict(row), "text": text, "notion_url": notion_url}})
            if url.path == "/api/doc":
                doc = self.store.doc(int(qs.get("id", 0)))
                if not doc:
                    return self._error("文档不存在", 404)
                chunks = [dict(c) for c in self.store.all_chunks() if c["doc_id"] == doc["id"]]
                return self._json({"doc": dict(doc), "chunks": chunks})
            return self._error("没有这个接口", 404)
        except Exception as e:
            traceback.print_exc()
            return self._error(str(e), 500)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            # ── 本地服务防护：只接受本机来源，挡住恶意网页/DNS rebinding ──
            _host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
            if _host not in ("127.0.0.1", "localhost", "::1", ""):
                return self._error("bad host", 403)
            _origin = self.headers.get("Origin")
            if _origin and not _origin.startswith(("http://127.0.0.1", "http://localhost")):
                return self._error("bad origin", 403)
            data = self._body()
            if url.path == "/api/locks":
                from . import locks as _lk
                ls = _lk.load()
                act = data.get("action", "set")
                if act == "clear":
                    ls.clear()
                elif act == "remove":
                    ls.remove(data.get("pos", ""))
                else:
                    ls.set(_lk.Constraint(pos=data.get("pos", ""),
                        ctype=data.get("ctype", "range"),
                        payload=data.get("payload", ""),
                        player_type=data.get("player_type", "*"),
                        stack=data.get("stack", "*"),
                        note=data.get("note", "")))
                if data.get("semantics") in _lk.SEMANTICS:
                    ls.semantics = data["semantics"]
                _lk.save(ls)
                return self._json({"ok": True, "describe": _lk.describe(ls),
                                   "semantics": ls.semantics})
            if url.path == "/api/upload-hh":
                from .upload import save_and_import
                from pathlib import Path as _P
                b = data or {}
                txt = b.get("text") or ""
                if not txt.strip():
                    return self._error("文件是空的", 400)
                root = data_path()
                out = save_and_import(
                    self.store, root,
                    platform=b.get("platform", ""), stakes=b.get("stakes", ""),
                    period_from=b.get("period_from", ""), period_to=b.get("period_to", ""),
                    filename=b.get("filename", "hh.txt"), text=txt)
                return self._json(out)
            if url.path == "/api/rules/history":
                return self._json({"history": self.store.rule_history(int(qs.get("limit", 50)))})
            if url.path == "/api/adjustments":
                from .playertypes import merge_adjustments
                merged = merge_adjustments((data or {}).get("cfg") or (data or {}))
                return self._json({"ok": True, "merged": merged})
            if url.path == "/api/scenarios":
                from .playertypes import compare_scenarios
                return self._json(compare_scenarios(
                    qs.get("board", "A72r"), qs.get("type", "标准"),
                    qs.get("hero", "BTN"), qs.get("opp", "BB")))
            if url.path == "/api/vs-type":
                from .playertypes import analyze_vs
                return self._json(analyze_vs(
                    qs.get("board", "A72r"), qs.get("type", "紧凶"),
                    qs.get("hero", "BTN"), qs.get("opp", "BB"),
                    qs.get("pot", "SRP")))
            if url.path == "/api/player-types":
                from .playertypes import options
                return self._json({"types": options()})
            if url.path == "/api/rules":
                return self._json(self._tree_rules(qs))
            if url.path == "/api/library":
                return self._json(self._library())
            if url.path == "/api/rules/update":
                rid = int(data.get("id", 0))
                if not rid:
                    return self._error("缺少 id")
                self.store.update_note_rule(rid, data.get("fields") or {})
                return self._json({"ok": True})
            if url.path == "/api/rules/delete":
                rid = int(data.get("id", 0))
                if not rid:
                    return self._error("缺少 id")
                self.store.delete_note_rule(rid)
                return self._json({"ok": True})
            if url.path == "/api/sim/types/suggest":
                return self._json(self._suggest_range(data.get("id", "")))
            if url.path == "/api/sim/types":
                from .playertypes import combo_pct
                from .ranges import parse_range
                tid = (data.get("id") or "").strip()
                if not tid:
                    return self._error("缺少类型 id")
                if data.get("reset"):
                    self.store.conn.execute("DELETE FROM profile WHERE k = ?", (f"ptype:{tid}",))
                    self.store.conn.commit()
                    return self._json({"ok": True, "reset": True})
                rng = (data.get("range") or "").strip()
                try:
                    parse_range(rng)
                except Exception as e:
                    return self._error(f"范围解析失败：{e}")
                payload = {"range": rng}
                if data.get("vpip"):
                    payload["vpip"] = data["vpip"].strip()
                if data.get("desc"):
                    payload["desc"] = data["desc"].strip()
                import json as _json
                self.store.profile_set(f"ptype:{tid}", _json.dumps(payload, ensure_ascii=False))
                return self._json({"ok": True, "combo_pct": combo_pct(rng)})
            if url.path == "/api/sim/report":
                return self._json(self.store.sim_report())
            if url.path == "/api/sim/new":
                from .sim import new_hand
                _SIM["n"] += 1
                sid = str(_SIM["n"])
                st = new_hand(pot_type=data.get("pot_type") or "SRP", style=data.get("style") or "通用")
                _SIM["hands"][sid] = st
                return self._json({"id": sid, "state": st})
            if url.path == "/api/sim/act":
                from .sim import act as sim_act
                sid = str(data.get("id"))
                st = _SIM["hands"].get(sid)
                if not st:
                    return self._error("这手牌已经结束了", 404)
                snapshot = dict(st)
                try:
                    out = sim_act(st, data.get("action", "check"), data.get("amount"), store=self.store)
                except ValueError as e:
                    return self._error(str(e))
                # 课程引用：按牌面 + 动作检索你的笔记
                try:
                    from .cards import card_str
                    board_txt = " ".join(card_str(c) for c in snapshot["board"])
                    act_cn = {"fold": "弃牌", "check": "过牌", "call": "跟注", "bet": "下注", "raise": "加注"}.get(data.get("action"), "")
                    hits = self.coach.search(f"{board_txt} {act_cn} 翻后 策略", k=1)
                    if hits:
                        out["note"] = {
                            "title": hits[0]["title"],
                            "heading": hits[0]["heading"],
                            "preview": hits[0]["preview"][:180],
                        }
                except Exception:
                    pass
                # 记录决策（用于"模拟漏洞"）
                adv = snapshot.get("advice") or {}
                aggressive = any(w in (adv.get("freq") or "") for w in ("下注", "加注", "领打"))
                passive = any(w in (adv.get("freq") or "") for w in ("弃牌", "过牌", "跟注"))
                act_dir = "ag" if data.get("action") in ("bet", "raise") else "pa"
                agree = None
                if aggressive and not passive:
                    agree = 1 if act_dir == "ag" else 0
                elif passive and not aggressive:
                    agree = 1 if act_dir == "pa" else 0
                try:
                    self.store.log_sim({
                        "street": snapshot.get("street"),
                        "board": " ".join(__import__("pokercoach.cards", fromlist=["card_str"]).card_str(c) for c in snapshot["board"]),
                        "hero": " ".join(__import__("pokercoach.cards", fromlist=["card_str"]).card_str(c) for c in snapshot["hero"]),
                        "facing": snapshot.get("facing", 0),
                        "action": data.get("action"),
                        "advice_freq": adv.get("freq"),
                        "advice_size": adv.get("size"),
                        "equity": snapshot.get("equity", {}).get("equity", 0),
                        "pot": snapshot.get("pot", 0),
                        "style": snapshot.get("style"),
                        "agree": agree,
                    })
                except Exception:
                    pass
                if out.get("state"):
                    _SIM["hands"][sid] = out["state"]
                return self._json(out)
            if url.path == "/api/postflop/practice":
                return self._json(self._practice(data))
            if url.path == "/api/config":
                if data.get("clear_key"):
                    self.coach.configure(api_key="")
                else:
                    self.coach.configure(
                        api_key=data.get("api_key") if data.get("api_key") is not None else None,
                        model=data.get("model"),
                        base_url=data.get("base_url"),
                    )
                return self._json(self.coach.config_info())
            if url.path == "/api/quiz/flag":
                cid = int(data.get("id", 0))
                ok = self.store.delete_card(cid)
                return self._json({"ok": ok})
            if url.path == "/api/quiz/answer":
                from .campaign import status
                from .quiz import make_question
                q = make_question(self.store, int(data.get("id", 0)))
                if not q:
                    return self._error("这道题不存在", 404)
                choice = int(data.get("choice", -1))
                correct = choice == q["answer"]
                self.store.record_attempt(q["id"], q["level"], correct)
                st = status(self.store)
                return self._json(
                    {
                        "correct": correct,
                        "answer": q["answer"],
                        "explain": q["explain"],
                        "xp": st["xp"],
                        "rank": st["rank"]["name"],
                        "new": st["new_achievements"],
                    }
                )
            if url.path == "/api/ask":
                q = (data.get("q") or "").strip()
                if not q:
                    return self._error("问题不能为空")
                return self._json(self.coach.ask(q, k=int(data.get("k", 6))))
            if url.path == "/api/equity":
                hero = (data.get("hero") or "").strip()
                villain = (data.get("villain") or "").strip()
                board = (data.get("board") or "").strip()
                if not hero or not villain:
                    return self._error("需要 hero 和 villain")
                third = (data.get("third") or "").strip()
                if third:
                    res = equity_multi([hero, villain, third], board, n_samples=int(data.get("n", 20000)))
                    return self._json({"multiway": res.to_dict()})
                res = equity_fn(hero, villain, board, n_samples=int(data.get("n", 20000)))
                return self._json({"equity": res.to_dict()})
            if url.path == "/api/odds":
                pot = float(data.get("pot", 0))
                bet = float(data.get("bet", 0))
                if pot <= 0 or bet <= 0:
                    return self._error("底池和下注都要大于 0")
                eq = data.get("equity")
                eq = float(eq) / 100 if eq not in (None, "") else None
                return self._json({"odds": odds_mod.analyze(pot, bet, eq)})
            if url.path == "/api/review":
                card_id = int(data.get("card_id", 0))
                grade = int(data.get("grade", 2))
                if not 1 <= card_id:
                    return self._error("card_id 非法")
                return self._json(self.store.review(card_id, max(0, min(3, grade))))
            if url.path == "/api/cards/delete":
                ok = self.store.delete_card(int(data.get("card_id", 0)))
                return self._json({"ok": ok})
            if url.path == "/api/hands":
                hid = self.store.add_hand(data)
                return self._json({"id": hid, "ok": True})
            if url.path == "/api/ingest":
                with _INGEST_LOCK:
                    root = Path(data.get("root") or "data")
                    stats = ingest(root, self.store, transcribe_media=bool(data.get("transcribe", True)))
                    self.coach.rebuild()
                return self._json({"stats": stats, "indexed": len(self.coach.bm25.docs)})
            return self._error("没有这个接口", 404)
        except Exception as e:
            traceback.print_exc()
            return self._error(str(e), 500)

    # ---------------- 静态文件 ----------------

    def _static(self, rel: str):
        target = (WEB_DIR / rel).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            return self._error("找不到文件", 404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def _practice(self, data: dict) -> dict:
        """从策略树出题——场景合法、答案由树算出、干扰项是邻近合法值。

        不再让模型自由发挥（那样答案会和选项对不上）。
        """
        import hashlib
        import json as _json

        from . import spots
        from .store import now

        # 前端筛选 → 出题过滤条件
        filters = {}
        if data.get("pot_type"):
            filters["pot"] = data["pot_type"]
        if data.get("role"):
            filters["role"] = data["role"]
        if data.get("street"):
            filters["street"] = {"flop": "翻牌", "turn": "转牌", "river": "河牌"}.get(
                data["street"], data["street"])

        root = data_path("tree")

        try:
            qs = spots.make_questions(root, n=3, filters=filters)
        except Exception as e:
            return {"error": str(e)}
        if not qs:
            return {"added": 0, "scene": "（这个筛选下没有可出的场景）"}

        # 落到对应主题的关卡
        from .topics import best_topic
        want = {"flip": "翻牌持续下注", "翻牌": "翻牌持续下注", "turn": "转牌与双枪",
                "转牌": "转牌与双枪", "river": "河牌与抓诈唬", "河牌": "河牌与抓诈唬"}
        street = (qs[0].get("scene") or {}).get("street") or "翻牌"
        doc_id = None
        for row in self.store.conn.execute("SELECT id, title FROM docs"):
            if best_topic(row["title"]) == want.get(street, "翻牌持续下注"):
                doc_id = row["id"]
                break
        if doc_id is None:
            doc = self.store.conn.execute("SELECT id FROM docs ORDER BY id LIMIT 1").fetchone()
            doc_id = doc["id"] if doc else 1

        added = 0
        for q in qs:
            if not spots.validate_question(q):
                continue
            key = hashlib.sha1(q["front"].encode()).hexdigest()[:16]
            if self.store.conn.execute("SELECT 1 FROM cards WHERE key = ?", (key,)).fetchone():
                continue
            self.store.conn.execute(
                "INSERT INTO cards(doc_id, front, back, tags, key, kind, quality, options, created) "
                "VALUES (?, ?, ?, ?, ?, 'spot', 9, ?, ?)",
                (doc_id, q["front"], q["answer"], q["tags"], key,
                 _json.dumps(q["options"], ensure_ascii=False), now()),
            )
            added += 1
        self.store.conn.commit()
        scene = (qs[0].get("scene") or {}).get("label", "")
        return {"added": added, "scene": scene, "explain": qs[0].get("explain", "")}

    def _postflop_coach(self, qs: dict) -> dict:
        """把当前矩阵喂给模型，让它写一段教练式诊断（10 分钟缓存）。"""
        from .hh.spotdb import DIMS, aggregate

        filters = {k: qs.get(k) for k in ("street", "role", "pot_type")}
        group = qs.get("group", "high")
        key = (tuple(sorted((k, v) for k, v in filters.items() if v)), group)
        now = time.time()
        cached = _COACH_CACHE.get(key)
        if cached and now - cached[0] < 600:
            return cached[1]

        rows = aggregate(self.store.conn, filters, group)
        total = sum(r["n"] for r in rows) or 1
        lines = []
        for r in rows[:8]:
            if group == "size":
                lines.append(f"- {r['label']}：占所有下注 {r['n']/total*100:.0f}%（n={r['n']}）")
                continue
            acts = " ".join(
                f"{a} {r['actions'][a]/r['n']*100:.0f}%"
                for a in ("下注", "过牌", "跟注", "弃牌", "加注", "过牌加注")
                if r["actions"].get(a)
            )
            lines.append(f"- {r['label']}（n={r['n']}）：{acts}")
        if not lines:
            return {"text": "这个组合下没有数据。"}
        prompt = (
            f"下面是我在 {qs.get('street','flop')} 的决策分布，维度是「{DIMS.get(group, group)}」，"
            f"角色：{qs.get('role') or '全部'}，池型：{qs.get('pot_type') or '全部'}。\n\n"
            + "\n".join(lines)
            + "\n\n请用中文写 3~4 条结论：哪里明显偏离、可能的原因、以及一条下一场就能执行的动作。"
            "不要重复数字，不要客套。每条不超过 40 字。"
        )
        try:
            text = self.coach.chat(
                [{"role": "system", "content": "你是我的扑克教练，擅长从频率数据里找漏洞。说话直接，只讲能落地的。"},
                 {"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=600,
            )
            out = {"text": text}
        except Exception as e:
            out = {"error": str(e)}
        _COACH_CACHE[key] = (now, out)
        return out

    def _tree_rules(self, qs) -> dict:
        """规则审核：直接读策略树，不再用笔记抽的旧规则。"""
        import csv as _csv
        from pathlib import Path as _P

        tdir = data_path("tree")
        path = tdir / "rules.csv"
        if not path.exists():
            return {"rules": [], "counts": {"total": 0}}
        rows = list(_csv.DictReader(open(path, encoding="utf-8")))
        pot = qs.get("pot", "")
        st = qs.get("street", "")
        role = qs.get("role", "")
        src = qs.get("source", "")
        q = (qs.get("q") or "").strip()
        out = []
        for r in rows:
            if pot and r["pot_type"] != pot:
                continue
            if st and r["street"] != st:
                continue
            if role and r["role"] != role:
                continue
            if src and r["source"] != src:
                continue
            if q and q not in (r.get("note") or "") and q not in r["rule_id"]:
                continue
            out.append({
                "id": r["rule_id"], "pot": r["pot_type"], "role": r["role"],
                "board": r["board_class"], "street": r["street"],
                "action": r["node_action"], "sizing": r["sizing"], "freq": r["freq"],
                "table": r["bucket_table"], "source": r["source"], "conf": r["conf"],
                "status": r["status"], "note": r.get("note") or "",
                "path": r.get("path") or "", "capped": r.get("capped") or "*",
                "vs_type": r.get("vs_type") or "*", "runout": r.get("runout") or "*",
            })
        order = {"active": 0, "hold": 1, "retired": 2}
        out.sort(key=lambda x: (order.get(x["status"], 3), x["pot"], x["street"]))
        counts = {
            "total": len(out),
            "active": sum(1 for x in out if x["status"] == "active"),
            "hold": sum(1 for x in out if x["status"] == "hold"),
            "retired": sum(1 for x in out if x["status"] == "retired"),
            "derived": sum(1 for x in out if x["source"] == "推导"),
        }
        return {"rules": out, "counts": counts}

    def _library(self) -> dict:
        from .knowledge import ZONES, build_index, summary
        from .quiz import LEVELS

        index = build_index(lambda k, n: self.coach.search(k, k=n), 2)
        nconcept = 0
        for block in index:
            for c in block["concepts"]:
                lv = c.get("level") or 1
                c["topic"] = LEVELS[lv - 1] if 1 <= lv <= len(LEVELS) else "其他"
                nconcept += 1
        docs = self.store.stats().get("docs", 0)
        leak = None
        try:
            lk = self._leaks()
            for x in lk.get("leaks", []):
                if x.get("id") == "fold_to_cbet":
                    leak = x.get("value")
        except Exception:
            pass
        return {"zones": ZONES,
                "summary": summary(docs=docs, concepts=nconcept, zones=len(index), leak=leak),
                "outline": index}

    def _suggest_range(self, type_id: str) -> dict:
        """从课程笔记里给某个玩家类型找范围。"""
        import re as _re

        from .playertypes import combo_pct, get as get_ptype
        from .ranges import parse_range

        if not type_id:
            return {"error": "缺少类型"}
        t = get_ptype(type_id, self.store)
        hits = self.coach.search(
            f"{type_id} {' '.join(t.get('alias', []))} 范围 开池 跟注 防守 剥削", k=4
        )
        if not hits:
            return {"error": "笔记里没找到相关内容"}
        ctx = "\n\n".join(
            f"[{i+1}] 《{h['title']}》{h['heading'] or ''}\n{h['text'][:600]}" for i, h in enumerate(hits)
        )
        prompt = (
            f"这是课程笔记里和「{type_id}」这个玩家类型相关的段落：\n\n{ctx}\n\n"
            f"这个类型目前的参考范围是：{t['range']}（约占 {round(sum(w for _,_,w in parse_range(t['range']))/1326*100,1)}% 的组合）。\n"
            f"请判断：笔记里有没有给出更准确的【{type_id}】跟注/防守范围？\n"
            "有 —— 就按笔记给出新范围；没有 —— 原样返回当前范围，并把 confidence 标 low。\n"
            "范围语法：22+, A2s+, K9s+, QTs+, JTs, 98s, ATo+, KQo（纯 ASCII，不要中文）。\n"
            "只输出 JSON：{\"range\":\"…\",\"basis\":\"依据笔记的哪句话（20字内，没有就写「笔记未给具体范围」）\","
            "\"confidence\":\"high|low\"}"
        )
        try:
            raw = self.coach.chat(
                [{"role": "system", "content": "你是扑克教练，只输出 JSON。"},
                 {"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=500,
            )
            m = _re.search(r"\{.*\}", raw, _re.S)
            data = __import__("json").loads(m.group(0)) if m else {}
        except Exception as e:
            return {"error": str(e)}

        rng = (data.get("range") or "").strip()
        try:
            parse_range(rng)
        except Exception as e:
            return {"error": f"模型给的范围无法解析：{e}", "raw": rng, "sources": hits}
        return {
            "range": rng,
            "basis": data.get("basis", ""),
            "confidence": data.get("confidence", "low"),
            "combo_pct": combo_pct(rng),
            "sources": [{"title": h["title"], "heading": h["heading"], "preview": h["preview"][:160]} for h in hits[:3]],
        }

    def _leaks(self) -> dict:
        """漏洞报告：算一次缓存 30 秒，避免每次请求都读 1.5 万手。"""
        now = time.time()
        if _LEAK_CACHE["data"] is not None and now - _LEAK_CACHE["at"] < 30:
            return _LEAK_CACHE["data"]
        from .hh.analysis import analyze
        flags = self.store.all_hh_flags()
        result = analyze(flags) if flags else {"agg": {"hands": 0}, "leaks": [], "priority_topics": []}
        data = {
            "hands": result["agg"].get("hands", 0),
            "winrate_bb100": result["agg"].get("winrate_bb100"),
            "totals": result["agg"].get("totals", {}),
            "samples": result["agg"].get("samples", {}),
            "rfi": result["agg"].get("rfi", {}),
            "leaks": result["leaks"],
            "priority_topics": result["priority_topics"],
        }
        # 每个指标都给出「我的值 / 标准区间 / 判定」
        try:
            from .hh.analysis import BENCHMARKS
            rows = []
            for key, b in BENCHMARKS.items():
                v = (data.get("totals") or {}).get(key)
                n = (data.get("samples") or {}).get(key)
                if v is None:
                    continue
                lo, hi = b["lo"], b["hi"]
                from .hh.analysis import band as _band
                verdict = _band(v, b)
                gap = 0 if verdict == "正常" else (v - hi if v > hi else v - lo)
                rows.append({"key": key, "label": b["label"], "value": v,
                             "lo": lo, "hi": hi,
                             "wlo": b.get("wlo", lo - 1), "whi": b.get("whi", hi + 1),
                             "verdict": verdict,
                             "gap": round(gap, 1), "samples": n or 0,
                             "enough": (n or 0) >= b["min_n"],
                             "min_n": b["min_n"], "topic": b.get("topic", "")})
            rows.sort(key=lambda x: -abs(x["gap"]))
            data["metrics"] = rows
            data["benchmarks"] = BENCHMARKS
        except Exception as e:
            data["metrics"] = []
        _LEAK_CACHE.update({"at": now, "data": data})
        return data

    def _status(self):
        stats = self.store.stats()
        return {
            "stats": stats,
            "indexed": len(self.coach.bm25.docs) if self.coach.bm25 else 0,
            "llm": bool(self.coach.api_key),
            "model": self.coach.model if self.coach.api_key else None,
        }


def _warm_caches(store: Store) -> None:
    """后台预热：策略树一致性要算 3,894 个决策点，约 19 秒。
    服务刚起来就先算好，用户打开复盘页时直接命中缓存。"""
    import time
    from pathlib import Path as _P

    time.sleep(2)
    try:
        from .treemismatch import analyze as _mm
        from .evaluate import evaluate as _ev

        tdir = data_path("tree")
        mm = _mm(store, tdir, 10)
        _ev(store, tdir, store_leaks(store), mm)
    except Exception:
        pass


def store_leaks(store: Store) -> dict:
    """给预热用：直接从 store 算一份 leaks（不经过 HTTP 层）。"""
    try:
        from .hh.analysis import analyze as _ha

        out = _ha(store.all_hh_flags())
        out["hands"] = len(store.all_hh_flags())
        return out
    except Exception:
        return {}


def serve(store: Store, coach: Coach, host: str = "127.0.0.1", port: int = 8770) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"store": store, "coach": coach})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    import threading

    threading.Thread(target=_warm_caches, args=(store,), daemon=True).start()
    return httpd
