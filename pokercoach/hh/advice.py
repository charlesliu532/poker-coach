"""伪 solver：按"牌面 × 角色 × 池型"给基础建议。

这些不是 GTO 解，是把公开的通用打法原则写成规则：
频率、尺度、为什么、以及常见的错误做法。
每条规则只在对应条件全部命中时生效，越具体的规则优先级越高。
"""

from __future__ import annotations

# ---------------- 预设牌面 ----------------

PRESETS = {
    "flop": [
        {"name": "A高干燥", "filters": {"high": "A高", "suit": "彩虹面", "paired": "0", "connected": "0"}},
        {"name": "A高双花", "filters": {"high": "A高", "suit": "双花面"}},
        {"name": "双高干燥", "filters": {"high": "双高", "suit": "彩虹面", "paired": "0"}},
        {"name": "低牌连张", "filters": {"high": "低牌", "connected": "1"}},
        {"name": "对子面", "filters": {"paired": "1"}},
        {"name": "单色面", "filters": {"suit": "单色面"}},
    ],
    "turn": [
        {"name": "转牌超张", "filters": {"runout": "超张"}},
        {"name": "转牌成花", "filters": {"runout": "成花"}},
        {"name": "转牌公对", "filters": {"runout": "公对面"}},
        {"name": "转牌白板", "filters": {"runout": "白板"}},
    ],
    "river": [
        {"name": "河牌超张", "filters": {"runout": "超张"}},
        {"name": "河牌成花", "filters": {"runout": "成花"}},
        {"name": "河牌白板", "filters": {"runout": "白板"}},
    ],
}

# ---------------- 建议规则 ----------------
# 条件里出现的键必须全部命中；越具体的规则分数越高，优先返回。

RULES = [
    {
        "when": {"street": "flop", "high": "A高", "role": "进攻"},
        "freq": "下注 75~85%", "size": "25~33% 池",
        "why": "A 高面你垄断坚果优势，对手很难拿到强牌；小尺度全范围下注就能逼掉大量空气。",
        "avoid": "别用大尺度——那会把你的范围压缩成两极化，中等牌反而不好打。",
    },
    {
        "when": {"street": "flop", "high": "A高", "role": "防守"},
        "freq": "防守 55~65%", "size": "跟注为主，弃牌 35~45%",
        "why": "A 高面对手范围里有大量 Ax 和中对，但你的大盲范围也有不少 Ax；不要一看到 A 就弃。",
        "avoid": "别用「没有 A 就弃」处理——对手在小尺度下注时诈唬比例不低。",
    },
    {
        "when": {"street": "flop", "high": "双高", "role": "进攻"},
        "freq": "下注 55~65%", "size": "33% 池为主，连牌面降到 25%",
        "why": "双高面（KQJ、QJT）对手的顺子听牌很多，你的范围优势被削弱，频率要明显低于 A 高面。",
        "avoid": "别照搬 A 高面的 80% 频率——那是这页最容易漏钱的地方。",
    },
    {
        "when": {"street": "flop", "high": "低牌", "connected": "1", "role": "进攻"},
        "freq": "下注 30~40%", "size": "过牌为主，下注用 66% 池",
        "why": "低牌连张（765、876）是对手范围最舒服的面，你的范围优势最小，应该多过牌、下注时用大尺度。",
        "avoid": "不要小尺度高频——会被大量加注打穿。",
    },
    {
        "when": {"street": "flop", "high": "低牌", "role": "进攻"},
        "freq": "下注 40~55%", "size": "33% 池",
        "why": "低牌干燥面双方都没什么牌，小尺度高频能拿到最多弃牌率。",
        "avoid": "别把顶对当坚果打三条街。",
    },
    {
        "when": {"street": "flop", "paired": "1", "role": "进攻"},
        "freq": "下注 45~60%", "size": "25~33% 池",
        "why": "对子面你的范围优势取决于谁有更多明三条；小尺度能保护整个范围，又不用冒太大风险。",
        "avoid": "别在这个面上过度弃牌——对手同样很少击中。",
    },
    {
        "when": {"street": "flop", "suit": "单色面", "role": "进攻"},
        "freq": "下注 35~45%", "size": "50~66% 池",
        "why": "单色面同花听牌集中在对手那边，你的范围优势下降，频率要降、尺度要升。",
        "avoid": "别用 1/3 池小尺度——给了同花听牌太好的价格。",
    },
    {
        "when": {"street": "flop", "oline": "XR", "role": "防守"},
        "freq": "弃牌 80%+", "size": "只留两对以上和强听牌",
        "why": "翻牌被过牌加注，对手的范围高度两极化（暗三条/两对 + 纯诈唬）。你的顶对弱踢基本是弃牌。",
        "avoid": "别用「他可能是在诈唬」说服自己跟注——这个层级过牌加注的诈唬比例很低。",
    },
    {
        "when": {"street": "flop", "oline": "B", "role": "防守"},
        "freq": "跟注 55~65%", "size": "按 MDF 守，别低于 55%",
        "why": "面对对手的持续下注，你要守住 MDF 下限：1/3 池守 75%，半池守 67%，满池守 50%。",
        "avoid": "别只用「有没有对子」决定——要看自己有没有后门听牌和阻断牌。",
    },
    {
        "when": {"street": "flop", "oline": "X", "role": "防守"},
        "freq": "下注 30~40%（领打）", "size": "50~66% 池",
        "why": "对手过牌说明他的范围封顶，领打（donk/lead）能直接拿走底池，也防止他免费看转牌。",
        "avoid": "别每次过牌都领打——会被加注惩罚。",
    },
    {
        "when": {"street": "turn", "oline": "XR", "role": "防守"},
        "freq": "弃牌 85%+", "size": "只留两对以上",
        "why": "转牌被过牌加注，你的中等强度牌基本没戏，直接弃。",
        "avoid": "别在转牌还想着抓诈唬。",
    },
    {
        "when": {"street": "flop", "role": "防守"},
        "freq": "防守 55~65%", "size": "跟注为主",
        "why": "面对 cbet 的默认防守下限：小尺度（1/3 池）要守到 67% 以上，半池 67%，满池 50%。",
        "avoid": "别只看牌力，先看对手的尺度和他的诈唬比例。",
    },
    {
        "when": {"street": "turn", "runout": "超张", "role": "进攻"},
        "freq": "继续下注 40~50%", "size": "66~75% 池",
        "why": "超张转牌对你的范围更有利（你有更多 Ax/大牌），是继续开第二枪的好时机。",
        "avoid": "别在这里突然变成只下注强牌——对手会轻松弃掉中等牌。",
    },
    {
        "when": {"street": "turn", "runout": "超张", "role": "防守"},
        "freq": "弃牌 45~55%", "size": "只留能扛河牌的牌",
        "why": "超张转牌是对手下注范围最强的时候，中等强度牌该弃就弃——这正是你目前漏钱最多的地方。",
        "avoid": "别用「我跟一手看看河牌」的思路，那是在为对手的下一枪付费。",
    },
    {
        "when": {"street": "turn", "runout": "成花", "role": "进攻"},
        "freq": "继续下注 20~30%", "size": "过牌为主",
        "why": "成花转牌让对手的跟注范围里同花比例上升，你要大幅降低下注频率。",
        "avoid": "别用同花面去诈唬——对手的跟注范围正好被增强了。",
    },
    {
        "when": {"street": "turn", "runout": "公对面", "role": "进攻"},
        "freq": "继续下注 35~45%", "size": "66% 池",
        "why": "公对面降低了双方的范围差距，但你的坚果优势还在；用中等频率+大尺度施压。",
        "avoid": "别在这个面上放弃——对手也很难有明三条。",
    },
    {
        "when": {"street": "turn", "runout": "白板", "role": "进攻"},
        "freq": "继续下注 45~55%", "size": "50~66% 池",
        "why": "白板不改变范围结构，你可以按原本的计划继续下注。",
        "avoid": "别把白板当借口无脑开第二枪，要看翻牌下注的尺度是否合理。",
    },
    {
        "when": {"street": "river", "runout": "超张", "role": "进攻"},
        "freq": "下注 30~40%", "size": "66~100% 池",
        "why": "河牌超张是极化下注的好时机：你要么有强牌，要么是纯空气。",
        "avoid": "别用中等强度做薄价值——被跟注时通常输。",
    },
    {
        "when": {"street": "river", "runout": "成花", "role": "防守"},
        "freq": "弃牌 50~60%", "size": "只抓有阻断牌的诈唬",
        "why": "成花河牌对手的价值范围最集中，你现在的弃牌率只有三成出头，明显偏低。",
        "avoid": "别用「我有对子」当理由跟注，要看自己有没有阻断同花。",
    },
    {
        "when": {"street": "river", "role": "防守"},
        "freq": "按 MDF 下限弃牌", "size": "看尺度和阻断牌",
        "why": "河牌防守的核心是 MDF + 阻断牌：对手下注越大，你的跟注范围越窄。",
        "avoid": "别用固定的「有一对就跟」策略。",
    },
    {
        "when": {"street": "flop", "role": "进攻", "vtype": "松"},
        "freq": "下注 65~75%，其中价值更多", "size": "50~66% 池",
        "why": "松的对手跟注太宽，诈唬没用——把尺度放大、把价值牌打足。",
        "avoid": "别对他做多街诈唬，他几乎不弃牌。",
    },
    {
        "when": {"street": "flop", "role": "进攻", "vtype": "紧"},
        "freq": "下注 55~65%，诈唬可以多一点", "size": "25~33% 池",
        "why": "紧的对手弃牌多，小尺度诈唬的收益高；但被跟注时他的范围更强。",
        "avoid": "别对他做薄价值下注。",
    },
    {
        "when": {"street": "flop", "role": "防守", "vtype": "紧"},
        "freq": "弃牌 45~55%", "size": "只跟有后门的牌",
        "why": "紧的对手下注代表强范围，你的边缘牌该弃就弃。",
        "avoid": "别用「他也可能诈唬」安慰自己——紧手很少诈唬。",
    },
    {
        "when": {"street": "flop", "role": "防守", "vtype": "松"},
        "freq": "防守 60~70%", "size": "跟注为主",
        "why": "松的对手下注范围很宽，你的中等牌有摊牌价值，别被吓跑。",
        "avoid": "别过度弃牌，他的下注里有很多空气。",
    },
    {
        "when": {"street": "flop", "role": "进攻"},
        "freq": "下注 55~70%", "size": "33% 池为主",
        "why": "翻牌 cbet 的默认值：范围优势越大频率越高。先按牌面类型调，再用对手倾向微调。",
        "avoid": "别用同一个频率打所有牌面——那是最容易被针对的地方。",
    },
    {
        "when": {"street": "turn", "role": "进攻"},
        "freq": "继续下注 40~50%", "size": "66% 池",
        "why": "转牌第二枪的默认值：比翻牌低一半左右，尺度要大一些，因为底池已经变大。",
        "avoid": "别用翻牌的频率继续打——转牌对手的范围已经变强。",
    },
    {
        "when": {"street": "turn", "role": "防守"},
        "freq": "弃牌 40~50%", "size": "只留能扛河牌的牌",
        "why": "转牌面对下注，中等强度牌要开始做取舍：能扛河牌的跟，扛不住的弃。",
        "avoid": "别用「跟一手看看」的思路，那是在替对手的河牌下注付费。",
    },
    {
        "when": {"street": "river", "role": "进攻"},
        "freq": "下注 30~40%", "size": "66~100% 池",
        "why": "河牌下注要极化：要么强价值，要么纯诈唬，中等强度过牌摊牌。",
        "avoid": "别用中等强度做薄价值，被加注时你几乎必输。",
    },
    {
        "when": {"street": "river", "role": "防守"},
        "freq": "按 MDF 弃牌", "size": "看尺度和阻断牌",
        "why": "河牌防守 = MDF + 阻断牌：对手下注越大，跟注范围越窄。",
        "avoid": "别用「我有一对」当理由。",
    },
    {
        "when": {"street": "flop", "role": "进攻", "pot_type": "3bet底池"},
        "freq": "下注 60~70%", "size": "25~33% 池",
        "why": "3bet 底池 SPR 低，你的范围优势更大，可以用小尺度高频下注，但别到 80%。",
        "avoid": "别在 3bet 池里每手都 cbet——翻牌 miss 率同样高。",
    },
]


def _score(rule: dict, filters: dict) -> int:
    if not rule["when"]:
        return 0
    for k, v in rule["when"].items():
        if str(filters.get(k) or "") != str(v):
            return 0
    return len(rule["when"])


def advice_for(filters: dict, store=None) -> dict | None:
    # 先看从课程笔记里抽出来的规则
    if store is not None:
        row = store.match_note_rule(filters)
        if row:
            return {
                "freq": row["freq"],
                "size": row["size"],
                "why": row["why"],
                "avoid": row["avoid"],
                "confidence": "来自你的笔记",
                "source": {"title": row["source_title"], "heading": row["source_heading"]},
            }
    best, best_score = None, 0
    for r in RULES:
        sc = _score(r, filters)
        if sc > best_score:
            best, best_score = r, sc
    if not best:
        return None
    return {
        "freq": best["freq"],
        "size": best["size"],
        "why": best["why"],
        "avoid": best["avoid"],
        "matched": best["when"],
        "confidence": "经验规则" if best_score >= 2 else "通用经验",
    }


def presets_for(street: str) -> list[dict]:
    return PRESETS.get(street, PRESETS["flop"])
