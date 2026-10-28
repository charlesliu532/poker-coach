"""用 TexasSolver 跑节点，和策略树对比，找出偏差。

用法：python tools/solve_compare.py [节点名...]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOLVER = Path.home() / "tools/TexasSolver/TexasSolver-v0.2.0-MacOs/console_solver"

sys.path.insert(0, str(ROOT))
from pokercoach import preflop  # noqa: E402
from pokercoach.ranges import parse_range  # noqa: E402
from pokercoach import tree as T  # noqa: E402

RANKS = "23456789TJQKA"


def solver_range(spec: str) -> str:
    out = set()
    for a, b, _w in parse_range(spec):
        r1, s1 = RANKS[a >> 2], "shdc"[a & 3]
        r2, s2 = RANKS[b >> 2], "shdc"[b & 3]
        if r1 == r2:
            out.add(r1 + r2)
        elif s1 == s2:
            out.add(max(r1, r2) + min(r1, r2) + "s")
        else:
            out.add(max(r1, r2) + min(r1, r2) + "o")
    return ",".join(sorted(out))


CASES = {
    # ASCII 键（solver 读不了中文文件名）: (牌面, 我方, 对手, 底池bb, 筹码bb, 中文名)
    "a_high_tt": ("As,7s,2h", "BTN", "BB", 5.5, 100, "A高两色"),
    "k_high_r": ("Ks,8d,4c", "BTN", "BB", 5.5, 100, "K高彩虹"),
    "low_conn": ("8s,6h,5d", "BTN", "BB", 5.5, 100, "低连张"),
    "paired": ("Ks,7d,7c", "BTN", "BB", 5.5, 100, "公对面"),
    "double_bw": ("Qs,Jh,9d", "BTN", "BB", 5.5, 100, "双高张"),
    "low_r": ("Td,7s,3c", "BTN", "BB", 5.5, 100, "低彩虹"),
}


def run_solver(board: str, ip: str, oop: str, pot_bb: float, stack_bb: int, tag: str) -> dict | None:
    cfg = Path(f"/tmp/cal_{tag}.txt")
    out = Path(f"/tmp/cal_{tag}.json")
    if out.exists():
        out.unlink()
    cfg.write_text(f"""set_pot {int(pot_bb*100)}
set_effective_stack {stack_bb*100}
set_board {board}
set_range_ip {ip}
set_range_oop {oop}
set_bet_sizes oop,flop,bet,33,75
set_bet_sizes oop,flop,allin
set_bet_sizes ip,flop,bet,33,75
set_bet_sizes ip,flop,raise,60
set_bet_sizes ip,flop,allin
build_tree
set_thread_num 4
set_accuracy 1.0
set_max_iteration 80
set_print_interval 80
set_use_isomorphism 1
start_solve
set_dump_rounds 1
dump_result {out}
""", encoding="utf-8")
    try:
        # 必须在 solver 自己的目录下跑，否则加载不到资源
        subprocess.run([str(SOLVER), "-i", str(cfg)], capture_output=True, timeout=900,
                       cwd=str(SOLVER.parent))
    except subprocess.TimeoutExpired:
        return None
    if not out.exists():
        return None
    return json.loads(out.read_text(encoding="utf-8"))


def summarize(node: dict) -> dict:
    acts = node["actions"]
    st = node["strategy"]["strategy"]
    tot = len(st) or 1
    agg = {a: 0.0 for a in acts}
    for fr in st.values():
        for i, a in enumerate(acts):
            agg[a] += fr[i]
    bet = sum(v for a, v in agg.items() if a.startswith("BET"))
    return {
        "n": tot,
        "check_pct": round(agg["CHECK"] / tot * 100, 1),
        "bet_pct": round(bet / tot * 100, 1),
        "sizes": {a: round(v / tot * 100, 1) for a, v in agg.items() if a.startswith("BET")},
    }


def main():
    wanted = sys.argv[1:] or list(CASES)
    ip_spec = solver_range(preflop.get("BTN", "BB"))
    oop_spec = solver_range(preflop.get("BB", "BTN"))
    rows = []
    for name in wanted:
        board, hp, vp, pot_bb, stack_bb, cn = CASES[name]
        tag = name
        print(f"跑 {cn} ({board}) …", flush=True)
        data = run_solver(board, ip_spec, oop_spec, pot_bb, stack_bb, tag)
        if not data:
            print("  失败/超时")
            continue
        node = (data.get("childrens") or {}).get("CHECK")
        if not node:
            print("  没有 CHECK 分支")
            continue
        s = summarize(node)
        # 我们的树
        btxt = "".join(c for c in board.split(",")[0][0] + board.split(",")[1][0] + board.split(",")[2][0])
        bt = btxt + ("r" if len({c[1] for c in board.split(",")}) == 3 and all(len(c) == 2 for c in board.split(",")) else "")
        board_key = f"{board.split(',')[0][0]}{board.split(',')[1][0]}{board.split(',')[2][0]}"
        suits = [c[1] for c in board.split(",")]
        two_tone = len(set(suits)) == 2
        mono = len(set(suits)) == 1
        bt = board_key + ("m" if mono else ("tt" if two_tone else "r"))
        try:
            ours = T.grid(ROOT / "data/tree", "SRP", "IP-PFR", bt, "翻牌", "对手过牌", hero_pos=hp, opp_pos=vp)
        except Exception as e:
            ours = {"ok": False, "reason": str(e)}
        rows.append({"name": cn, "board": bt, "solver": s, "ours": ours})
    print("\n" + "=" * 78)
    print(f"{'节点':<14}{'牌面':<10}{'Solver下注':>10}{'我们下注':>10}{'差':>8}   尺度")
    print("-" * 78)
    for r in rows:
        sb = r["solver"]["bet_pct"]
        ok = r["ours"].get("ok")
        ob = r["ours"].get("range_bet_pct") if ok else None
        gap = f"{ob - sb:+.0f}" if ob is not None else "—"
        sz = r["ours"]["rule"]["sizing"] if ok else r["ours"].get("reason", "")
        sizes = ", ".join(f"{k.split()[1][:3]}={v}%" for k, v in r["solver"]["sizes"].items())
        print(f"{r['name']:<14}{r['board']:<10}{sb:>10}{str(ob):>10}{gap:>8}   {sz}  ｜ solver: {sizes}")
    Path("/tmp/calibration.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n明细存 /tmp/calibration.json")


if __name__ == "__main__":
    main()
