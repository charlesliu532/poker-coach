"""模拟牌桌：生成一个真实可玩的翻后场景，你选行动，系统给反馈。

不是 solver——它用三样东西给建议：
  1. 你的真实胜率（对对手范围的蒙特卡洛）
  2. 底池赔率 / MDF 这些硬数字
  3. 课程库里的经验规则
"""

from __future__ import annotations

import random

from .cards import RANKS, SUITS, card_str, parse_card
from .equity import equity as equity_calc
from .equity import evaluate
from .hh.advice import advice_for
from .playertypes import get as get_type
from .hh.rangechart import REFERENCE

# 对手在单加注池里的跟注范围（比开池范围宽一些，简化的通用范围）
CALL_RANGE = "22+, A2s+, K5s+, Q7s+, J8s+, T8s+, 98s, 87s, 76s, 65s, A7o+, K9o+, Q9o+, J9o+, T9o"
# 对手风格：决定他跟注/施压的宽窄
STYLE_RANGES = {
    "通用": CALL_RANGE,
    "紧": "77+, ATs+, KQs, AQo+, AJo, KQo",
    "松": "22+, A2s+, K2s+, Q4s+, J6s+, T6s+, 95s+, 84s+, 74s+, 63s+, 53s+, A2o+, K7o+, Q8o+, J8o+, T8o+, 98o",
}
THREE_BET_RANGE = "QQ+, AKs, AKo, A5s-A2s, KQs"

POS_ORDER = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]


def _fmt_cards(cards: list[int]) -> str:
    return " ".join(card_str(c) for c in cards)


def _deal(rng: random.Random, n: int) -> list[int]:
    deck = list(range(52))
    rng.shuffle(deck)
    return deck[:n]


def _combo_in_range(combos, hand: list[int]) -> bool:
    key = (min(hand), max(hand))
    return any((min(a, b), max(a, b)) == key for a, b, _ in combos)


def new_hand(seed: int | None = None, pot_type: str = "SRP", style: str = "紧凶", villain_range: str | None = None, store=None) -> dict:
    rng = random.Random(seed)
    hero_pos, villain_pos = rng.choice(
        [("BTN", "BB"), ("CO", "BB"), ("BTN", "SB"), ("UTG", "BB"), ("HJ", "BB")]
    )
    board = _deal(rng, 3)

    if pot_type == "3bet底池":
        hero_range = THREE_BET_RANGE
        villain_range = villain_range or "QQ+, AKs, AKo, JJ, AQs"
        pot, stack = 20.0, 80.0
    else:
        hero_range = REFERENCE.get(hero_pos, REFERENCE["BTN"])
        villain_range = villain_range or get_type(style)["range"]
        pot, stack = 6.5, 94.0

    # 从自己的开池范围里抽一手牌，避免出现 72o 在 UTG 开池这种假牌
    from .ranges import parse_range

    combos = [c for c in parse_range(hero_range)]
    rng.shuffle(combos)
    hero = None
    for a, b, _ in combos:
        if a not in board and b not in board:
            hero = [a, b]
            break
    hero = hero or _deal(rng, 2)

    # 对手的真实底牌：从它的范围里抽，且不能和牌面/英雄撞牌
    vcombos = [(a, b) for a, b, _ in parse_range(villain_range) if a not in board and b not in board and a not in hero and b not in hero]
    villain_hole = list(rng.choice(vcombos)) if vcombos else _deal(rng, 2)

    # 对手的翻牌动作：按牌力决定，而不是掷硬币
    cat = _category(villain_hole, board)
    draw = _has_draw(villain_hole, board)
    if rng.random() < _villain_lead_prob(cat, draw, "flop", False):
        frac = rng.choice([1 / 3, 1 / 2, 2 / 3])
        bet = round(pot * frac, 1)
        facing = bet
        oline = "B"
    else:
        facing, bet = 0.0, 0.0
        oline = "X"

    from .hh.spotdb import _board_class, _connected, _suited_class

    ranks = [c // 4 for c in board]
    advice = advice_for(
        {
            "street": "flop",
            "role": "防守" if facing else "进攻",
            "high": _board_class(board),
            "suit": _suited_class(board),
            "paired": "1" if len(set(ranks)) < 3 else "0",
            "connected": "1" if _connected(board) else "0",
            "oline": oline,
            "pot_type": pot_type,
        },
        store,
    )

    return {
        "street": "flop",
        "opp_desc": f"对手 {villain_pos} " + (f"下注 {bet:.1f}" if facing else "过牌"),
        "history": [],
        "board": board,
        "hero": hero,
        "hero_pos": hero_pos,
        "villain_pos": villain_pos,
        "pot": pot,
        "stack": stack,
        "facing": facing,
        "oline": oline,
        "pot_type": pot_type,
        "villain_range": villain_range,
        "villain_hole": villain_hole,
        "villain_bet_last": oline == "B",
        "style": style,
        "equity": equity_calc(_fmt_cards(hero), villain_range, _fmt_cards(board), n_samples=12000).to_dict(),
        "advice": advice,
        "log": [],
    }


def _category(hand: list[int], board: list[int]) -> int:
    """0 高牌 … 8 同花顺。"""
    import numpy as np

    score = int(evaluate(np.array([hand + board], dtype=np.int16))[0])
    return score >> 40


def _has_draw(hand: list[int], board: list[int]) -> bool:
    if len(board) >= 5:
        return False
    cards = hand + board
    suits = [c % 4 for c in cards]
    if any(suits.count(s) == 4 for s in range(4)):
        return True
    ranks = sorted({c // 4 for c in cards})
    for i in range(len(ranks) - 3):
        if ranks[i + 3] - ranks[i] <= 4:
            return True
    return False


def _villain_lead_prob(cat: int, draw: bool, street: str, bet_last: bool) -> float:
    """对手主动下注的概率：跟注者在翻牌很少领打，强牌/听牌才提高。"""
    p = 0.04
    if cat >= 6:
        p += 0.30
    elif cat >= 2:
        p += 0.16
    elif cat == 1:
        p += 0.06 if street != "flop" else 0.02
    if draw:
        p += 0.08
    if bet_last:
        p += 0.10
    if street == "flop":
        p *= 0.6   # 翻牌领打（donk）本来就少见
    elif street == "river":
        p *= 0.8   # 河牌没有听牌，领打更少
    return min(p, 0.5)


def _villain_raise_prob(cat: int, draw: bool) -> float:
    """面对你的下注，对手过牌加注的概率。强牌高、听牌做半诈唬、空气很低。"""
    if cat >= 6:
        return 0.28
    if cat >= 2:
        return 0.15
    if draw:
        return 0.07
    return 0.02


def _villain_fold_prob(cat: int, draw: bool, bet_frac: float) -> float:
    """面对你的下注，对手弃牌的概率。"""
    if cat >= 2:
        return 0.02
    if cat == 1:
        return 0.10 if bet_frac >= 0.6 else 0.04
    base = 0.30 if draw else 0.55
    return min(0.8, base + max(0.0, bet_frac - 0.5) * 0.3)


def _required(pot: float, bet: float) -> float:
    return bet / (pot + 2 * bet) if bet else 0.0


def act(state: dict, action: str, amount: float | None = None, store=None) -> dict:
    """执行一个行动，返回反馈 + 下一街的状态。"""
    from .hh.spotdb import runout_class

    board = list(state["board"])
    pot = state["pot"]
    facing = state["facing"]
    hero = state["hero"]
    eq = state["equity"]["equity"]

    if facing > 0 and action == "check":
        raise ValueError("面对下注时不能过牌，请选择弃牌/跟注/加注")
    if facing == 0 and action in ("call", "fold"):
        raise ValueError("没人下注，不能跟注或弃牌")

    feedback = {"action": action, "pot_before": pot, "facing": facing}
    label = {"fold": "弃牌", "check": "过牌", "call": f"跟注 {facing:.1f}", "bet": "下注", "raise": "加注"}.get(action, action)
    history = list(state.get("history") or [])
    history.append({"street": state["street"], "opp": state.get("opp_desc", ""), "hero": label})
    if action == "fold":
        feedback["verdict"] = "弃牌：放弃这部分底池权益。"
        feedback["done"] = True
        return {"state": state, "feedback": feedback, "history": history}
    if action == "call" and facing:
        need = _required(pot, facing)
        ev = eq * (pot + facing) - (1 - eq) * facing
        feedback.update(
            required_pct=round(need * 100, 1),
            ev=round(ev, 2),
            verdict=f"跟注需要 {need*100:.0f}% 胜率，你有 {eq*100:.1f}% → {'+EV' if ev > 0 else '-EV'}",
        )
        pot += facing * 2
    elif action == "check":
        feedback["verdict"] = "过牌，把决策交给对手。"
    elif action in ("bet", "raise"):
        frac = amount if amount else 0.66
        bet = round(pot * frac, 1)
        need_fold = bet / (pot + bet)
        vcat = _category(state["villain_hole"], board)
        vdraw = _has_draw(state["villain_hole"], board)
        fold_p = _villain_fold_prob(vcat, vdraw, frac)
        feedback.update(
            bet=bet,
            fold_needed_pct=round(need_fold * 100, 1),
            villain_fold_pct=round(fold_p * 100),
            verdict=f"下注 {bet:.1f}（{frac*100:.0f}% 池）：纯诈唬需要对手弃牌 {need_fold*100:.0f}% 才不亏。",
        )
        import random as _r
        raise_p = _villain_raise_prob(vcat, vdraw)
        if state.get("vil_raised_street") != state["street"] and _r.random() < raise_p:
            raise_to = round(bet * 2.5, 1)
            need = round(raise_to - bet, 1)
            history.append({"street": state["street"], "opp": f"你下注 {bet:.1f}", "hero": f"对手加注到 {raise_to:.1f}"})
            feedback.update(
                villain_raised=True,
                raise_to=raise_to,
                verdict=f"对手过牌加注到 {raise_to:.1f}，你需要再跟 {need:.1f}。",
            )
            state = dict(state)
            state.update(
                facing=need,
                opp_desc=f"对手 {state['villain_pos']} 过牌加注到 {raise_to:.1f}",
                vil_raised_street=state["street"],
                history=history,
            )
            state["advice"] = advice_for(
                {
                    "street": state["street"],
                    "role": "防守",
                    "oline": "XR",
                    "pot_type": state.get("pot_type"),
                    "runout": state.get("runout", ""),
                },
                store,
            )
            return {"state": state, "feedback": feedback, "history": history}

        if _r.random() < fold_p:
            feedback["verdict"] += " 对手弃牌，你直接拿下底池。"
            feedback["done"] = True
            feedback["won_by_fold"] = True
            return {"state": state, "feedback": feedback, "history": history, "showdown": {"result": "win", "text": "对手弃牌，你赢下底池。", "villain": ""}}
        pot += bet * 2

    # 推进到下一条街
    order = ["flop", "turn", "river"]
    idx = order.index(state["street"])
    if idx >= 2:
        feedback.update(done=True, verdict=feedback.get("verdict", "") + "（河牌结束）")
        return {"state": state, "feedback": feedback, "showdown": _showdown(state)}

    rng = random.Random()
    used = set(board) | set(hero)
    new_card = rng.choice([c for c in range(52) if c not in used])
    runout = runout_class(board, new_card)
    board.append(new_card)

    # 对手下一条街的动作：还按牌力 + 上一街是否在打
    ncat = _category(state["villain_hole"], board)
    ndraw = _has_draw(state["villain_hole"], board)
    lead_p = _villain_lead_prob(ncat, ndraw, order[idx + 1], bool(state.get("villain_bet_last")))
    if rng.random() < lead_p:
        frac = rng.choice([1 / 3, 1 / 2, 2 / 3])
        facing = round(pot * frac, 1)
        oline = "B"
        bet_last = True
    else:
        facing = 0.0
        oline = "X"
        bet_last = False

    nxt = dict(state)
    nxt.update(
        history=history,
        opp_desc=f"对手 {state['villain_pos']} " + (f"下注 {facing:.1f}" if facing else "过牌"),
        street=order[idx + 1],
        board=board,
        pot=pot,
        facing=facing,
        oline=oline,
        villain_bet_last=bet_last,
        equity=equity_calc(_fmt_cards(hero), state["villain_range"], _fmt_cards(board), n_samples=12000).to_dict(),
    )
    nxt["advice"] = advice_for(
        {
            "street": order[idx + 1],
            "role": "防守" if facing else "进攻",
            "runout": runout,
            "oline": oline,
            "pot_type": state["pot_type"],
        },
        store,
    )
    return {"state": nxt, "feedback": feedback, "history": history}


def _showdown(state: dict) -> dict:
    """用对手的真实底牌比大小。"""
    board = state["board"]
    hero = state["hero"]
    v = state.get("villain_hole")
    if not v:
        return {"text": "对手底牌未知"}
    used = set(board) | set(hero)
    if any(c in used for c in v):
        return {"text": "对手底牌与牌面冲突"}
    import numpy as np

    scores = evaluate(np.array([hero + board, list(v) + board], dtype=np.int16))
    win = int(scores[0]) > int(scores[1])
    tie = int(scores[0]) == int(scores[1])
    return {
        "villain": _fmt_cards(list(v)),
        "result": "win" if win else ("tie" if tie else "lose"),
        "text": f"摊牌：对手是 {_fmt_cards(list(v))}，你{'赢' if win else ('平' if tie else '输')}。",
    }
