import sys, itertools
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pokercoach import tree as T
td=Path(__file__).resolve().parent.parent/'data'/'tree'
POTS=["SRP","3BP","4BP","3人池","3BP多人","多人池"]
ROLES=["IP-PFR","OOP-PFR","IP-caller","OOP-caller"]
ACTS=["对手过牌","对手小注","对手中注","对手大注"]
BOARDS=["As7h2c","AhKh2h","Kc8d4s","9s8s7d","2c3d4h","QdJdTd"]
issues=[]
def add(c,m): issues.append((c,m))

for pot,role,ac,bd in itertools.product(POTS,ROLES,ACTS,BOARDS):
    r=T.grid(td,pot,role,bd,"翻牌",ac,hero_pos="BTN",opp_pos="BB")
    if not r.get("ok"): continue
    labels=[a["label"] for a in r.get("node_actions") or []]
    vl=[a["label"] for a in r.get("villain_actions") or []]
    # 数值
    for c in r.get("cells") or []:
        b=c.get("bucket")
        if b is not None and not (0<=b<=100): add("A 数值越界", f"{pot}/{role}/{bd} {c['combo']}={b}")
    for f in (r.get("opponent_freq") or []):
        if f["raise"]+f["call"]+f["fold"]!=100: add("F 频率和≠100", f"{pot}/{bd} {f['combo']}")
    # 语义
    if role.endswith("PFR") and any("领打" in x for x in labels): add("C PFR有领打", f"{role}/{ac}")
    if ac=="对手过牌" and any("过牌加注" in x for x in vl): add("D 过牌后有XR", f"{role}/{ac}")
    if ac in ("对手小注","对手中注","对手大注") and any(x.startswith("下注") for x in labels):
        add("C 面对下注还能下注", f"{role}/{ac}")
    # 对手范围外的牌不该有频率
    vr={x["combo"]:x for x in (r.get("villain_range") or [])}
    for f in (r.get("opponent_freq") or []):
        if f["raise"]>0 and vr and vr.get(f["combo"],{}).get("kind")=="fold":
            add("E 范围外有加注频率", f"{pot}/{bd} {f['combo']} raise={f['raise']}")

# 翻前术语
for act in ["开池"]:
    r=T.grid(td,"翻前","*","As7h2c","翻前",act,hero_pos="BTN",stack="100bb")
    labels=[a["label"] for a in r.get("node_actions") or []]
    if any(x.startswith("下注") for x in labels): add("H 翻前用下注术语", str(labels))

# 范围过滤
r=T.grid(td,"SRP","IP-PFR","As7h2c","翻牌","对手过牌",hero_pos="BTN",opp_pos="BB")
imp={c["combo"] for c in r["cells"] if c.get("impossible")}
if "72o" not in imp: add("I 72o 未被排除", "BTN SRP")

# 3BP 对手范围
r=T.grid(td,"3BP","IP-caller","As7h2c","翻牌","对手过牌",hero_pos="BB",opp_pos="BTN")
kinds=[x["kind"] for x in (r.get("villain_range") or [])]
if "call" in kinds: add("J 3BP对手范围混入跟注牌", str(set(kinds)))

print(f"审计完成，{len(issues)} 个问题")
from collections import Counter
for c,n in Counter(x[0] for x in issues).most_common(): print(f"  {c}: {n}")
for c,m in issues[:12]: print(f"  [{c}] {m}")
