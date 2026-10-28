"""节点锁定：按 GTO solver 设计的「约束系统」实现（不是直接改策略）。

设计依据（来自自制 solver 架构文档）：
  Constraint { nodeId, type, payload, appliesTo }
  三种语义：
    constrained  —— 锁定后其余玩家照常解，得到「约束下的均衡」
    best_response—— 锁定对手，我方只做 max-EV（多人局唯一有意义的结果）
    one_sided    —— 锁定己方，看对手怎么剥削你

本模块只做「约束的存储 + 编译成范围」，求解交给 fastcalc（毫秒级近似）。

关键原则：
  1. 约束是独立文件，可叠加、可版本化
  2. 锁定不修改原规则，只作为查询输入
  3. 结果必须标注语义（constrained / best_response）
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

LOCK_FILE = "data/locks.json"

SEMANTICS = ("constrained", "best_response", "one_sided")


@dataclass
class Constraint:
    """一条锁定约束。"""
    pos: str                    # 锁哪个位置（UTG/CO/BTN/BB…）
    ctype: str = "range"        # range | strategy | force_action | remove_action
    payload: str = ""           # range 时是范围串；strategy 时是 JSON 分布
    player_type: str = "*"      # 该位置的对手形象
    stack: str = "*"            # 该位置的筹码深度
    note: str = ""
    created: float = field(default_factory=lambda: time.time())


@dataclass
class LockSet:
    """一组约束 + 求解语义。"""
    constraints: list = field(default_factory=list)
    semantics: str = "best_response"
    hero: str = ""

    # ── 增删查 ────────────────────────────────────────
    def set(self, c: Constraint):
        self.constraints = [x for x in self.constraints if x.pos != c.pos]
        self.constraints.append(c)

    def remove(self, pos: str):
        self.constraints = [x for x in self.constraints if x.pos != pos]

    def clear(self):
        self.constraints = []

    def get(self, pos: str):
        for x in self.constraints:
            if x.pos == pos:
                return x
        return None

    def positions(self) -> list:
        return [x.pos for x in self.constraints]

    # ── 序列化 ────────────────────────────────────────
    def to_dict(self) -> dict:
        return {"semantics": self.semantics, "hero": self.hero,
                "constraints": [asdict(x) for x in self.constraints]}

    @classmethod
    def from_dict(cls, d: dict) -> "LockSet":
        ls = cls(semantics=d.get("semantics", "best_response"),
                 hero=d.get("hero", ""))
        for item in d.get("constraints", []):
            try:
                ls.constraints.append(Constraint(**item))
            except TypeError:
                continue
        return ls


# ── 持久化（按会话存，可版本化）─────────────────────────
_CACHE = {"at": 0.0, "data": None}


def load(root: Path | None = None) -> LockSet:
    p = (root or Path(".")) / LOCK_FILE
    try:
        if p.exists():
            return LockSet.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        pass
    return LockSet()


def save(ls: LockSet, root: Path | None = None) -> bool:
    p = (root or Path(".")) / LOCK_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(ls.to_dict(), ensure_ascii=False, indent=2),
                     encoding="utf-8")
        _CACHE["data"] = None
        return True
    except Exception:
        return False


# ── 编译：约束 → 各位置的实际范围 ────────────────────────
def compile_ranges(ls: LockSet, hero_pos: str, opp_pos: str, pot: str = "SRP"):
    """把约束编译成 (我方范围, 对手范围)，供 fastcalc 算最佳反应。

    没有锁定的位置 → 用该位置的默认范围（开池或按底池类型）。
    """
    from .preflop import get as _get
    hero_lock = ls.get(hero_pos)
    opp_lock = ls.get(opp_pos)

    def _resolve(lock, pos, other):
        if lock and lock.ctype == "range" and lock.payload:
            return lock.payload, f"锁定：{lock.note or lock.payload[:20]}"
        try:
            return _get(pos, other), "默认范围"
        except Exception:
            return "", "无范围"

    hr, hsrc = _resolve(hero_lock, hero_pos, opp_pos)
    vr, vsrc = _resolve(opp_lock, opp_pos, hero_pos)
    return {"hero_range": hr, "hero_src": hsrc,
            "villain_range": vr, "villain_src": vsrc,
            "semantics": ls.semantics,
            "has_lock": bool(hero_lock or opp_lock)}


def describe(ls: LockSet) -> list:
    """给界面用：每条约束一句话。"""
    out = []
    for c in ls.constraints:
        bits = [c.pos]
        if c.player_type and c.player_type != "*":
            bits.append(f"形象 {c.player_type}")
        if c.stack and c.stack != "*":
            bits.append(f"{c.stack}")
        if c.ctype == "range" and c.payload:
            bits.append(f"范围 {c.payload[:26]}")
        out.append(" · ".join(bits))
    return out
