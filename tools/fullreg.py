import sys, itertools, time, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pokercoach import tree as T
td = Path('data/tree')

POTS   = ["SRP","3BP","4BP","3人池","3BP多人","多人池"]
ROLES  = ["IP-PFR","OOP-PFR","IP-caller","OOP-caller"]
STREETS= ["翻牌","转牌","河牌"]
ACTS   = ["对手过牌","对手小注","对手中注","对手大注"]
DONKS  = ["我方领打","我方领打（小注）"]
BOARDS = ["As7h2c","AhKh2h","Kc8d4s","9s8s7d","AcAd2h","2c3d4h"]
TYPES  = ["*","标准","紧凶","松凶","岩石","受气包","跟注站","娱乐玩家","过度诈唬型","下注不足型"]
POS6   = ["UTG","HJ","CO","BTN","SB","BB"]
POS8   = ["UTG","UTG1","HJ","CO","BTN","SB","BB"]
STACKS = ["20bb","30bb","40bb","60bb","100bb","200bb","*"]

errs=[]; stats={"ok":0,"fail":0,"exc":0}
def check(label, **kw):
    try:
        r=T.grid(td, **kw)
        if not r.get("ok"):
            stats["fail"]+=1
            errs.append((label, r.get("reason","无原因")[:60]))
            return None
        stats["ok"]+=1
        # 结构校验
        problems=[]
        if len(r.get("cells") or [])!=169: problems.append(f"格数{len(r.get('cells') or [])}")
        if not r.get("node_actions"): problems.append("无动作")
        if not r.get("strategy_mode"): problems.append("无模式")
        if problems:
            errs.append((label,"结构:"+",".join(problems)))
        return r
    except Exception as e:
        stats["exc"]+=1
        errs.append((label,"异常:"+str(e)[:60]+" @"+traceback.format_exc().split("\n")[-2].strip()[:40]))
        return None

t0=time.time()
# 1) 全池型 × 角色 × 街 × 动作（固定牌面）
n=0
for pot,role,st,ac in itertools.product(POTS,ROLES,STREETS,ACTS):
    check(f"{pot}/{role}/{st}/{ac}", pot=pot,role=role,board_text="As7h2c",street=st,action=ac)
    n+=1
# 2) 领打
for pot,st,ac in itertools.product(POTS,STREETS,DONKS):
    check(f"领打/{pot}/{st}/{ac}", pot=pot,role="OOP-caller",board_text="As7h2c",street=st,action=ac)
# 3) 各牌面
for bd in BOARDS:
    for pot in POTS:
        check(f"牌面/{bd}/{pot}", pot=pot,role="IP-PFR",board_text=bd,street="翻牌",action="对手过牌")
# 4) 对手类型
for ty in TYPES:
    check(f"类型/{ty}", pot="SRP",role="IP-PFR",board_text="As7h2c",street="翻牌",action="对手过牌",vs_type=ty)
# 5) 位置（6人/8人）
for pos in POS6:
    check(f"6max/{pos}", pot="翻前",role="*",board_text="As7h2c",street="翻前",action="开池",hero_pos=pos,stack="100bb")
for pos in POS8:
    check(f"8max/{pos}", pot="翻前",role="*",board_text="As7h2c",street="翻前",action="开池",hero_pos=pos,stack="200bb")
for h in POS6:
    for v in POS6:
        if h==v: continue
        check(f"对位/{h}v{v}", pot="SRP",role="IP-PFR",board_text="As7h2c",street="翻牌",action="对手过牌",hero_pos=h,opp_pos=v)
# 6) 筹码深度
for st_ in STACKS:
    check(f"筹码/{st_}", pot="翻前",role="*",board_text="As7h2c",street="翻前",action="开池",hero_pos="BTN",stack=st_)
# 7) 简化开关
for sm in (False,True):
    for pot in POTS:
        check(f"简化{sm}/{pot}", pot=pot,role="IP-PFR",board_text="As7h2c",street="翻牌",action="对手过牌",simplify=sm)
# 8) 多人池对手
for opp in ["BB","BTN","CO"]:
    check(f"多人/{opp}", pot="3人池",role="IP-PFR",board_text="As7h2c",street="翻牌",action="对手过牌",hero_pos="BTN",opp_pos=opp)

dt=time.time()-t0
print(f"合计 {stats['ok']+stats['fail']+stats['exc']} 项  用时 {dt:.1f}s")
print(f"  ✅ 通过 {stats['ok']}")
print(f"  ⚠️ 查不到规则 {stats['fail']}")
print(f"  ❌ 抛异常 {stats['exc']}")
if errs:
    print("\n问题清单（前 25 条）：")
    for a,b in errs[:25]: print(f"  {a:<34}{b}")
    if len(errs)>25: print(f"  …还有 {len(errs)-25} 条")
