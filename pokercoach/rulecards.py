"""从策略树生成复习卡。

为什么不用笔记抽取的卡：
  笔记抽出来的 num 卡题干经常被截断（"留 5–____ 最强牌在过牌里（A-A-8-2-6 的"），
  def 卡是词典释义（「遛入是什么意思」），对决策没帮助。
策略树是结构化数据，出题天然干净：场景 → 尺度 / 频率。
"""
from __future__ import annotations

import csv
from pathlib import Path

ROLE_CN = {"IP-PFR": "进攻·有位置", "OOP-PFR": "进攻·无位置",
           "IP-caller": "跟注·有位置", "OOP-caller": "跟注·无位置",
           "BvB-SB": "小盲", "BvB-BB": "大盲"}
POT_CN = {"SRP": "单加注池", "3BP": "3bet池", "3BP多人": "3bet多人池",
          "4BP": "4bet池", "多人池": "多人池", "翻前": "翻前"}
ACT_CN = {"对手过牌": "对手过牌", "对手小注": "对手小注", "对手大注": "对手大注",
          "对手中注": "对手中注", "无": "我先行动", "对手过牌加注": "对手过牌加注"}

# 高价值原则卡（这些是十四套课真正的结论，手写最准）
PRINCIPLES = [
    ("同一类牌面为什么会有相反的尺度？", "决定尺度的不是牌面类别，是「对手的坚果占比」。A85r 上 BB 没有坚果 → 大注逼弃；A32r 上 BB 全是顺子听牌 → 大注折损权益，只能小注。board_class 太粗，要看第二张牌。"),
    ("Donk 频率随筹码怎么变？", "20bb 约 81%，30bb 约 65%，15bb 以下直接两极分化（全压或过牌）。越浅越能 donk，因为面对加注可以轻松全压实现权益。"),
    ("15bb 以下该什么时候 donk 全压？", "低中连张面（765/876）：几乎所有对子 + 所有两头顺和卡顺都全压。超强牌（顺子/两对/暗三）反而过牌慢玩设陷阱。"),
    ("转牌的下注尺度由什么决定？", "自身的权益，不是牌面。权益 >70%（坚果级）用 66%+ 甚至无上限；权益 30–50%（中对/中等听牌）用 25–50% 小注。Bencb 大师课 M03-L33/L34。"),
    ("筹码越短越该慢玩吗？", "相反——越短越不能慢玩。短筹码下对手会用中等牌力赌一把，转牌任何高张或听牌完成都会变成 action killer，让你错失价值。15bb 级别顶对+ 在湿润面直接快玩。"),
    ("天花面（单色）的 cbet 频率是多少？", "约 50%，明显低于其他牌面（60%+）。因为跟注方在这种面上拥有坚果优势，PFR 的范围反而被压制。尺度仍用 25–33%。"),
    ("什么牌面该用 XR（过牌加注）？", "干燥公对面（如 K77）是典型：IP 高频小注 15–33%，OOP 拿暗三条 + 部分后门听牌做 3–4 倍 XR，构建极化范围。"),
    ("诈唬频率由什么决定？", "对手的弃牌率。对手按 MDF 防守时约 33%；对手从不弃牌时是 0%。不存在固定的「1/3」。"),
    ("什么情况下可以超池？", "坚果/极强价值 + 对手范围已封顶 + 转牌空白。河牌持坚果时理论上无上限。"),
    ("「范围封顶」是什么意思？", "对手在某节点从不以强牌采取该行动。封顶后你的下注/诈唬门槛下降、尺度可以放大。"),
    ("三人池里决定下注的是什么？", "不是整体权益，是坚果优势。三人池任何一方权益极少超过 50%（最有利面也约 43%）。"),
    ("MDF 该用在哪里？", "只约束「有摊牌价值」的那部分范围。0% 权益的错过听牌应 100% 弃牌，所以整体弃牌率高于 MDF 是正常的。"),
    ("多人池下注频率由什么决定？", "身后待行动人数（不是总人数）。身后人相同，频率就接近。"),
    ("翻牌的尺度由什么决定？", "静态面偏大（50–75%），动态面偏小（33%）。方向与直觉相反：牌面越动态，越该用小注。"),
    ("什么时候该平衡、什么时候不该？", "对手会调整才需要平衡。对手不会或不能调整时，纳什均衡就是最大化剥削策略——诈唬频率可以归零。"),
    ("XR（过牌加注）的尺码怎么定？", "找「能让对手犯错的最小尺度」。3x–4x 是默认；7x 无出处。牌的正面性差、听牌多的面用大一些。"),
    ("河牌抓诈唬怎么选牌？", "分两段：线性顶端（超对/顶对）+ 阻断牌抓诈（约各半）。不要阻断对手的诈唬组合，要阻断他的价值组合。"),
    ("为什么不能总用单一尺度下注？", "会制造可被剥削的封顶范围。多尺寸能分档取价值，但小注那条线要留一部分坚果当陷阱。"),
    ("BvB 的 SPR 意味着什么？", "常超过 15，接近超深 3bet 池。超对不再是坚果级，顶对远不如标准池稳固，薄价值三连注要取消。"),
]

def _ok(s: str) -> bool:
    s = (s or "").strip()
    return bool(s) and s not in ("—", "-", "*")

def build_cards(tree_dir: Path, limit: int = 400) -> list[dict]:
    path = Path(tree_dir) / "rules.csv"
    if not path.exists():
        return []
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8"))
            if r.get("status") == "active"]
    out, seen = [], set()

    for q, a in PRINCIPLES:
        out.append(dict(front=q, back=a, kind="principle", key=f"prin:{q[:24]}", tags="策略树·原则"))

    for r in rows:
        sizing = (r.get("sizing") or "").strip()
        freq = (r.get("freq") or "").strip()
        if not _ok(sizing):
            continue
        street, pot, role = r["street"], r["pot_type"], r["role"]
        if pot not in POT_CN:
            continue
        board = r.get("board_class") or "*"
        btxt = "任意牌面" if board == "*" else board
        extra = ""
        if (r.get("capped") or "*") != "*":
            extra = "（对手范围" + ("已封顶" if r["capped"] == "是" else "未封顶") + "）"
        elif (r.get("vs_type") or "*") != "*":
            extra = f"（对手类型：{r['vs_type']}）"
        elif (r.get("runout") or "*") != "*":
            extra = f"（转牌/河牌：{r['runout']}）"
        act = ACT_CN.get(r["node_action"], r["node_action"])
        front = f"{pot}·{street}·{ROLE_CN.get(role, role)}｜{btxt}｜{act}{extra} → 打多少？"
        if front in seen:
            continue
        seen.add(front)
        back = sizing
        if _ok(freq) and freq != "*":
            back += f"｜频率 {freq}"
        conf = r.get("conf") or ""
        src = r.get("source") or ""
        tag = f"策略树·{pot}"
        if conf == "低":
            tag += "·推导"
        out.append(dict(front=front, back=back, kind="rule",
                        key=f"rule:{r['rule_id']}:{board}", tags=tag))
        if len(out) >= limit:
            break
    return out
