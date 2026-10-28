"""GGPoker 手牌历史解析。

格式样例：
    Poker Hand #RC4815149750: Hold'em No Limit ($0.01/$0.02) - 2026/09/19 16:01:24
    Table 'RushAndCash33403974' 6-max Seat #1 is the button
    Seat 1: 3aa9bfdc ($2 in chips)
    20547e20: posts small blind $0.01
    *** HOLE CARDS ***
    Dealt to Hero [5h 6c]
    Hero: folds
    *** FLOP *** [2h 4s 3s]
    *** TURN *** [2h 4s 3s] [Kd]
    *** RIVER *** [2h 4s 3s Kd] [8c]
    *** SHOWDOWN ***
    78fc7825: collected $0.85 from pot
    *** SUMMARY ***
    Total pot $0.92 | Rake $0.04 ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_HAND_SPLIT = re.compile(r"(?=^Poker Hand #)", re.M)

_HEADER = re.compile(
    r"^Poker Hand #(?P<id>\S+):\s+Hold'em\s+(?:No Limit|Pot Limit)\s+"
    r"\(\$?(?P<sb>[\d.]+)/\$?(?P<bb>[\d.]+)\)\s+-\s+(?P<date>[\d/]+\s+[\d:]+)",
    re.M,
)
_TABLE = re.compile(r"^Table '(?P<table>[^']+)'\s+(?P<max>\d+)-max\s+Seat #(?P<seat>\d+) is the button", re.M)
_SEAT = re.compile(r"^Seat (?P<seat>\d+): (?P<name>.+?) \(\$?(?P<stack>[\d.,]+) in chips\)", re.M)
_BLIND = re.compile(r"^(?P<name>.+?): posts (?P<kind>small|big|the ante) blind \$?(?P<amount>[\d.]+)", re.M)
_DEALT = re.compile(r"^Dealt to (?P<name>[^\[\n]+?)(?: \[(?P<cards>[^\]]+)\])?\s*$", re.M)
_ACTION = re.compile(r"^(?P<name>.+?): (?P<kind>folds|checks|calls|bets|raises|is all-in)(?P<rest>.*)$")
# 注意：GG 的 collected 行没有冒号，"Hero collected $0.85 from pot"
_COLLECT = re.compile(r"^(?P<name>.+?) collected \$?(?P<amount>[\d.,]+) from pot", re.M)
_UNCALLED = re.compile(r"^Uncalled bet \(\$?(?P<amount>[\d.,]+)\) returned to (?P<name>.+?)\s*$", re.M)
_POT = re.compile(r"^Total pot \$?(?P<pot>[\d.,]+) \| Rake \$?(?P<rake>[\d.,]+)", re.M)
_BOARD = re.compile(r"^Board \[(?P<board>[^\]]+)\]", re.M)
_SHOW = re.compile(r"^(?P<name>.+?): shows \[(?P<cards>[^\]]+)\]", re.M)

_RAISE_TO = re.compile(r"([\d.]+) to \$?([\d.]+)")
_CALL_AMT = re.compile(r"\$?([\d.]+)")
_BET_AMT = re.compile(r"\$?([\d.]+)")
_ALLIN_AMT = re.compile(r"\$?([\d.]+)")

STREETS = ("preflop", "flop", "turn", "river")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


@dataclass
class Action:
    street: str
    seq: int
    player: str
    kind: str
    amount: float = 0.0     # 本动作投入的筹码（raise 为总额）
    to: float = 0.0         # raise 到多少


@dataclass
class Hand:
    hand_id: str
    played_at: str
    sb: float
    bb: float
    table: str
    max_players: int
    button: int
    seats: dict[str, dict] = field(default_factory=dict)   # name -> {seat, stack, pos}
    hero: str = ""
    hero_cards: list[str] = field(default_factory=list)
    board: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    pot: float = 0.0
    rake: float = 0.0
    collected: dict[str, float] = field(default_factory=dict)
    returned: dict[str, float] = field(default_factory=dict)
    shown: dict[str, list[str]] = field(default_factory=dict)

    # ---------- 派生 ----------

    @property
    def positions(self) -> dict[str, str]:
        return {n: s["pos"] for n, s in self.seats.items()}

    def hero_invested(self) -> float:
        spent = 0.0
        for a in self.actions:
            if a.player != self.hero:
                continue
            if a.kind in ("calls", "bets"):
                spent += a.amount
            elif a.kind == "raises":
                spent += a.to
        return spent

    def hero_net(self) -> float:
        """净输赢 = 赢到的底池 + 未被跟注退回的筹码 - 自己投入的筹码。"""
        return (
            self.collected.get(self.hero, 0.0)
            + self.returned.get(self.hero, 0.0)
            - self.hero_invested()
        )

    def actions_by(self, street: str) -> list[Action]:
        return [a for a in self.actions if a.street == street]

    def hero_actions(self, street: str) -> list[Action]:
        return [a for a in self.actions_by(street) if a.player == self.hero]

    def to_dict(self) -> dict:
        return {
            "hand_id": self.hand_id,
            "played_at": self.played_at,
            "sb": self.sb,
            "bb": self.bb,
            "table": self.table,
            "max_players": self.max_players,
            "button": self.button,
            "seats": self.seats,
            "hero": self.hero,
            "hero_cards": self.hero_cards,
            "board": self.board,
            "pot": self.pot,
            "rake": self.rake,
            "collected": self.collected,
            "returned": self.returned,
            "shown": self.shown,
            "actions": [a.__dict__ for a in self.actions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Hand":
        h = cls(
            hand_id=d["hand_id"], played_at=d["played_at"], sb=d["sb"], bb=d["bb"],
            table=d["table"], max_players=d["max_players"], button=d["button"],
            seats=d["seats"], hero=d["hero"], hero_cards=d["hero_cards"], board=d["board"],
            pot=d["pot"], rake=d["rake"], collected=d["collected"],
            returned=d.get("returned", {}), shown=d["shown"],
        )
        h.actions = [Action(**a) for a in d["actions"]]
        return h


_POS_ORDER = ("BTN", "SB", "BB", "UTG", "HJ", "CO")


def _assign_positions(seats: dict[str, dict], button: int, max_players: int) -> None:
    ordered = sorted(seats.items(), key=lambda kv: (kv[1]["seat"] - button) % max_players)
    for i, (_name, info) in enumerate(ordered):
        info["pos"] = _POS_ORDER[i] if i < len(_POS_ORDER) else f"P{i+1}"


def parse_hand(block: str) -> Hand | None:
    m = _HEADER.search(block)
    if not m:
        return None
    t = _TABLE.search(block)
    hand = Hand(
        hand_id=m.group("id"),
        played_at=m.group("date"),
        sb=_num(m.group("sb")),
        bb=_num(m.group("bb")),
        table=t.group("table") if t else "",
        max_players=int(t.group("max")) if t else 6,
        button=int(t.group("seat")) if t else 0,
    )
    for s in _SEAT.finditer(block):
        hand.seats[s.group("name")] = {"seat": int(s.group("seat")), "stack": _num(s.group("stack")), "pos": ""}

    for d in _DEALT.finditer(block):
        if d.group("cards"):
            hand.hero = d.group("name")
            hand.hero_cards = d.group("cards").split()
    if not hand.hero:
        # 有些平台不写 "Dealt to X [..]"，退化成 Seat 里叫 Hero 的
        if "Hero" in hand.seats:
            hand.hero = "Hero"
        else:
            return None

    # 位置
    _assign_positions(hand.seats, hand.button, hand.max_players)

    # 动作 + 街道
    street = "preflop"
    seq = 0
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("*** FLOP ***"):
            street = "flop"
            continue
        if line.startswith("*** TURN ***"):
            street = "turn"
            continue
        if line.startswith("*** RIVER ***"):
            street = "river"
            continue
        if line.startswith("*** SHOWDOWN ***") or line.startswith("*** SUMMARY ***"):
            street = "showdown" if street != "summary" else street
            continue
        bm = _BLIND.match(line)
        if bm:
            seq += 1
            amt = _num(bm.group("amount"))
            hand.actions.append(Action(street, seq, bm.group("name"), "post", amt, amt))
            continue
        am = _ACTION.match(line)
        if am and am.group("name") in hand.seats:
            seq += 1
            kind = am.group("kind")
            rest = am.group("rest") or ""
            amount = to = 0.0
            if kind == "raises":
                rm = _RAISE_TO.search(rest)
                if rm:
                    to = _num(rm.group(2))
                    amount = to
            elif kind == "calls":
                cm = _CALL_AMT.search(rest)
                amount = _num(cm.group(1)) if cm else 0.0
            elif kind == "bets":
                bm2 = _BET_AMT.search(rest)
                amount = _num(bm2.group(1)) if bm2 else 0.0
            elif kind == "is all-in":
                am2 = _ALLIN_AMT.search(rest)
                amount = to = _num(am2.group(1)) if am2 else 0.0
            hand.actions.append(Action(street, seq, am.group("name"), kind, amount, to))
            continue

    for c in _COLLECT.finditer(block):
        hand.collected[c.group("name")] = hand.collected.get(c.group("name"), 0.0) + _num(c.group("amount"))
    for u in _UNCALLED.finditer(block):
        hand.returned[u.group("name")] = hand.returned.get(u.group("name"), 0.0) + _num(u.group("amount"))
    for s in _SHOW.finditer(block):
        hand.shown[s.group("name")] = s.group("cards").split()

    pm = _POT.search(block)
    if pm:
        hand.pot = _num(pm.group("pot"))
        hand.rake = _num(pm.group("rake"))
    bm = _BOARD.search(block)
    if bm:
        hand.board = bm.group("board").split()

    return hand


def parse_file(path: str | Path) -> tuple[list[Hand], int]:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    hands, bad = [], 0
    for block in _HAND_SPLIT.split(text):
        block = block.strip()
        if not block.startswith("Poker Hand #"):
            continue
        try:
            h = parse_hand(block)
        except Exception:
            h = None
        if h:
            hands.append(h)
        else:
            bad += 1
    return hands, bad


def parse_paths(paths: list[str | Path]) -> tuple[list[Hand], dict]:
    files, bad = 0, 0
    out: list[Hand] = []
    for p in paths:
        p = Path(p)
        candidates = [p] if p.is_file() else sorted(p.rglob("*.txt"))
        for f in candidates:
            hands, b = parse_file(f)
            out.extend(hands)
            bad += b
            files += 1
    return out, {"files": files, "hands": len(out), "unparsed": bad}
