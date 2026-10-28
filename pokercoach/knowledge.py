"""知识库索引：按扑克逻辑重新组织（不是按文件夹）。

每个概念挂两类东西：
  1. 你笔记里对应的原文（点开就能看）
  2. 对应的关卡 / 卡片主题（去复习、去练习）
"""

from __future__ import annotations

# 学习分区：先学什么、再练什么
ZONES = [
    {"key": "learn", "name": "学", "desc": "知识点与卡片复习", "tabs": ["cards", "plan"]},
    {"key": "drill", "name": "练", "desc": "闯关与场景练习", "tabs": ["campaign"]},
    {"key": "play", "name": "战", "desc": "模拟牌桌实战", "tabs": ["sim"]},
    {"key": "analyze", "name": "析", "desc": "翻后数据与手牌复盘", "tabs": ["post", "review"]},
    {"key": "ask", "name": "问", "desc": "对着自己的笔记提问", "tabs": ["ask"]},
]

def summary(docs: int = 0, concepts: int = 0, zones: int = 0, leak: float | None = None) -> str:
    """按当前库存动态生成，不要再写死数字。"""
    d = f"{docs} 篇笔记" if docs else "你的笔记"
    leak_txt = (
        f"这也解释了为什么你在「弃给 cbet {leak:.1f}%（基准 38–56%）」这种基础指标上会漏，"
        if leak is not None else "这也解释了为什么基础指标上会漏，"
    )
    return f"""你的资料库有个很明显的特点：**剥削和多人底池的部分非常厚，基础的部分反而薄**。
{d}里，讲「怎么针对某种玩家/某种池型调整」的内容占了大头，
而「底池赔率、EV、翻前范围表」这类地基相对少——{leak_txt}而不是在高级剥削上。

建议的顺序不是从第一篇读到最后一篇，而是：

1. **先补地基**（翻前范围 + 赔率/EV）——你的漏洞在基础层，不在高级层
2. **再练牌面识别**（牌面结构 → 范围优势 → cbet 频率）
3. **然后才是剥削**（玩家类型、池型调整）——这块你的资料最厚，但要先把前两层立住
4. **最后做统计复盘**（翻后页 + 手牌库），用数据验证有没有改对

下面按这个逻辑把知识库拆成了 {zones or '若干'} 个区、{concepts or '若干'} 个概念。每个概念都连着你的原文和对应的练习。
"""



# 概念 -> (检索词, 所属关卡)
OUTLINE: list[dict] = [
    {
        "zone": "一、翻前",
        "desc": "所有决策的起点：范围宽度、位置、加注尺度",
        "concepts": [
            {"name": "位置与开池宽度", "keys": "位置 开池范围 RFI 宽度", "level": 1},
            {"name": "面对开池：跟注 / 3bet / 弃牌", "keys": "对抗率先加注 跟注 3bet 防守", "level": 2},
            {"name": "3bet 的构成与尺度", "keys": "3bet 三次加注 尺度 线性 极化", "level": 2},
            {"name": "4bet 与全下", "keys": "4bet 四次加注 全下 短筹码", "level": 2},
            {"name": "盲注战（SB vs BB）", "keys": "盲注战 BvB 小盲 大盲 limp", "level": 1},
            {"name": "抽水对翻前的影响", "keys": "抽水 rake 高抽水 翻前策略", "level": 1},
        ],
    },
    {
        "zone": "二、翻牌",
        "desc": "牌面结构决定一切：谁有范围优势、谁有坚果优势",
        "concepts": [
            {"name": "牌面结构与范围优势", "keys": "牌面结构 范围优势 board texture", "level": 3},
            {"name": "持续下注（cbet）的频率与尺度", "keys": "cbet 持续下注 尺度 频率", "level": 3},
            {"name": "面对 cbet 的防守", "keys": "防守 cbet 跟注 弃牌 MDF", "level": 3},
            {"name": "过牌加注（check-raise）", "keys": "过牌加注 check raise 加注 范围", "level": 3},
            {"name": "单色面 / 连牌面的特殊处理", "keys": "单色 双花 连牌 顺子面", "level": 3},
        ],
    },
    {
        "zone": "三、转牌",
        "desc": "第二枪、放弃、以及什么时候该弃牌",
        "concepts": [
            {"name": "第二枪（double barrel）", "keys": "第二枪 double barrel 转牌 下注", "level": 4},
            {"name": "超张转牌的处理", "keys": "超张 转牌 overcard 弃牌", "level": 4},
            {"name": "成花/成顺转牌的降频", "keys": "成花 成顺 转牌 降低频率", "level": 4},
            {"name": "探测下注（probe）", "keys": "探测 probe 转牌 领打", "level": 4},
        ],
    },
    {
        "zone": "四、河牌",
        "desc": "价值、诈唬、抓诈唬——最贵的决策都在这里",
        "concepts": [
            {"name": "价值下注与薄价值", "keys": "价值下注 薄价值 河牌 尺度", "level": 5},
            {"name": "诈唬与极化", "keys": "诈唬 极化 bluff 河牌", "level": 5},
            {"name": "抓诈唬与 MDF", "keys": "抓诈唬 MDF 最小防守频率", "level": 5},
            {"name": "阻断牌（blocker）", "keys": "阻断牌 blocker 阻断效应", "level": 5},
            {"name": "超池下注（overbet）", "keys": "超池 overbet 河牌 极化", "level": 5},
        ],
    },
    {
        "zone": "五、多人底池",
        "desc": "三个以上玩家，所有频率都要重算",
        "concepts": [
            {"name": "多人底池的翻前策略", "keys": "多人底池 multiway 翻前 挤压", "level": 6},
            {"name": "多人底池的持续下注", "keys": "多人底池 cbet 持续下注 频率", "level": 6},
            {"name": "多人底池的防守", "keys": "多人底池 防守 跟注 范围", "level": 6},
        ],
    },
    {
        "zone": "六、剥削与调整",
        "desc": "你的资料最厚的一块——但要用在前两层立住之后",
        "concepts": [
            {"name": "玩家类型：紧 / 松 / 跟注站", "keys": "玩家类型 紧型 松型 跟注站 极端", "level": 7},
            {"name": "剥削范围的来源", "keys": "剥削范围 玩家池 population exploit", "level": 7},
            {"name": "HUD 数据与样本", "keys": "HUD 数据 VPIP PFR 样本", "level": 7},
            {"name": "什么时候不该剥削", "keys": "不该剥削 反制 被剥削 counter", "level": 7},
        ],
    },
    {
        "zone": "七、心态与资金",
        "desc": "打得久比打得好更重要",
        "concepts": [
            {"name": "A-Game 与状态管理", "keys": "A-Game 心态 状态 tilt", "level": 8},
            {"name": "资金管理", "keys": "资金管理 bankroll 级别", "level": 8},
        ],
    },
    {
        "zone": "八、基础（容易被跳过）",
        "desc": "赔率、EV、组合数——你漏钱的地方往往在这",
        "concepts": [
            {"name": "底池赔率与需要的胜率", "keys": "底池赔率 pot odds 需要胜率", "level": 1},
            {"name": "MDF 与 alpha", "keys": "MDF alpha 弃牌率 诈唬", "level": 5},
            {"name": "EV 与权益实现（EQR）", "keys": "EV 权益实现 EQR equity", "level": 1},
        ],
    },
]


def build_index(search_fn, limit: int = 2) -> list[dict]:
    """给每个概念挂上笔记原文。"""
    out = []
    for block in OUTLINE:
        concepts = []
        for c in block["concepts"]:
            hits = search_fn(c["keys"], limit)
            concepts.append(
                {
                    "name": c["name"],
                    "level": c["level"],
                    "hits": [
                        {
                            "title": h["title"],
                            "heading": h["heading"],
                            "preview": h["preview"][:140],
                            "chunk_id": h.get("chunk_id"),
                            "doc_id": h.get("doc_id"),
                        }
                        for h in hits
                    ],
                }
            )
        out.append({"zone": block["zone"], "desc": block["desc"], "concepts": concepts})
    return out
