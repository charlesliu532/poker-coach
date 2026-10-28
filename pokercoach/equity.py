"""牌力评估与胜率（equity）计算。

原则：所有数字都由这里的确定性算法算出来，不让语言模型心算。
- 5~7 张牌的牌力用向量化编码器打分，可一次处理上百万手牌
- 能精确枚举时精确枚举（river 永远精确），否则用蒙特卡洛并给出置信区间
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

from .cards import full_deck, parse_cards, pretty_cards
from .ranges import parse_range, remove_blocked

CATEGORY_NAMES = {8: "同花顺", 7: "四条", 6: "葫芦", 5: "同花", 4: "顺子", 3: "三条", 2: "两对", 1: "一对", 0: "高牌"}

_BASE = 77
_EXACT_LIMIT = 400_000


def _build_straight_table() -> np.ndarray:
    table = np.full(1 << 13, -1, dtype=np.int8)
    for high in range(3, 13):  # high = 顺子最大牌的 rank index
        need = (1 << 12) | 0b1111 if high == 3 else 0b11111 << (high - 4)
        for mask in range(1 << 13):
            if mask & need == need:
                table[mask] = high
    return table


_STRAIGHT = _build_straight_table()


def evaluate(cards: np.ndarray) -> np.ndarray:
    """cards: (N, K)，K 在 5~7 之间。返回 (N,) int64 分数，越大越强。"""
    cards = np.asarray(cards, dtype=np.int16)
    if cards.ndim != 2:
        raise ValueError("cards 需要二维数组 (N, K)")
    n, k = cards.shape
    if not 5 <= k <= 7:
        raise ValueError("每手牌需要 5~7 张")

    ranks = (cards // 4).astype(np.int32)
    suits = (cards % 4).astype(np.int32)
    rows = np.arange(n)
    R = np.arange(13)

    counts = np.bincount((rows[:, None] * 13 + ranks).ravel(), minlength=n * 13).reshape(n, 13)
    suit_counts = np.bincount((rows[:, None] * 4 + suits).ravel(), minlength=n * 4).reshape(n, 4)

    mask_all = np.zeros(n, dtype=np.int32)
    for j in range(k):
        mask_all |= 1 << ranks[:, j]
    mask_suit = np.zeros((n, 4), dtype=np.int32)
    for s in range(4):
        m = np.zeros(n, dtype=np.int32)
        for j in range(k):
            sel = suits[:, j] == s
            if sel.any():
                m[sel] |= 1 << ranks[sel, j]
        mask_suit[:, s] = m

    flush_suit = suit_counts.argmax(axis=1)
    has_flush = suit_counts.max(axis=1) >= 5
    straight_all = _STRAIGHT[mask_all].astype(np.int64)
    flush_straight = _STRAIGHT[mask_suit[rows, flush_suit]].astype(np.int64)

    # 同花时，最好的 5 张就是该花色里最大的 5 张
    flush_key = np.where(suits == flush_suit[:, None], ranks, -1)
    ftop = np.sort(flush_key, axis=1)[:, -5:][:, ::-1].astype(np.int64)

    max_count = counts.max(axis=1)
    quads = max_count == 4
    trips = max_count == 3
    multi = (counts >= 2).sum(axis=1)  # 至少两张的 rank 个数（两个三条也是葫芦）

    cat = np.zeros(n, dtype=np.int64)
    cat[(max_count == 2) & (multi == 1)] = 1
    cat[(max_count == 2) & (multi >= 2)] = 2
    cat[trips & (multi == 1)] = 3
    cat[(straight_all >= 0) & ~has_flush] = 4
    cat[has_flush] = 5
    cat[(max_count >= 3) & (multi >= 2)] = 6
    cat[quads] = 7
    cat[has_flush & (flush_straight >= 0)] = 8

    # ---- 同牌型内排序：选出"最好的 5 张"的 5 个点数 ----
    # 不能按 (张数, 点数) 直接排序：三条/三对时第三个对子会挤掉真正的踢脚
    present = counts > 0

    def desc(mask):
        m = np.where(mask, R[None, :], -1)
        return np.argsort(-m, axis=1)

    def kickers(excl, kk):
        m = present.copy()
        for e in excl:
            m[rows, e] = False
        return desc(m)[:, :kk]

    order2 = desc(counts >= 2)
    p1, p2 = order2[:, 0], order2[:, 1]
    t1 = desc(counts >= 3)[:, 0]
    q1 = desc(counts >= 4)[:, 0]

    digits = desc(present)[:, :5].astype(np.int64)

    def five(*cols):
        """拼成 (N, 5) 的点数位，不够的部分补 0。"""
        d = np.column_stack(cols).astype(np.int64)
        if d.shape[1] < 5:
            d = np.concatenate([d, np.zeros((n, 5 - d.shape[1]), dtype=np.int64)], axis=1)
        return d

    one_pair_d = five(p1, kickers([p1], 3))
    two_pair_d = five(p1, p2, kickers([p1, p2], 1))
    trips_d = five(t1, kickers([t1], 2))
    pair_ex = present & (counts >= 2)
    pair_ex[rows, t1] = False
    full_house_d = five(t1, desc(pair_ex)[:, 0])
    quads_d = five(q1, kickers([q1], 1))
    straight_d = five(straight_all)
    sf_d = five(flush_straight)

    digits[cat == 1] = one_pair_d[cat == 1]
    digits[cat == 2] = two_pair_d[cat == 2]
    digits[cat == 3] = trips_d[cat == 3]
    digits[cat == 4] = straight_d[cat == 4]
    digits[cat == 5] = ftop[cat == 5]
    digits[cat == 6] = full_house_d[cat == 6]
    digits[cat == 7] = quads_d[cat == 7]
    digits[cat == 8] = sf_d[cat == 8]

    powers = np.array([16 ** 4, 16 ** 3, 16 ** 2, 16, 1], dtype=np.int64)
    enc = digits @ powers
    return (cat << 40) | enc


def category_name(score: int) -> str:
    return CATEGORY_NAMES.get(int(score) >> 40, "?")


# ---------------------------------------------------------------- 输入解析


def _hand_combos(spec) -> list[tuple[int, int, float]]:
    """具体手牌（'AhKh' / [7, 19]）或 range 字符串，统一变成组合列表。"""
    if isinstance(spec, (list, tuple)) and spec and all(isinstance(c, (int, np.integer)) for c in spec):
        cards = [int(c) for c in spec]
        if len(cards) != 2:
            raise ValueError("具体手牌需要两张牌")
        if cards[0] == cards[1]:
            raise ValueError("两张牌不能相同")
        return [(min(cards), max(cards), 1.0)]
    if isinstance(spec, str):
        try:
            cards = parse_cards(spec)
            if len(cards) == 2:
                return [(min(cards), max(cards), 1.0)]
        except ValueError:
            pass
        return parse_range(spec)
    raise TypeError(f"无法识别的手牌写法: {spec!r}")


@dataclass
class EquityResult:
    equity: float
    win: float
    tie: float
    loss: float
    samples: int
    exact: bool
    hero: str = ""
    villain: str = ""
    board: str = ""
    multiway: list[float] = field(default_factory=list)

    @property
    def stderr(self) -> float:
        if self.exact or self.samples == 0:
            return 0.0
        p = min(max(self.equity, 1e-9), 1 - 1e-9)
        return float(np.sqrt(p * (1 - p) / self.samples))

    def to_dict(self) -> dict:
        d = {
            "equity": round(self.equity, 4),
            "equity_pct": round(self.equity * 100, 2),
            "win_pct": round(self.win * 100, 2),
            "tie_pct": round(self.tie * 100, 2),
            "loss_pct": round(self.loss * 100, 2),
            "samples": self.samples,
            "exact": self.exact,
            "hero": self.hero,
            "villain": self.villain,
            "board": self.board,
        }
        if not self.exact and self.samples:
            d["stderr_pct"] = round(self.stderr * 100, 2)
        if self.multiway:
            d["multiway_pct"] = [round(x * 100, 2) for x in self.multiway]
        return d

    def __str__(self) -> str:
        kind = "精确枚举" if self.exact else f"蒙特卡洛 {self.samples:,} 次"
        return (
            f"{self.hero} vs {self.villain} | 牌面 {self.board or '翻前'}\n"
            f"  胜率 {self.equity*100:.2f}%  "
            f"(胜 {self.win*100:.1f}% / 平 {self.tie*100:.1f}% / 负 {self.loss*100:.1f}%)\n"
            f"  方式: {kind}"
        )


# ---------------------------------------------------------------- 采样


class _ComboSet:
    """预先把组合矩阵化，采样时只做索引。"""

    def __init__(self, combos):
        if not combos:
            raise ValueError("组合为空")
        self.cards = np.array([[a, b] for a, b, _ in combos], dtype=np.int16)
        w = np.array([w for _, _, w in combos], dtype=np.float64)
        self.weights = w / w.sum()

    def sample(self, n, rng):
        idx = rng.choice(len(self.cards), size=n, p=self.weights)
        return self.cards[idx]


def _deal(n: int, sets: list[_ComboSet], board: list[int], need: int, rng, budget: int = 400):
    """同时抽出各家的手牌和剩余公共牌，保证互不重复。"""
    holes = [[] for _ in sets]
    draws = []
    got = 0
    fixed = np.array(board, dtype=np.int16)
    for _ in range(budget):
        if got >= n:
            break
        h = [s.sample(n, rng) for s in sets]
        d = rng.integers(0, 52, size=(n, need), dtype=np.int16) if need else np.zeros((n, 0), np.int16)
        allc = np.concatenate([*h, np.tile(fixed, (n, 1)), d], axis=1)
        s = np.sort(allc, axis=1)
        ok = np.all(np.diff(s, axis=1) != 0, axis=1)
        for i in range(len(sets)):
            holes[i].append(h[i][ok])
        draws.append(d[ok])
        got += int(ok.sum())

    if got == 0:
        raise RuntimeError("采样失败：公共牌与范围冲突过多")
    return [np.concatenate(x)[:n] for x in holes], np.concatenate(draws)[:n]


def _scores_of(holes, draw, board, need):
    n = len(holes[0])
    fixed = np.tile(np.array(board, dtype=np.int16), (n, 1)) if board else np.zeros((n, 0), np.int16)
    full = np.concatenate([fixed, draw], axis=1)
    hands = [np.concatenate([h, full], axis=1) for h in holes]
    return np.stack([evaluate(h) for h in hands], axis=1)


def _equity_from_scores(scores: np.ndarray):
    """返回 (每家平均 equity 数组, 独赢率, 平局率, 输率)。"""
    best = scores.max(axis=1, keepdims=True)
    is_winner = scores == best
    winners = is_winner.sum(axis=1)
    share = np.where(is_winner, 1.0 / winners[:, None], 0.0)
    per_player = share.mean(axis=0)
    # win/loss 站在第一个人（hero）的视角，多人底池里也是
    hero_best = is_winner[:, 0]
    win = float((hero_best & (winners == 1)).mean())
    tie = float((winners > 1).mean())
    return per_player, win, tie, max(0.0, 1.0 - win - tie)


def _n_boards(need: int) -> int:
    return {0: 1, 1: 46, 2: 990, 3: 15180, 5: 1_712_304}.get(need, 1)


# ---------------------------------------------------------------- 对外接口


def equity(hero, villain, board=(), *, n_samples: int = 20000, seed: int | None = 7, exact: bool | None = None) -> EquityResult:
    """两人底池胜率。hero / villain 可以是具体手牌，也可以是 range。"""
    board_cards = list(parse_cards(board) if isinstance(board, str) else board)
    if len(board_cards) not in (0, 3, 4, 5):
        raise ValueError("公共牌必须是 0/3/4/5 张")
    if len(set(board_cards)) != len(board_cards):
        raise ValueError("公共牌有重复")

    h_combos = remove_blocked(_hand_combos(hero), board_cards)
    v_combos = remove_blocked(_hand_combos(villain), board_cards)
    if not h_combos or not v_combos:
        raise ValueError("手牌与公共牌冲突，或范围被完全阻挡")
    need = 5 - len(board_cards)
    if exact is None:
        exact = len(h_combos) * len(v_combos) * _n_boards(need) <= _EXACT_LIMIT

    if exact:
        return _exact_equity(h_combos, v_combos, board_cards, need, hero, villain)

    rng = np.random.default_rng(seed)
    holes, draw = _deal(n_samples, [_ComboSet(h_combos), _ComboSet(v_combos)], board_cards, need, rng)
    scores = _scores_of(holes, draw, board_cards, need)
    per, w, t, l = _equity_from_scores(scores)
    return EquityResult(
        equity=float(per[0]), win=w, tie=t, loss=l, samples=len(scores), exact=False,
        hero=str(hero), villain=str(villain), board=pretty_cards(board_cards),
    )


def _exact_equity(h_combos, v_combos, board_cards, need, hero, villain) -> EquityResult:
    eq_sum = win_sum = tie_sum = total = 0.0
    for a, b, wa in h_combos:
        for c, d, wb in v_combos:
            used = {a, b, c, d} | set(board_cards)
            if len(used) < 4 + len(board_cards):
                continue
            rem = [x for x in full_deck() if x not in used]
            boards = list(itertools.combinations(rem, need)) if need else [()]
            m = len(boards)
            draw = np.array(boards, dtype=np.int16).reshape(m, need)
            fixed = np.tile(np.array(board_cards, dtype=np.int16), (m, 1)) if board_cards else np.zeros((m, 0), np.int16)
            full = np.concatenate([fixed, draw], axis=1)
            h7 = np.concatenate([np.tile([a, b], (m, 1)).astype(np.int16), full], axis=1)
            v7 = np.concatenate([np.tile([c, d], (m, 1)).astype(np.int16), full], axis=1)
            scores = np.stack([evaluate(h7), evaluate(v7)], axis=1)
            per, w, t, _ = _equity_from_scores(scores)
            weight = wa * wb
            eq_sum += float(per[0]) * m * weight
            win_sum += w * m * weight
            tie_sum += t * m * weight
            total += m * weight
    return EquityResult(
        equity=eq_sum / total, win=win_sum / total, tie=tie_sum / total,
        loss=max(0.0, 1 - (win_sum + tie_sum) / total),
        samples=int(total), exact=True,
        hero=str(hero), villain=str(villain), board=pretty_cards(board_cards),
    )


def equity_multi(specs: list, board=(), *, n_samples: int = 20000, seed: int | None = 7) -> EquityResult:
    """多人底池（2~4 人），multiway 里是每个人的 equity。"""
    if not 2 <= len(specs) <= 4:
        raise ValueError("支持 2~4 人")
    board_cards = list(parse_cards(board) if isinstance(board, str) else board)
    need = 5 - len(board_cards)
    rng = np.random.default_rng(seed)
    sets = [_ComboSet(remove_blocked(_hand_combos(s), board_cards)) for s in specs]
    holes, draw = _deal(n_samples, sets, board_cards, need, rng)
    scores = _scores_of(holes, draw, board_cards, need)
    per, w, t, l = _equity_from_scores(scores)
    return EquityResult(
        equity=float(per[0]), win=w, tie=t, loss=l, samples=len(scores), exact=False,
        hero=str(specs[0]), villain=" / ".join(str(s) for s in specs[1:]),
        board=pretty_cards(board_cards),
        multiway=[float(x) for x in per],
    )


def explain_equity(result: EquityResult, pot: float | None = None, bet: float | None = None) -> str:
    from .odds import required_equity_call

    lines = [str(result)]
    if pot is not None and bet:
        need_eq = required_equity_call(pot, bet)
        verdict = "跟注有利可图" if result.equity >= need_eq else "按纯赔率不该跟"
        lines.append(
            f"  底池 {pot:g}，对手下注 {bet:g} → 需要 {need_eq*100:.1f}% 胜率；"
            f"你有 {result.equity*100:.1f}% → {verdict}"
        )
    return "\n".join(lines)
