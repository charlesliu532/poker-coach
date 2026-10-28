"""底池赔率、EV、SPR 等确定性计算。

约定：pot 是"对手下注之前"的底池，bet 是面对的下注额（或你自己下注的额度）。
单位只要统一即可（筹码、bb、元都行）。
"""

from __future__ import annotations


def required_equity_call(pot: float, bet: float) -> float:
    """面对 bet 时，跟注需要的最低胜率 = bet / (pot + 2*bet)。"""
    if bet < 0:
        raise ValueError("下注额不能为负")
    if pot + 2 * bet <= 0:
        raise ValueError("底池和下注不能同时为 0")
    return bet / (pot + 2 * bet)


def pot_odds_ratio(pot: float, bet: float) -> float:
    """底池赔率，如 3.0 表示"跟 1 赢 3"。"""
    if bet <= 0:
        raise ValueError("下注额必须大于 0")
    return (pot + bet) / bet


def mdf(pot: float, bet: float) -> float:
    """最低防守频率：对手下注 bet，你至少要防守 pot/(pot+bet) 才不被任意诈唬剥削。"""
    if pot + bet <= 0:
        raise ValueError("参数非法")
    return pot / (pot + bet)


def alpha(pot: float, bet: float) -> float:
    """诈唬的盈亏平衡弃牌率：对手至少要弃 bet/(pot+bet)。"""
    if pot + bet <= 0:
        raise ValueError("参数非法")
    return bet / (pot + bet)


def ev_call(equity: float, pot: float, bet: float) -> float:
    """跟注的净 EV。equity 是你对对手范围的胜率（0~1）。"""
    if not 0 <= equity <= 1:
        raise ValueError("equity 需要在 0~1 之间")
    return equity * (pot + bet) - (1 - equity) * bet


def ev_bluff(fold_equity: float, pot: float, bet: float, equity_when_called: float = 0.0) -> float:
    """诈唬的净 EV。

    fold_equity: 对手弃牌概率
    equity_when_called: 被跟注后的胜率（纯空气牌填 0）
    """
    if not 0 <= fold_equity <= 1:
        raise ValueError("fold_equity 需要在 0~1 之间")
    called = 1 - fold_equity
    return fold_equity * pot + called * (equity_when_called * (pot + 2 * bet) - bet)


def ev_raise(equity_when_called: float, fold_equity: float, pot: float, bet: float, raise_to: float) -> float:
    """面对下注时加注的净 EV（raise_to 是加注到的总额）。"""
    called = 1 - fold_equity
    return fold_equity * (pot + bet) + called * (
        equity_when_called * (pot + bet + raise_to) - raise_to
    )


def spr(stack: float, pot: float) -> float:
    """筹码底池比。"""
    if pot <= 0:
        raise ValueError("底池必须大于 0")
    return stack / pot


def breakeven_fold_equity(pot: float, bet: float) -> float:
    """纯诈唬需要对手弃牌的比例（与 alpha 相同，名字更直白）。"""
    return alpha(pot, bet)


def analyze(pot: float, bet: float, equity: float | None = None) -> dict:
    """一次给出面对下注时的关键数字。"""
    out = {
        "pot": pot,
        "bet": bet,
        "required_equity_pct": round(required_equity_call(pot, bet) * 100, 2),
        "pot_odds": round(pot_odds_ratio(pot, bet), 2),
        "mdf_pct": round(mdf(pot, bet) * 100, 2),
        "alpha_pct": round(alpha(pot, bet) * 100, 2),
    }
    if equity is not None:
        out["equity_pct"] = round(equity * 100, 2)
        out["ev_call"] = round(ev_call(equity, pot, bet), 2)
        out["verdict"] = "跟注 +EV" if ev_call(equity, pot, bet) > 0 else "跟注 -EV"
        out["edge_pct"] = round((equity - required_equity_call(pot, bet)) * 100, 2)
    return out


def describe(pot: float, bet: float, equity: float | None = None) -> str:
    a = analyze(pot, bet, equity)
    lines = [
        f"底池 {pot:g}，面对下注 {bet:g}（{bet/pot*100:.0f}% 池）",
        f"  需要胜率 {a['required_equity_pct']}%（底池赔率 {a['pot_odds']}:1）",
        f"  最低防守频率 MDF {a['mdf_pct']}%",
    ]
    if equity is not None:
        lines.append(
            f"  你的胜率 {a['equity_pct']}%，边际 {a['edge_pct']:+.2f}% → {a['verdict']}，EV {a['ev_call']:+.2f}"
        )
    return "\n".join(lines)
