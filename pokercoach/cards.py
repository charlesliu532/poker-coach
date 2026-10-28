"""牌的表示与解析。

牌用 0..51 的整数表示: card = rank_index * 4 + suit_index
rank 顺序: 2 3 4 5 6 7 8 9 T J Q K A   -> 0..12
suit 顺序: s h d c                     -> 0..3
"""

from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "shdc"
SUIT_SYMBOL = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

RANK_INDEX = {r: i for i, r in enumerate(RANKS)}
SUIT_INDEX = {s: i for i, s in enumerate(SUITS)}


class CardError(ValueError):
    pass


def parse_card(text: str) -> int:
    """解析单张牌: 'Ah' / 'ah' / '10h' / 'Th' 都可以。"""
    t = text.strip().replace("10", "T")
    if len(t) != 2:
        raise CardError(f"无法解析的牌: {text!r}")
    rank, suit = t[0].upper(), t[1].lower()
    if rank not in RANK_INDEX or suit not in SUIT_INDEX:
        raise CardError(f"无法解析的牌: {text!r}")
    return RANK_INDEX[rank] * 4 + SUIT_INDEX[suit]


def card_str(card: int) -> str:
    return RANKS[card // 4] + SUITS[card % 4]


def card_pretty(card: int) -> str:
    return RANKS[card // 4] + SUIT_SYMBOL[SUITS[card % 4]]


def parse_cards(text: str) -> list[int]:
    """解析一串牌，允许空格/逗号分隔，也允许连写: 'AhKh' / 'Ah, Kh' / 'Kh7h2c'。"""
    if text is None:
        return []
    cleaned = text.replace("10", "T").replace(",", " ").replace("/", " ")
    out: list[int] = []
    for token in cleaned.split():
        if len(token) % 2 == 0:
            for i in range(0, len(token), 2):
                out.append(parse_card(token[i : i + 2]))
        else:
            raise CardError(f"无法解析的牌组: {token!r}（牌数必须是偶数）")
    return out


def full_deck() -> list[int]:
    return list(range(52))


def rank_of(card: int) -> int:
    return card // 4


def suit_of(card: int) -> int:
    return card % 4


def pretty_cards(cards) -> str:
    return " ".join(card_pretty(c) for c in cards)
