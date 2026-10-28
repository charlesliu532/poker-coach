#!/usr/bin/env python3
"""策略树查询：给定节点 → 规则 → 桶表 → 这手牌该怎么打。

用法：
  python3 lookup.py --pot SRP --role IP-PFR --board 高A-低-彩 --street 翻牌 --action 对手过牌 --hand 顶对好踢
  python3 lookup.py --test
"""
import argparse, csv
from pathlib import Path

ROOT = Path(__file__).parent
FIELDS = ("pot_type", "role", "board_class", "street", "node_action", "opp_pos", "stack")
WILD = {"*", "", "-"}

def load(name):
    with open(ROOT / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def score(rule, q):
    """返回特异度（命中的非通配字段数）；不匹配返回 -1。"""
    s = 0
    for k in FIELDS:
        v = (rule.get(k) or "*").strip()
        if v in WILD:
            continue
        if v != (q.get(k) or "").strip():
            return -1
        s += 1
    return s

def basis_of(table, buckets):
    for b in buckets:
        if b["table_id"] == table:
            return b.get("basis") or ""
    return ""

def resolve(hand, table, buckets):
    hit = [b for b in buckets if b["table_id"] == table and b["hand_class"] == hand]
    if not hit:
        hit = [b for b in buckets if b["table_id"] == table and b["hand_class"] == "其他"]
    return (hit[0]["bucket"], hit[0].get("unit") or "下注率") if hit else ("?", "?")

def query(q, rules, buckets):
    scored = [(score(r, q), r) for r in rules]
    scored = [(s, r) for s, r in scored if s >= 0]
    if not scored:
        return [], None
    top = max(s for s, _ in scored)
    return [(s, r) for s, r in scored if s == top], top

def show(q, hits, top, rules, buckets):
    print(f"\n查询：{' · '.join(str(q.get(k, '*')) for k in FIELDS)}  |  手牌：{q['hand']}")
    if not hits:
        print("  ✗ 没有匹配规则。可能原因：牌面类别拼错，或这条线还没录入。")
        return
    for i, (s, r) in enumerate(hits):
        mark = "⚠" if len(hits) > 1 else "→"
        bk, unit = resolve(q["hand"], r["bucket_table"], buckets)
        print(f"  {mark} {r['rule_id']}（特异度 {s}/{len(FIELDS)}）  {r['source']} · 置信 {r['conf']}")
        basis = basis_of(r["bucket_table"], buckets) if r["bucket_table"] not in WILD else ""
        tag = f"  ⚠ {basis}" if basis.startswith("反推") else (f"  [{basis}]" if basis else "")
        print(f"     尺度 {r['sizing']}   总频率 {r['freq']}   桶表 {r['bucket_table']}{tag}")
        if r["bucket_table"] in WILD:
            print("     桶表 —（本规则不定桶，按课程给的频率执行）")
        elif unit == "下注率":
            print(f"     「{q['hand']}」→ 桶 {bk}（≈ {bk}% 下注）")
        else:
            print(f"     「{q['hand']}」→ {bk}% {unit}")
        if r["note"]:
            print(f"     备注：{r['note']}")
    if len(hits) > 1:
        print(f"  ⚠ 有 {len(hits)} 条同特异度规则（冲突/并存），请人工裁决。")

CASES = [
    dict(pot_type="SRP", role="IP-PFR", board_class="高A-低-彩", street="翻牌", node_action="对手过牌", hand="顶对好踢", want="R01"),
    dict(pot_type="SRP", role="IP-PFR", board_class="高A-高-彩", street="翻牌", node_action="对手过牌", hand="顶对好踢", want="R02"),
    dict(pot_type="SRP", role="IP-PFR", board_class="高A-高-彩", street="转牌", node_action="对手过牌", hand="顶对弱踢", want="R16"),
    dict(pot_type="3BP", role="OOP-PFR", board_class="低-断-彩", street="翻牌", node_action="对手过牌", hand="超对", want="CONFLICT"),
    dict(pot_type="翻前", role="OOP-PFR", board_class="-", street="翻前", node_action="对手3bet", opp_pos="HJ", stack="100bb", hand="QQ/AKo", want="R61"),
    dict(pot_type="3BP", role="OOP-PFR", board_class="轮子", street="翻牌", node_action="对手过牌", hand="超对", want="R53"),
]

def run_tests(rules, buckets):
    ok = 0
    for c in CASES:
        want = c.pop("want")
        hits, _ = query(c, rules, buckets)
        got = [r["rule_id"] for _, r in hits]
        if want == "CONFLICT":
            good = len(hits) == 2
        else:
            good = want in got
        ok += good
        print(("✓" if good else "✗"), f"期望 {want}，实际 {got}")
        show(c, hits, None, rules, buckets)
    print(f"\n{ok}/{len(CASES)} 通过")
    return ok == len(CASES)

def main():
    ap = argparse.ArgumentParser()
    for f in FIELDS:
        ap.add_argument("--" + f.replace("node_", ""), dest=f, default="*")
    ap.add_argument("--hand", default="其他")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    rules, buckets = load("rules.csv"), load("buckets.csv")
    if a.test:
        raise SystemExit(0 if run_tests(rules, buckets) else 1)
    q = {k: getattr(a, k) for k in FIELDS}
    q["hand"] = a.hand
    hits, top = query(q, rules, buckets)
    show(q, hits, top, rules, buckets)

if __name__ == "__main__":
    main()
