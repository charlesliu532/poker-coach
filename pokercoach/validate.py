"""推导规则的实测校验。

三类检查：
  A 锚点 —— 用课程实测的聚合频率，比对我们桶表的平均值
  B 重复 —— 完整键下的同键规则（真冲突 or 已裁决）
  C 单调 —— 位置 / 池型的相对排序是否成立
"""
import csv, statistics, sys
from pathlib import Path as _P
from . import tree as _tree
from pathlib import Path
from collections import defaultdict

CLASSES = ["两对+","暗三条","超对","顶对好踢","顶对弱踢","中对","听牌","后门空气","纯空气","A大","其他"]
POTS  = ["SRP","3BP","3BP多人","4BP","多人池"]
ROLES = ["IP-PFR","OOP-PFR","IP-caller","OOP-caller"]

# 课程实测锚点：(名称, 底池, 角色, 街, 动作, 期望频率, line, 出处)
ANCHORS = [
 ("IP PFR 翻牌 Cbet",        "SRP","IP-PFR","翻牌","对手过牌",66,"*","GTO 66%（学生实测 81%）"),
 ("延迟 Cbet",               "SRP","IP-PFR","转牌","对手过牌",41,"翻牌过牌→延迟","GTO 41%（Hero 70%）"),
 ("多人池 OOP PFR 下注",      "多人池","OOP-PFR","翻牌","对手过牌",10,"*","Smash：过牌 90%"),
 ("3bet池 IP 翻牌下注",        "3BP","IP-PFR","翻牌","对手过牌",(60,100),"*","R43 蓝图 vs R142 range bet，取区间"),
]

def load(root):
    rules=[r for r in csv.DictReader(open(Path(root)/"rules.csv",encoding="utf-8")) if r["status"]!="retired"]
    b=defaultdict(dict)
    for x in csv.DictReader(open(Path(root)/"buckets.csv",encoding="utf-8")):
        b[x["table_id"]][x["hand_class"]]=int(x["bucket"])
    return rules,b

def mean(r,b):
    t=b.get(r["bucket_table"],{}); v=[x for k,x in t.items() if k in CLASSES]
    return statistics.mean(v) if v else None

def find(rules,pot,role,st,act,line,generic=True):
    """锚点都是「不限牌面」的，所以优先匹配 board_class='*' 的通用规则"""
    cands=[r for r in rules
           if (r["pot_type"],r["role"],r["street"],r["node_action"])==(pot,role,st,act)
           and (r.get("line") or "*")==line]
    if generic:
        cands=[r for r in cands if r["board_class"]=="*"
               and (r.get("vs_type") or "*")=="*" and (r.get("capped") or "*")=="*"]
    return cands[0] if cands else None

def run(root="data/tree"):
    rules,b=load(root)
    print(f"══ 规则 {len(rules)} 条 ══\n")

    # D 规则 ID 唯一性（曾因为 ID 撞车，把旧规则的角色改坏了）
    raw = list(csv.DictReader(open(Path(root) / "rules.csv", encoding="utf-8")))
    ids = [r["rule_id"] for r in raw]
    seen, dup_ids = set(), []
    for i in ids:
        if i in seen and i not in dup_ids:
            dup_ids.append(i)
        seen.add(i)
    print("D 规则 ID 唯一性")
    if dup_ids:
        print(f"  ❌ 重复 ID：{', '.join(dup_ids[:12])}（共 {len(dup_ids)} 个）—— 会导致角色/内容被互相覆盖")
    else:
        print(f"  ✅ {len(ids)} 行，ID 全部唯一")
    print()

    print("A 锚点校验（直接问引擎，取用户实际看到的那条）")
    print(f"  {'节点':<24}{'实测':>6}{'我们':>6}{'差':>6}  判定")
    bad=0
    for name,pot,role,st,act,exp,line,src in ANCHORS:
        try:
            out=_tree.grid(Path(root),pot,role,"A72r",st,act,
                           hero_pos="BTN",opp_pos="BB",
                           runout=("*" if st=="翻牌" else "空白"),
                           line=line)
        except Exception:
            out={"ok":False}
        if not out.get("ok"):
            print(f"  {name:<24}{exp:>6}{'—':>6}{'—':>6}  ⬜ 无规则"); continue
        r=out["rule"]
        # 只统计「在这条线范围里」的牌；范围外的空气不该稀释平均值
        _v=[c["bucket"] for c in out["cells"]
            if c["bucket"] is not None and not c.get("impossible")]
        m=statistics.mean(_v) if _v else 0
        lo,hi = exp if isinstance(exp,tuple) else (exp-12,exp+12)
        ok = "✅" if lo-1<=m<=hi+1 else ("⚠ 偏高" if m>hi else "⚠ 偏低")
        if not (lo-1<=m<=hi+1): bad+=1
        txt=f"{lo}–{hi}" if isinstance(exp,tuple) else f"{exp}"
        print(f"  {name:<24}{txt:>6}{m:>6.0f}{m-exp if not isinstance(exp,tuple) else 0:>+6.0f}  {ok} ({r['rule_id']})")
    print(f"  → {len(ANCHORS)} 个锚点，{bad} 个偏离\n")
    print("  ⚠ 防守类节点无法用此法验证：GTO 的防守率分母是「走到该街的范围」，")
    print("    而我们的表是全部 169 组合 → 会被大量空气稀释，只能比排序不能比绝对值。\n")

    KEY=lambda r:(r["pot_type"],r["role"],r["street"],r["node_action"],r["board_class"],
                  r.get("runout") or "*",r.get("vs_type") or "*",r.get("capped") or "*",
                  r.get("line") or "*",r.get("board_exact") or "",
                  r["hero_pos"],r["opp_pos"],r["stack"])
    g=defaultdict(list)
    for r in rules: g[KEY(r)].append(r)
    dup=[(k,v) for k,v in g.items() if len(v)>1]
    unresolved=[(k,v) for k,v in dup if all(x["status"]=="hold" for x in v)]
    print(f"B 同键规则：{len(dup)} 组，其中 {len(unresolved)} 组是「双方并存未裁决」")
    for k,v in unresolved:
        print(f"  ⚠ {k[0]}·{k[1]}·{k[2]}·{k[3]} → {'/'.join(x['rule_id'] for x in v)}")
    print()

    print("C 单调性（只比通用规则）")
    gen=[r for r in rules if (r.get("line") or "*")=="*" and not (r.get("path") or "").strip()
         and r["board_class"]=="*" and not r["board_exact"] and r["node_action"]=="对手过牌"]
    issues=0
    for st in ["翻牌","转牌","河牌"]:
        for pot in POTS:
            m={}
            for role in ROLES:
                vals=[mean(x,b) for x in gen if (x["pot_type"],x["role"],x["street"])==(pot,role)]
                vals=[v for v in vals if v is not None]
                if vals: m[role]=statistics.mean(vals)
            if {"IP-PFR","OOP-caller"}<=m.keys() and m["IP-PFR"]<m["OOP-caller"]-3:
                print(f"  ⚠ 位置倒挂 {pot}·{st}: IP-PFR {m['IP-PFR']:.0f} < OOP-caller {m['OOP-caller']:.0f}"); issues+=1
    print(f"  → {issues} 处倒挂")
    return bad, len(unresolved), issues

if __name__=="__main__":
    run(sys.argv[1] if len(sys.argv)>1 else "data/tree")
