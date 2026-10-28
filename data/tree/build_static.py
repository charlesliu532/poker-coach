#!/usr/bin/env python3
"""生成纯静态 HTML：不含任何 JavaScript，打开就能看，按 Cmd+F 搜索。"""
import csv, html
from pathlib import Path

ROOT = Path(__file__).parent
rules = list(csv.DictReader(open(ROOT / "rules.csv", encoding="utf-8")))
buckets = list(csv.DictReader(open(ROOT / "buckets.csv", encoding="utf-8")))

tables = {}
for b in buckets:
    t = tables.setdefault(b["table_id"], {"unit": b["unit"], "basis": b["basis"], "rows": []})
    t["rows"].append((b["hand_class"], b["bucket"]))

e = html.escape
out = ["""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>扑克策略树 · 静态版</title>
<style>
body{margin:0;background:#faf9f7;color:#1e1e1e;font:15px/1.7 -apple-system,"PingFang SC",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:24px;margin:0 0 6px}
h2{font-size:18px;margin:34px 0 10px;padding-bottom:6px;border-bottom:2px solid #8b1e3f}
.hint{background:#fff;border:1px solid #e6e2dc;border-radius:10px;padding:12px 16px;font-size:13px;color:#555;margin-bottom:10px}
table{width:100%;border-collapse:collapse;font-size:13px;background:#fff}
th,td{padding:6px 8px;border-bottom:1px solid #eee;text-align:left}
th{background:#f3efea;font-weight:600;font-size:12px;position:sticky;top:0}
tr:hover td{background:#fcfbf9}
.warn{color:#b45309;font-weight:600}
.tbl{margin-bottom:18px}
.tid{font-weight:600}
.unit{color:#6b6b6b}
</style>
<div class="wrap">
<h1>扑克策略树 · 静态版</h1>
<div class="hint">
  这个页面<b>不用任何脚本</b>，打开就能看。<br>
  想查某个局面 → 按 <b>⌘F</b> 搜牌面代号（如 <code>高A-低-彩</code>），或搜规则号（如 <code>R02</code>）。<br>
  <span class="warn">⚠</span> = 该桶表是反推的（不是课程原文）。
</div>
"""]
out.append(f"<p style='color:#6b6b6b;font-size:13px'>{len(rules)} 条规则 · {len(tables)} 张桶表 · {len(buckets)} 行</p>")

out.append("<h2>一、全部规则</h2><table><tr><th>ID</th><th>底池</th><th>角色</th><th>牌面</th><th>街</th><th>对手动作</th><th>尺度</th><th>频率</th><th>桶表</th><th>来源</th><th>置信</th></tr>")
for r in rules:
    t = r["bucket_table"]
    mark = ' <span class="warn">⚠</span>' if t in tables and tables[t]["basis"].startswith("反推") else ""
    out.append("<tr>" + "".join(f"<td>{e(r[k])}</td>" for k in
               ["rule_id","pot_type","role","board_class","street","node_action","sizing","freq","source","conf"][:8])
               + f"<td>{e(t)}{mark}</td><td>{e(r['source'])}</td><td>{e(r['conf'])}</td></tr>")
out.append("</table>")

out.append("<h2>二、桶表</h2>")
for tid, v in tables.items():
    warn = ' <span class="warn">⚠ 反推</span>' if v["basis"].startswith("反推") else ""
    out.append(f'<div class="tbl"><div class="tid">{tid}{warn}</div>'
               f'<div class="unit">单位：{e(v["unit"])} ｜ 来源：{e(v["basis"])}</div>'
               '<table><tr><th>手牌类别</th><th>数值</th></tr>')
    for h, n in v["rows"]:
        out.append(f"<tr><td>{e(h)}</td><td>{e(str(n))}%</td></tr>")
    out.append("</table></div>")

out.append("</div></html>")
(ROOT / "策略树-静态.html").write_text("\n".join(out), encoding="utf-8")
print("已生成 策略树-静态.html", len("\n".join(out)), "字符")
