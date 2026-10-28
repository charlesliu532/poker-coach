"""手牌范围（range）解析。

支持写法（大写小写都行，逗号分隔）:
    AA, KK, AKs, AQo, T9s, 22-55, A5s-A2s, TT+, ATs+, KQo+
    AKs:0.5      # 带权重
    AhKh         # 指定花色
    random       # 任意两张
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

from .cards import RANK_INDEX, RANKS

_PAIR_RE = re.compile(r"^([2-9TJQKA])\1$")
_HAND_RE = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([SO])?$")
_SPECIFIC_RE = re.compile(r"^([2-9TJQKA])([shdc])([2-9TJQKA])([shdc])$", re.IGNORECASE)


class RangeError(ValueError):
    pass


@dataclass
class Combo:
    c1: int
    c2: int
    weight: float = 1.0

    @property
    def cards(self) -> tuple[int, int]:
        return (self.c1, self.c2)


def _combo(rank_hi: int, rank_lo: int, suited: bool | None) -> list[tuple[int, int]]:
    """给定两个 rank（hi > lo）与 suited 属性，展开成具体花色组合。"""
    out: list[tuple[int, int]] = []
    for s1 in range(4):
        for s2 in range(4):
            if suited is True and s1 != s2:
                continue
            if suited is False and s1 == s2:
                continue
            a = rank_hi * 4 + s1
            b = rank_lo * 4 + s2
            out.append((a, b))
    return out


def _pair(rank: int) -> list[tuple[int, int]]:
    return list(itertools.combinations([rank * 4 + s for s in range(4)], 2))


def _token_combos(token: str) -> list[tuple[int, int]]:
    raw = token.strip()
    m = _SPECIFIC_RE.match(raw)
    if m:
        r1, s1, r2, s2 = (g.upper() for g in m.groups())
        if r1 == r2 and s1 == s2:
            raise RangeError(f"同一张牌不能出现两次: {raw}")
        a = RANK_INDEX[r1] * 4 + "SHDC".index(s1)
        b = RANK_INDEX[r2] * 4 + "SHDC".index(s2)
        return [(min(a, b), max(a, b))]

    token = raw.upper()

    plus = False
    if token.endswith("+"):
        plus = True
        token = token[:-1]

    if "-" in token:
        lo_s, hi_s = token.split("-", 1)
        lo = _parse_base(lo_s)
        hi = _parse_base(hi_s)
        return _expand_dash(lo, hi)

    base = _parse_base(token)
    if plus:
        return _expand_plus(base)
    return _base_combos(base)


@dataclass(frozen=True)
class _Base:
    hi: int
    lo: int
    suited: bool | None  # None = 任意花色

    @property
    def is_pair(self) -> bool:
        return self.hi == self.lo


def _parse_base(token: str) -> _Base:
    token = token.strip().upper()
    m = _PAIR_RE.match(token)
    if m:
        r = RANK_INDEX[m.group(1)]
        return _Base(r, r, None)
    m = _HAND_RE.match(token)
    if m:
        r1, r2, s = m.groups()
        a, b = RANK_INDEX[r1], RANK_INDEX[r2]
        if a == b:
            return _Base(a, a, None)
        suited = {"S": True, "O": False}.get(s, None)
        return _Base(max(a, b), min(a, b), suited)
    raise RangeError(f"无法解析的范围片段: {token!r}")


def _base_combos(base: _Base) -> list[tuple[int, int]]:
    if base.is_pair:
        return _pair(base.hi)
    return _combo(base.hi, base.lo, base.suited)


def _expand_plus(base: _Base) -> list[tuple[int, int]]:
    """'TT+' -> TT..AA；'ATs+' -> ATs..AKs（顶牌固定，踢脚往上加）。"""
    if base.is_pair:
        return [c for r in range(base.hi, 13) for c in _pair(r)]
    return [c for kicker in range(base.lo, base.hi) for c in _combo(base.hi, kicker, base.suited)]


def _expand_dash(lo: _Base, hi: _Base) -> list[tuple[int, int]]:
    """'22-55' / 'A5s-A2s' / 'T9s-54s'。"""
    if lo.is_pair != hi.is_pair:
        raise RangeError("连写范围两端类型不一致")
    if lo.is_pair:
        a, b = sorted((lo.hi, hi.hi))
        return [c for r in range(a, b + 1) for c in _pair(r)]
    if lo.suited != hi.suited:
        raise RangeError("连写范围两端 suited 属性不一致")
    if lo.hi == hi.hi:
        a, b = sorted((lo.lo, hi.lo))
        return [c for k in range(a, b + 1) for c in _combo(lo.hi, k, lo.suited)]
    gap_lo = lo.hi - lo.lo
    gap_hi = hi.hi - hi.lo
    if gap_lo != gap_hi:
        raise RangeError("连写范围两端间隔不一致")
    a, b = sorted((lo.hi, hi.hi))
    return [c for top in range(a, b + 1) for c in _combo(top, top - gap_lo, lo.suited)]


def parse_range(text: str) -> list[tuple[int, int, float]]:
    """返回 [(c1, c2, weight)]，已去重（同组合取最大权重）。"""
    if not text or not text.strip():
        raise RangeError("范围为空")
    text = text.strip()
    if text.lower() in {"random", "any", "any2", "*"}:
        return [(a, b, 1.0) for a, b in itertools.combinations(range(52), 2)]

    weights: dict[tuple[int, int], float] = {}
    for raw in text.split(","):
        raw = raw.strip()
        if not raw:
            continue
        weight = 1.0
        if ":" in raw:
            raw, w = raw.split(":", 1)
            weight = float(w)
            weight = max(0.0, min(1.0, weight))
        for a, b in _token_combos(raw):
            key = (min(a, b), max(a, b))
            weights[key] = max(weights.get(key, 0.0), weight)
    if not weights:
        raise RangeError(f"范围为空: {text!r}")
    return [(a, b, w) for (a, b), w in sorted(weights.items())]


def combo_count(text: str) -> float:
    return sum(w for _, _, w in parse_range(text))


def remove_blocked(combos, board_cards) -> list[tuple[int, int, float]]:
    dead = set(board_cards)
    return [(a, b, w) for a, b, w in combos if a not in dead and b not in dead]
