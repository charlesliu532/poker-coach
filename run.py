#!/usr/bin/env python3
"""扑克复盘台 —— 命令行入口。

    python run.py init            建目录、放模板
    python run.py ingest          把笔记/字幕/录屏入库
    python run.py serve           打开本地界面
    python run.py demo            用示例资料体验一遍
    python run.py import notion --token ...     从 Notion 导入
    python run.py import notion-zip 导出.zip    从 Notion 导出包导入
    python run.py import evernote 笔记.enex     从印象笔记导出文件导入
    python run.py import notion-local           直接读本机 Notion 缓存（推荐）
    python run.py import evernote-local         直接读本机印象笔记数据（推荐）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from pokercoach import odds as odds_mod
from pokercoach.importers import evernote as enex_mod
from pokercoach.importers import evernote_local
from pokercoach.importers import notion as notion_mod
from pokercoach.importers import notion_local
from pokercoach.coach import Coach
from pokercoach.equity import equity as eq_fn
from pokercoach.ingest import ingest, rebuild_cards
from pokercoach.hh import gg as hh_gg
from pokercoach.hh.analysis import analyze as hh_analyze
from pokercoach.hh.analysis import hero_flags, render_report
from pokercoach.hh import spotdb
from pokercoach import curate
from pokercoach.path import build_path, render_path
from pokercoach.transcribe_batch import plan_batch, render_plan, run_batch
from pokercoach.server import serve
from pokercoach.store import Store

GUIDE = """# 笔记怎么写，检索才准

这个文件本身不会被索引（文件名在跳过列表里）。把真正的笔记放成单独的 .md 文件，建议一篇一个主题。

## 一个主题一篇

```
data/notes/翻前-3bet.md
data/notes/翻后-cbet.md
data/notes/河牌-抓诈唬.md
```

## 用小标题切分场景

检索是按标题+段落切片的，标题写清楚场景，命中率会高很多：

```markdown
## BTN vs CO 的 3bet 范围
...
```

## 用 Q:/A: 写卡片

会被自动抽成复习卡：

```
Q：BTN 被 BB 3bet 后，哪些牌最适合跟注？
A：有位置、能实现胜率的牌：同花连张、小口袋对、KQo/AJo。
```

## 用"原则："写一句话结论

```
原则：位置决定宽度，UTG 的宽度要让你被 3bet 后依然不难受。
```

这类句子会变成"某主题的核心原则是什么"的卡片。

## 录屏放哪里

- 有字幕文件（.srt/.vtt）：放到 `data/transcripts/`
- 只有录屏：放到 `data/recordings/`，运行 ingest 时会自动用 Whisper 转录（首次会下载模型）
"""


def paths(demo: bool = False):
    if demo:
        root = BASE / "samples"
        return root, BASE / "data" / "demo.sqlite"
    root = Path(os.environ.get("POKERCOACH_DATA", BASE / "data")).resolve()
    return root, root / "coach.sqlite"


def cmd_init(args):
    root, _ = paths(False)
    for sub in ("notes", "transcripts", "recordings"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    guide = root / "notes" / "如何整理笔记.md"
    if not guide.exists():
        guide.write_text(GUIDE, encoding="utf-8")
    print(f"目录已就绪：{root}")
    print(f"  notes/        笔记与课程资料（.md / .txt / .pdf）")
    print(f"  transcripts/  字幕（.srt / .vtt）")
    print(f"  recordings/   录屏（自动转录）")
    print(f"\n下一步：把资料放进去，然后 python run.py ingest")


def cmd_ingest(args):
    root, db = paths(args.demo)
    store = Store(db)
    print(f"扫描 {root} …")
    stats = ingest(root, store, transcribe_media=not args.no_transcribe, model_size=args.model)
    coach = Coach(store)
    print(
        f"完成：文档 {stats['docs']} · 切片 {stats['chunks']} · 卡片 {stats['cards']}"
        f" · 新转录 {stats['transcribed']} · 跳过 {stats['skipped']}"
    )
    if stats["failed"]:
        print("有问题的文件：")
        for f in stats["failed"][:10]:
            print("  -", f)
    print(f"索引已重建：{len(coach.bm25.docs)} 段可检索")


def _serve(args, demo: bool = False):
    root, db = paths(demo or args.demo)
    store = Store(db)
    if store.stats()["chunks"] == 0 and (root / "notes").exists():
        print("库里还没有内容，先扫描一次 …")
        print(ingest(root, store, transcribe_media=False))
    coach = Coach(store)
    port = args.port
    httpd = None
    for p in range(port, port + 12):
        try:
            httpd = serve(store, coach, host="127.0.0.1", port=p)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print("端口都被占用了，换一个 --port")
        return 1
    url = f"http://127.0.0.1:{port}"
    print(f"扑克复盘台已启动：{url}")
    print(f"  资料 {store.stats()['docs']} 篇 · 可检索 {len(coach.bm25.docs)} 段 · 待复习 {store.stats()['due']} 张")
    if not coach.api_key:
        print("  提示：未检测到 DEEPSEEK_API_KEY，问答会走「检索 + 计算 + 提问包」离线模式")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


def cmd_serve(args):
    return _serve(args, demo=False)


def cmd_demo(args):
    _, db = paths(True)
    store = Store(db)
    print(ingest(paths(True)[0], store, transcribe_media=False))
    Coach(store).rebuild()
    return _serve(args, demo=True)


def cmd_search(args):
    _, db = paths(args.demo)
    coach = Coach(Store(db))
    hits = coach.search(" ".join(args.query), k=args.k)
    if not hits:
        print("没有命中。先运行 python run.py ingest")
        return
    for i, h in enumerate(hits, 1):
        where = h["title"] + (f" / {h['heading']}" if h["heading"] else "") + (f" @{h['time']}" if h["time"] else "")
        print(f"[{i}] {h['score']:.2f}  {where}")
        print("   ", h["preview"])


def cmd_equity(args):
    print(eq_fn(args.hero, args.villain, args.board or ()))


def cmd_odds(args):
    print(odds_mod.describe(args.pot, args.bet, args.equity / 100 if args.equity else None))


def cmd_import(args):
    root, db = paths(False)
    notes_root = root / "notes"
    if args.kind == "notion":
        token = args.token or os.environ.get("NOTION_TOKEN", "")
        if not token:
            print("需要 Notion token：--token 或环境变量 NOTION_TOKEN")
            return 2
        stats = notion_mod.import_notion(token, notes_root / "notion", query=args.query, force=args.force)
    elif args.kind == "notion-zip":
        stats = notion_mod.import_notion_zip(args.path, notes_root / "notion")
    elif args.kind == "evernote":
        stats = enex_mod.import_enex(args.path, notes_root / "evernote")
    elif args.kind == "notion-local":
        stats = notion_local.import_notion_local(notes_root / "notion", db_path=args.path or None, force=args.force)
    elif args.kind == "evernote-local":
        stats = evernote_local.import_evernote_local(
            notes_root / "evernote", store=args.path or None, force=args.force, only_poker=not args.all
        )
    else:
        print("未知的导入类型")
        return 2
    print(stats)
    if not args.no_ingest:
        store = Store(db)
        s = ingest(root, store, transcribe_media=False)
        coach = Coach(store)
        print(f"已入库：文档 {s['docs']} · 切片 {s['chunks']} · 卡片 {s['cards']} · 可检索 {len(coach.bm25.docs)} 段")
    return 0


def _player_types(hands) -> dict:
    """按 VPIP 给每个玩家打标签：紧 / 标准 / 松（样本少于 20 手不标）。"""
    stats: dict[str, dict] = {}
    for h in hands:
        pre = [a for a in h.actions if a.street == "preflop" and a.kind != "post"]
        first: dict[str, str] = {}
        for a in pre:
            if a.player in first:
                continue
            if a.kind in ("folds", "calls", "raises", "bets"):
                first[a.player] = a.kind
        for name in h.seats:
            st = stats.setdefault(name, {"n": 0, "vpip": 0})
            st["n"] += 1
            if first.get(name) in ("calls", "raises"):
                st["vpip"] += 1
    out = {}
    for name, st in stats.items():
        if st["n"] < 20:
            continue
        v = st["vpip"] / st["n"] * 100
        out[name] = "紧" if v < 20 else ("松" if v > 32 else "标准")
    return out


def cmd_hh(args):
    root, db = paths(args.demo)
    store = Store(db)
    if args.clear:
        store.clear_hh()
        print("已清空手牌库")
    src = Path(args.path) if args.path else root / "hh" / "raw"
    if not src.exists():
        print(f"找不到 {src}，把 GG 的 .txt 手牌放进去")
        return 1
    hands, info = hh_gg.parse_paths([src])
    print(f"解析 {info['files']} 个文件：{info['hands']:,} 手，失败 {info['unparsed']}")
    if not hands:
        return 1
    rows = []
    for h in hands:
        flags = hero_flags(h)
        rows.append(
            {
                "hand_id": h.hand_id,
                "played_at": h.played_at,
                "stakes": f"{h.sb:g}/{h.bb:g}",
                "hero": h.hero,
                "board": " ".join(h.board),
                "pot": h.pot,
                "net": h.hero_net(),
                "bb": h.bb,
                "flags": flags,
                "data": h.to_dict(),
            }
        )
    store.add_hh(rows)
    store.clear_spots()
    ptypes = _player_types(hands)
    spot_rows = [sp for hnd in hands for sp in spotdb.extract_spots(hnd, ptypes)]
    store.add_spots(spot_rows)
    print(f"决策点 {len(spot_rows):,} 个（翻牌/转牌/河牌）")
    result = hh_analyze(store.all_hh_flags())
    print()
    print(render_report(result))
    out = root / "leaks.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已保存：{out}")
    if result["priority_topics"]:
        print("建议优先补的主题：" + " · ".join(result["priority_topics"]))
        print("（运行 python run.py path 会自动把这些主题排到前面）")
    return 0


def cmd_path(args):
    root, db = paths(args.demo)
    store = Store(db)
    priority = []
    leak_file = root / "leaks.json"
    if leak_file.exists() and not args.no_leaks:
        try:
            priority = json.loads(leak_file.read_text(encoding="utf-8")).get("priority_topics", [])
        except Exception:
            priority = []
    plan = build_path(store, weeks=args.weeks, days_per_week=args.days, minutes=args.minutes, priority=priority)
    priority = list(dict.fromkeys(priority))
    if priority:
        print(f"已按手牌漏洞加权：{' · '.join(priority)}")
    print(render_path(plan))
    if plan["weeks"]:
        out = root / "plan.json"
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已保存：{out}")
    return 0


def cmd_transcribe(args):
    root, db = paths(args.demo)
    plan = plan_batch(root, topic=args.topic, limit=args.limit)
    print(render_plan(plan))
    if args.dry_run or not plan["ready"]:
        if not args.dry_run and not plan["ready"]:
            print("\n没有可转录的本地文件。把视频放进 data/recordings/ 再跑一次；Notion 里的视频需要先下载。")
        return 0
    stats = run_batch(root, plan["ready"], model=args.model)
    print(f"\n转录完成 {stats['transcribed']}，失败 {stats['failed']}")
    if stats["transcribed"]:
        store = Store(db)
        s = ingest(root, store, transcribe_media=False)
        print(f"已入库：切片 {s['chunks']}，文档 {s['docs']}")
    return 0


def cmd_cards(args):
    root, db = paths(args.demo)
    store = Store(db)
    if args.rebuild:
        rebuild_cards(store, limit=args.limit)
    s = store.stats()
    kinds = s.get("card_kinds", {})
    print(f"卡片 {s['cards']} 张（" + " · ".join(f"{k or '未分类'} {v}" for k, v in kinds.items()) + f"），待复习 {s['due']}")
    if args.sample:
        rows = store.conn.execute(
            "SELECT front, back, tags, kind FROM cards ORDER BY RANDOM() LIMIT ?", (args.sample,)
        ).fetchall()
        for r in rows:
            print(f"\n[{r['kind']}] {r['tags'][:40]}")
            print(f"  Q: {r['front']}")
            print(f"  A: {r['back']}")
    return 0


def cmd_config(args):
    root, db = paths(args.demo)
    store = Store(db)
    coach = Coach(store)
    if args.key is not None or args.model or args.base_url:
        coach.configure(api_key=args.key or None, model=args.model or None, base_url=args.base_url or None)
    info = coach.config_info()
    print(f"模型：{info['model']}　接口：{info['base_url']}")
    print(f"状态：{'已配置 ' + info['key_tail'] if info['configured'] else '未配置（离线检索模式）'}")
    print("\n配置示例：python run.py config --key sk-xxxx --model deepseek-chat")
    return 0


def cmd_curate(args):
    root, db = paths(args.demo)
    store = Store(db)
    coach = Coach(store)
    if not coach.api_key:
        print("需要先配置模型：python run.py config --key sk-xxx")
        return 2
    stats = curate.score_cards(store, coach, batch=args.batch, limit=args.limit or None)
    print(stats)
    rep = curate.report(store)
    print(f"分数分布：{rep['distribution']}")
    print(f"合格（≥6 分）：{rep['good']} 张")
    return 0


def cmd_gen(args):
    root, db = paths(args.demo)
    store = Store(db)
    coach = Coach(store)
    if not coach.api_key:
        print("需要先配置模型：python run.py config --key sk-xxx")
        return 2
    filt = [x for x in (args.topics or "").split(",") if x] or None
    stats = curate.generate(store, coach, chunks=args.chunks, topics_filter=filt)
    print(stats)
    return 0


def cmd_learn(args):
    root, db = paths(args.demo)
    store = Store(db)
    coach = Coach(store)
    if not coach.api_key:
        print("需要先配置模型")
        return 2
    stats = curate.extract_rules(store, coach, chunks=args.chunks, doc_filter=args.doc or "")
    print(stats)
    print("规则总数：", store.note_rule_count())
    return 0


def cmd_stats(args):
    _, db = paths(args.demo)
    store = Store(db)
    s = store.stats()
    print(f"文档 {s['docs']} · 切片 {s['chunks']} · 卡片 {s['cards']} · 待复习 {s['due']} · 手牌 {s['hands']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="poker-coach", description="本地扑克复盘 / 学习助手")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="建目录并放入笔记模板").set_defaults(func=cmd_init)

    pi = sub.add_parser("ingest", help="扫描资料并重建索引")
    pi.add_argument("--demo", action="store_true", help="用示例资料")
    pi.add_argument("--no-transcribe", action="store_true", help="跳过录屏转录")
    pi.add_argument("--model", default=os.environ.get("POKERCOACH_WHISPER_MODEL", "small"), help="Whisper 模型：tiny/base/small/medium")
    pi.set_defaults(func=cmd_ingest)

    ps = sub.add_parser("serve", help="启动本地界面")
    ps.add_argument("--port", type=int, default=8770)
    ps.add_argument("--demo", action="store_true")
    ps.add_argument("--no-browser", action="store_true")
    ps.set_defaults(func=cmd_serve)

    pd = sub.add_parser("demo", help="用示例资料体验")
    pd.add_argument("--port", type=int, default=8771)
    pd.add_argument("--no-browser", action="store_true")
    pd.set_defaults(func=cmd_demo, demo=True)

    pq = sub.add_parser("search", help="命令行检索")
    pq.add_argument("query", nargs="+")
    pq.add_argument("--k", type=int, default=5)
    pq.add_argument("--demo", action="store_true")
    pq.set_defaults(func=cmd_search)

    pe = sub.add_parser("equity", help="算胜率")
    pe.add_argument("hero")
    pe.add_argument("villain")
    pe.add_argument("board", nargs="?", default="")
    pe.set_defaults(func=cmd_equity)

    po = sub.add_parser("odds", help="算底池赔率与 EV")
    po.add_argument("pot", type=float)
    po.add_argument("bet", type=float)
    po.add_argument("--equity", type=float, default=None, help="胜率百分比")
    po.set_defaults(func=cmd_odds)

    pim = sub.add_parser("import", help="从 Notion / 印象笔记导入")
    pim.add_argument("kind", choices=["notion", "notion-zip", "notion-local", "evernote", "evernote-local"])
    pim.add_argument("path", nargs="?", default="", help="文件路径（zip / enex）")
    pim.add_argument("--token", default="", help="Notion integration token")
    pim.add_argument("--query", default="", help="只导入标题含关键词的页面")
    pim.add_argument("--force", action="store_true", help="覆盖已导出的页面")
    pim.add_argument("--no-ingest", action="store_true", help="只导出文件，不入库")
    pim.add_argument("--all", action="store_true", help="印象笔记：连非扑克笔记一起导入")
    pim.set_defaults(func=cmd_import)

    ph = sub.add_parser("hh", help="导入 GG 手牌历史并出漏洞报告")
    ph.add_argument("path", nargs="?", default="", help="手牌 txt 文件或目录")
    ph.add_argument("--clear", action="store_true", help="先清空已有手牌")
    ph.add_argument("--demo", action="store_true")
    ph.set_defaults(func=cmd_hh)

    pp = sub.add_parser("path", help="从资料生成 N 周学习路径")
    pp.add_argument("--weeks", type=int, default=4)
    pp.add_argument("--days", type=int, default=5, help="每周学习几天")
    pp.add_argument("--minutes", type=int, default=25, help="每天多少分钟")
    pp.add_argument("--demo", action="store_true")
    pp.add_argument("--no-leaks", action="store_true", help="忽略手牌漏洞，按默认顺序排")
    pp.set_defaults(func=cmd_path)

    ptt = sub.add_parser("transcribe", help="按主题批量转录")
    ptt.add_argument("--topic", default="", help="主题，如 河牌 / 多人底池；不填为全部")
    ptt.add_argument("--limit", type=int, default=0)
    ptt.add_argument("--model", default=os.environ.get("POKERCOACH_WHISPER_MODEL", "small"))
    ptt.add_argument("--dry-run", action="store_true", help="只看计划，不转录")
    ptt.add_argument("--demo", action="store_true")
    ptt.set_defaults(func=cmd_transcribe)

    pc = sub.add_parser("cards", help="看/重建复习卡片")
    pc.add_argument("--rebuild", action="store_true", help="从已有切片重新生成")
    pc.add_argument("--limit", type=int, default=8, help="每篇文档最多几张卡")
    pc.add_argument("--sample", type=int, default=0, help="随机抽几张看看")
    pc.add_argument("--demo", action="store_true")
    pc.set_defaults(func=cmd_cards)

    pcg = sub.add_parser("config", help="配置模型（API Key）")
    pcg.add_argument("--key", default=None, help="API Key，传空字符串表示清除")
    pcg.add_argument("--model", default="", help="模型名，如 deepseek-chat")
    pcg.add_argument("--base-url", default="", help="OpenAI 兼容接口地址")
    pcg.add_argument("--demo", action="store_true")
    pcg.set_defaults(func=cmd_config)

    pcu = sub.add_parser("curate", help="用模型给题库打分（筛掉烂题）")
    pcu.add_argument("--batch", type=int, default=6, help="每批几题")
    pcu.add_argument("--limit", type=int, default=0, help="只审前 N 张（调试用）")
    pcu.add_argument("--demo", action="store_true")
    pcu.set_defaults(func=cmd_curate)

    pgn = sub.add_parser("gen", help="让模型读笔记出新题")
    pgn.add_argument("--chunks", type=int, default=40, help="读多少个笔记片段")
    pgn.add_argument("--topics", default="", help="只在这些主题里出题，逗号分隔")
    pgn.add_argument("--demo", action="store_true")
    pgn.set_defaults(func=cmd_gen)

    pl = sub.add_parser("learn", help="从课程笔记里抽结构化建议规则")
    pl.add_argument("--chunks", type=int, default=40)
    pl.add_argument("--doc", default="", help="只从标题包含这段文字的文档里抽")
    pl.add_argument("--demo", action="store_true")
    pl.set_defaults(func=cmd_learn)

    pt = sub.add_parser("stats", help="看库存")
    pt.add_argument("--demo", action="store_true")
    pt.set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    try:
        return args.func(args) or 0
    except (ValueError, FileNotFoundError) as e:
        print(f"出错了：{e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
