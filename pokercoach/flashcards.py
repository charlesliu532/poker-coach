"""从结构化笔记自动生成复习卡。

这一版的原则：**宁缺毋滥**。上一版靠"冒号左边就是术语"抽卡，出了大量
「关键决策」「频率：提升至 ____」这种碎片。现在加了三道硬门槛：

1. 术语必须是真术语：带英文/括号，或在白名单里；纯中文长句一律拒绝
2. 答案必须是完整释义：不能是列表残片、不能是一串牌名、不能超过两句
3. 题干必须自洽：不能是"频率：____"这种没有主语的标签

抽不出来就不抽。卡片少了可以补，烂卡会毁掉复习队列。
"""

from __future__ import annotations

import hashlib
import re

# 冒号左边出现这些词，说明是行文提示或章节名，不是术语
_TEMPLATE_WORDS = {
    "例如", "比如", "表现", "推演", "作用", "目的", "说明", "场景", "注意", "前提",
    "原因", "结果", "方法", "步骤", "对比", "总结", "补充", "提示", "背景", "定义",
    "概念", "要点", "结论", "原则", "问题", "答案", "举例", "案例", "分析", "建议",
    "做法", "处理", "应对", "策略", "关键", "核心", "重点", "区别", "优势", "劣势",
    "子页面", "实战调整", "教材视图", "方法论", "评估", "框架", "应用", "小结",
    "本节", "本章", "课程", "目录", "前言", "回顾", "补充说明", "注意事项", "作业",
    "导言", "引言", "概述", "新模式", "旧模式", "示例", "关键决策", "主要问题",
    "具体", "给出", "分配", "频率", "尺度", "决策", "思路", "逻辑", "基础",
    "重要性", "影响", "意义", "效果", "特点", "优点", "缺点", "常见问题", "误区", "纠偏",
}

# 纯中文但确实是扑克术语的，才允许没有英文
_ZH_TERMS = {
    "阻断牌", "极化", "范围优势", "坚果优势", "最小防守频率", "持续下注", "过牌加注",
    "挤压", "诈唬", "价值下注", "胜率", "权益", "底池赔率", "隐含赔率", "剥削", "平衡",
    "范围", "位置", "半诈唬", "薄价值", "抓诈唬", "超额下注", "跟注站", "翻前",
}

_CLAUSE_WORDS = (
    "显示", "表示", "说明", "认为", "需要", "应该", "可以", "必须", "基于", "通过",
    "根据", "如果", "因为", "所以", "由于", "并且", "而且", "但是", "不过", "这样",
    "上述", "以下", "此时", "然后", "因此", "即", "则", "就", "都", "很", "更", "把",
    "被", "让", "使", "对",
)

_DEF_RE = re.compile(r"^[-*]\s*(?P<left>[^：:\n]{2,28})[：:]\s*(?P<right>.{12,240})$")
_PAREN_RE = re.compile(r"^(?P<zh>[^（(]{1,24})[（(](?P<en>[^）)]{1,40})[)）]\s*$")
_NUM_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?\s*(?:%|％|bb|BB|倍))")
_PRIN_RE = re.compile(r"^[-*]\s*(?:原则|结论|记住|要点|一句话)\s*[：:]\s*(?P<body>.{10,220})$")
_LABEL_STEM = re.compile(r"^(?:频率|尺度|结论|原则|要点|注意|说明|结果|原因|方法|步骤)\s*[：:]")
_EN = re.compile(r"[A-Za-z]{3,}")
_HANDLIST_RE = re.compile(r"^(?:[2-9TJQKA]{2}[so]?[\s,，、]*)+$")

_MIN_BACK, _MAX_BACK = 15, 200
_MIN_FRONT, _MAX_FRONT = 8, 90


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s or "").lower()


def card_key(front: str) -> str:
    return hashlib.sha1(_norm(front).encode("utf-8")).hexdigest()[:16]


def _clean_term(left: str) -> str | None:
    term = left.strip(" -·•*")
    if not 2 <= len(term) <= 18:
        return None
    if term in _TEMPLATE_WORDS:
        return None
    if any(ch in term for ch in "，。；、！？|[]“”\"'"):
        return None
    if any(ch in term for ch in "和与或及"):
        return None  # 「UNBLOCK空气牌和A高」这种是短语，不是术语
    if any(part in term for part in ("的", "是", "时", "后", "前", "了", "吗", "呢")):
        return None
    if any(w in term for w in _CLAUSE_WORDS):
        return None
    if any(p in term for p in _TEMPLATE_WORDS) and "（" not in term:
        return None
    if re.search(r"\d", term) and not _EN.search(term):
        return None  # 「4级（绿）」这类分级标签不是概念

    has_en = bool(_EN.search(term))
    has_paren = "（" in term or "(" in term
    if not has_en and not has_paren and term not in _ZH_TERMS:
        return None
    return term


def _good_answer(back: str) -> bool:
    if not (_MIN_BACK <= len(back) <= _MAX_BACK):
        return False
    if back.startswith(("例如", "比如", "见", "同上", "-", "•", "*")):
        return False
    if "|" in back or " - " in back or back.count("。") > 2:
        return False
    if back.count("：") >= 2:
        return False
    if _HANDLIST_RE.match(back.replace(" ", "")):
        return False
    if re.match(r"^[2-9TJQKA][shdc]", back):
        return False
    if re.search(r"\[\s*\]|【\s*】", back):
        return False
    # 真定义通常带判断词；纯描述片段（"包括强牌…""强极化范围…"）挡掉
    if not re.search(r"(是|指|表示|意味|代表|属于|用来|用于|即|称为|叫做)", back):
        return False
    return True


def _def_cards(text: str, heading: str, limit: int) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = _DEF_RE.match(line.strip())
        if not m:
            continue
        term = _clean_term(m.group("left"))
        if not term:
            continue
        back = m.group("right").strip()
        if not _good_answer(back):
            continue
        pm = _PAREN_RE.match(term)
        asked = f"{pm.group('zh')}（{pm.group('en')}）" if pm else term
        out.append({"front": f"「{asked}」是什么意思？", "back": back, "kind": "def", "tags": heading})
        if len(out) >= limit:
            break
    return out


def _number_cards(text: str, heading: str, limit: int) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 24 or len(line) > 140:
            continue
        if line.startswith(("- 例如", "- 比如", "例如", "比如")):
            continue
        if re.search(r"\[\s*\]|【\s*】", line):
            continue
        body = line.lstrip("-* ").strip()
        if _LABEL_STEM.match(body):
            continue  # 「频率：____」这种没有主语的标签
        # 开头就是「前注阶段：」「筹码深度:」这种标签 → 不是完整句子
        if re.search(r"[：:]", body[:10]):
            continue
        if not _EN.search(body) and "。" not in body:
            continue  # 至少得有英文术语或一个完整句子
        nums = _NUM_RE.findall(body)
        if len(nums) != 1:
            continue
        blanked = _NUM_RE.sub("____", body, count=1)
        if blanked.count("____") != 1 or len(blanked) < 18:
            continue
        if blanked.index("____") < 10:
            continue  # 句子一开始就挖空，等于没有上下文
        # 必须是完整句子：以「。！？）」结尾，不能是"……如下："这种引出列表的半句
        if not re.search(r"[。！？）」)]$", blanked):
            continue
        if any(w in blanked[-12:] for w in ("如下", "以下", "包括", "分别是")):
            continue
        out.append({"front": blanked, "back": nums[0].strip(), "kind": "num", "tags": heading})
        if len(out) >= limit:
            break
    return out


def _principle_cards(text: str, heading: str, limit: int) -> list[dict]:
    short = (heading or "").split(" / ")[-1].strip()
    if not short or len(short) > 40 or any(w in short for w in ("目录", "FAQ", "前言", "概览")):
        return []
    for line in text.splitlines():
        m = _PRIN_RE.match(line.strip())
        if not m:
            continue
        body = m.group("body").strip()
        if not _good_answer(body):
            continue
        return [
            {
                "front": f"《{short}》里最重要的结论是什么？",
                "back": body,
                "kind": "principle",
                "tags": heading,
            }
        ]
    return []


_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_SKIP_LINE = ("[视频]", "[图片]", "子页面", "视频：", "图片：", "附件：")


def _clean_text(text: str) -> str:
    text = _COMMENT_RE.sub("", text or "")
    keep = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") or "|" in s:
            continue
        if s.startswith(_SKIP_LINE) or ".mp4" in s or "http://" in s or "https://" in s:
            continue
        keep.append(line)
    return "\n".join(keep)


def generate_cards(text: str, heading: str = "", limit: int = 10) -> list[dict]:
    text = _clean_text(text)
    if not text or len(text) < 40:
        return []
    pool = (
        _def_cards(text, heading, limit)
        + _number_cards(text, heading, limit)
        + _principle_cards(text, heading, limit)
    )
    seen, out = set(), []
    for c in pool:
        key = _norm(c["front"])
        if not key or key in seen:
            continue
        if not (_MIN_FRONT <= len(c["front"]) <= _MAX_FRONT):
            continue
        if _norm(c["back"]) in key:
            continue
        seen.add(key)
        c["key"] = card_key(c["front"])
        out.append(c)
        if len(out) >= limit:
            break
    return out


def merge_cards(cards: list[dict], limit: int = 14) -> list[dict]:
    seen, out = set(), []
    for c in cards:
        k = c.get("key") or card_key(c["front"])
        if k in seen:
            continue
        seen.add(k)
        c["key"] = k
        out.append(c)
        if len(out) >= limit:
            return out
    return out
