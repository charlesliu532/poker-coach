#!/usr/bin/env python3
"""把 rules.csv + buckets.csv 渲染成一个自包含的 HTML（双击即可用，无需联网）。"""
import csv, json, re
from pathlib import Path

ROOT = Path(__file__).parent
rules = list(csv.DictReader(open(ROOT / "rules.csv", encoding="utf-8")))
buckets = list(csv.DictReader(open(ROOT / "buckets.csv", encoding="utf-8")))

WILD = {"*", "", "-"}
def vals(k):
    out = []
    for r in rules:
        v = (r.get(k) or "*").strip()
        if v not in WILD and v not in out:
            out.append(v)
    return out

FIELDS = ["pot_type", "role", "board_class", "street", "node_action", "opp_pos", "stack"]
LABEL = {"pot_type":"底池","role":"角色","board_class":"牌面","street":"街道",
         "node_action":"对手动作","opp_pos":"对手位置","stack":"筹码深度"}
HANDS = sorted({b["hand_class"] for b in buckets})

tables = {}
for b in buckets:
    tables.setdefault(b["table_id"], {"name": b["table_id"], "unit": b.get("unit","下注率"),
                                      "basis": b.get("basis",""), "rows": []})
    tables[b["table_id"]]["rows"].append([b["hand_class"], b["bucket"]])

html = """<!doctype html><html lang="zh"><meta charset="utf-8">
<title>扑克策略树 v0.1</title>
<style>
:root{--bg:#faf9f7;--card:#fff;--ink:#1e1e1e;--mut:#6b6b6b;--line:#e6e2dc;--accent:#8b1e3f;--warn:#b45309}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"PingFang SC","Helvetica Neue",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:24px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
label{display:block;font-size:12px;color:var(--mut);margin-bottom:4px}
select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:#fff;font-size:14px;color:var(--ink)}
button{margin-top:14px;padding:9px 22px;border:0;border-radius:8px;background:var(--accent);color:#fff;font-size:14px;cursor:pointer}
button:hover{opacity:.9}
.res{margin-top:16px}
.rule{border-left:3px solid var(--accent);background:#fff;padding:12px 14px;border-radius:0 8px 8px 0;margin-bottom:10px;box-shadow:0 1px 2px #0000000a}
.rule .id{font-weight:600}
.tag{display:inline-block;font-size:12px;padding:1px 7px;border-radius:99px;background:#f1ede8;color:var(--mut);margin-left:6px}
.tag.warn{background:#fdf0e0;color:var(--warn)}
.big{font-size:20px;margin:6px 0}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:500;font-size:12px}
tr:hover td{background:#fcfbf9}
details summary{cursor:pointer;color:var(--mut);font-size:13px;user-select:none}
.legend{font-size:12px;color:var(--mut);margin-top:10px}
</style>
<div class="wrap">
<h1>扑克策略树 <span class="tag">v0.1</span></h1>
<div class="sub">%STATS%</div>
<div class="card" id="boot" style="border-color:#f0c48a;background:#fff8ee">
  <b>正在加载…</b><br>
  <span style="font-size:13px;color:#8a5a12">如果这段文字一直停在这里，说明页面脚本出错了——把这张截图发我即可，不用你排查。</span>
</div>

<div class="card">
  <div class="grid" id="q"></div>
  <button onclick="run()">查</button>
  <div class="res" id="res"><div class="legend">选好条件点「查」。留「任意」表示通配。</div></div>
</div>

<div class="card">
  <details>
    <summary>查看全部 %NRULES% 条规则</summary>
    <div style="margin-top:12px;overflow-x:auto">
      <table id="all"><thead><tr>
        <th>ID</th><th>底池</th><th>角色</th><th>牌面</th><th>街</th><th>对手动作</th>
        <th>尺度</th><th>频率</th><th>桶表</th><th>来源</th><th>置信</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </details>
  <div class="legend">⚠ 标记 = 该桶表是反推出来的（数值由课程频率或弃牌率加总反推，不是课程原表）。</div>
</div>
</div>

<script>
window.onerror = function(msg, src, line){
  var b = document.getElementById('boot');
  if (b) b.innerHTML = '<b>页面出错了</b><br><span style="font-size:13px">' + msg + '（第 ' + line + ' 行）</span>';
  return false;
};
const RULES = %RULES%;
const HAND = %HANDS%;
const TABLES = %TABLES%;
const FIELDS = %FIELDS%;
const LABEL = %LABEL%;
const WILD = new Set(["*","","-"]);
const OPT = %OPTIONS%;

const q = document.getElementById('q');
FIELDS.forEach(f=>{
  const d=document.createElement('div');
  const opts=['*'].concat(OPT[f]||[]);
  d.innerHTML=`<label>${LABEL[f]}</label><select id="${f}">`+
    opts.map(o=>`<option value="${o}">${o==='*'?'任意':o}</option>`).join('')+`</select>`;
  q.appendChild(d);
});
const dh=document.createElement('div');
dh.innerHTML=`<label>手牌类别</label><select id="hand">`+
  HAND.map(h=>`<option>${h}</option>`).join('')+`</select>`;
q.appendChild(dh);
// 默认值
setv('pot_type','SRP'); setv('role','IP-PFR'); setv('board_class','高A-低-彩');
setv('street','翻牌'); setv('node_action','对手过牌'); setv('hand','顶对好踢');
function setv(id,v){const e=document.getElementById(id); if(e&&[...e.options].some(o=>o.value===v)) e.value=v;}

function score(r,sel){
  let s=0;
  for(const f of FIELDS){
    const rv=(r[f]||'*').trim(), qv=(sel[f]||'*').trim();
    if(WILD.has(rv)) continue;
    if(rv!==qv) return -1;
    s++;
  }
  return s;
}
function run(){
  const sel={}; FIELDS.forEach(f=>sel[f]=document.getElementById(f).value);
  const hand=document.getElementById('hand').value;
  const hits=[];
  for(const r of RULES){const s=score(r,sel); if(s>=0) hits.push([s,r]);}
  const res=document.getElementById('res');
  if(!hits.length){res.innerHTML='<div class="rule">✗ 没有匹配规则。检查牌面拼写，或这条线还没录入。</div>';return;}
  const top=Math.max(...hits.map(h=>h[0]));
  const best=hits.filter(h=>h[0]===top).map(h=>h[1]);
  res.innerHTML = best.map(r=>{
    const t=TABLES[r.bucket_table]||{};
    let line='', unit=t.unit||'下注率', hit=(t.rows||[]).find(x=>x[0]===hand)||(t.rows||[]).find(x=>x[0]==='其他');
    if(!r.bucket_table||WILD.has(r.bucket_table)) line='桶表 —（本规则不定桶）';
    else if(!hit) line='（这张表里没有该手牌类别）';
    else line = unit==='下注率' ? `→ 桶 ${hit[1]}（约 ${hit[1]}% 下注）` : `→ ${hit[1]}% ${unit}`;
    const warn = (t.basis||'').startsWith('反推') ? `<span class="tag warn">⚠ ${t.basis}</span>` : '';
    return `<div class="rule">
      <span class="id">${r.rule_id}</span><span class="tag">${r.source} · 置信 ${r.conf}</span>${warn}
      <div class="big">${line}</div>
      <div>尺度 <b>${r.sizing}</b> ｜ 总频率 <b>${r.freq}</b> ｜ 桶表 <b>${r.bucket_table||'—'}</b></div>
      ${r.note?`<div class="legend">${r.note}</div>`:''}
    </div>`;
  }).join('') + (best.length>1?`<div class="legend">⚠ ${best.length} 条同分规则（冲突/并存），需要你裁决。</div>`:'');
}

// 全规则表
const tb=document.querySelector('#all tbody');
RULES.forEach(r=>{
  const tr=document.createElement('tr');
  tr.innerHTML=[r.rule_id,r.pot_type,r.role,r.board_class,r.street,r.node_action,
    r.sizing,r.freq,r.bucket_table,r.source,r.conf].map(v=>`<td>${v||''}</td>`).join('');
  tb.appendChild(tr);
});
run();
var boot = document.getElementById('boot');
if (boot) boot.remove();
</script>
</html>"""

opts = {f: vals(f) for f in FIELDS}
stats = f"{len(rules)} 条规则 · {len(tables)} 张桶表 · {sum(len(t['rows']) for t in tables.values())} 行 · 来源可溯"
out = (html
       .replace("%STATS%", stats)
       .replace("%NRULES%", str(len(rules)))
       .replace("%RULES%", json.dumps(rules, ensure_ascii=False))
       .replace("%HANDS%", json.dumps(HANDS, ensure_ascii=False))
       .replace("%TABLES%", json.dumps(tables, ensure_ascii=False))
       .replace("%FIELDS%", json.dumps(FIELDS, ensure_ascii=False))
       .replace("%LABEL%", json.dumps(LABEL, ensure_ascii=False))
       .replace("%OPTIONS%", json.dumps(opts, ensure_ascii=False)))
left = re.findall(r"%[A-Z_]{3,}%", out)
if left:
    raise SystemExit(f"模板占位符没替换完：{set(left)}")
(ROOT / "策略树.html").write_text(out, encoding="utf-8")

# 纯文本总览（浏览器打不开时的兜底）
L=["# 策略树 · 总览（纯文本版）","","> 网页版打不开时看这个。数据与 rules.csv / buckets.csv 同源。","",
   f"共 {len(rules)} 条规则，{len(tables)} 张桶表。","","## 规则","",
   "| ID | 底池 | 角色 | 牌面 | 街 | 对手动作 | 尺度 | 频率 | 桶表 | 来源 | 置信 |",
   "|---|---|---|---|---|---|---|---|---|---|---|"]
for r in rules:
    t=r["bucket_table"]; mark=" ⚠" if t in tables and tables[t]["basis"].startswith("反推") else ""
    L.append(f"| {r['rule_id']} | {r['pot_type']} | {r['role']} | {r['board_class']} | {r['street']} | {r['node_action']} | {r['sizing']} | {r['freq']} | {t}{mark} | {r['source']} | {r['conf']} |")
L+=["","## 桶表","","⚠ = 反推（不是原文）",""]
for t,v in tables.items():
    L.append(f"### {t} · {v['unit']} · {v['basis']}{' ⚠' if v['basis'].startswith('反推') else ''}")
    L.append("")
    L.append("｜".join(f"{h} {n}" for h,n in v["rows"]))
    L.append("")
(ROOT / "策略树-总览.md").write_text("\n".join(L), encoding="utf-8")
print(f"已生成 策略树.html ({len(out)} 字节) + 策略树-总览.md")
