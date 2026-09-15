# -*- coding: utf-8 -*-
"""参考文件/设计依据抽取：国标、行标、规范、安全参考书与文献等。

来源：
  1. 章节标题含“依据/标准/规范/参考/文献/引用”的小节，逐条收集其内容行；
  2. 全文扫描形如《…》、GB/T xxxx、GB xxxx、HG/T、SH/T、JB/T、AQ、ISO、IEC、
     “标准/规范/手册/导则/指南/教材”的行。
输出：[{text, type, section, line}]
"""
import re

HEAD_KW = ["设计依据", "依据", "标准", "规范", "参考", "文献", "引用", "采用的标准"]
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[\.、)]|[（(]\d+[）)])\s*")

STD_RE = re.compile(r"(GB\s*/?\s*T?\s*\d|HG\s*/?\s*T?\s*\d|SH\s*/?\s*T?\s*\d|JB\s*/?\s*T?\s*\d|"
                    r"AQ\s*/?\s*\d|ISO\s*\d|IEC\s*\d|EN\s*\d|API\s*\d)", re.I)
BOOK_RE = re.compile(r"手册|教材|导则|指南|白皮书|百科全书|技术全书|实用|设计手册")
NORM_RE = re.compile(r"标准|规范|规程|规定|条例|办法")
BOOKTITLE_RE = re.compile(r"《[^》]{2,60}》")


def _clean(s):
    s = BULLET.sub("", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def _classify(text):
    if STD_RE.search(text):
        return "标准/规范"
    if BOOK_RE.search(text):
        return "参考书/手册"
    if NORM_RE.search(text) or BOOKTITLE_RE.search(text):
        return "规范/文献"
    return "其他依据"


def extract_references(text: str):
    lines = text.splitlines()
    refs = []
    seen = set()
    texts = set()          # 已收录文本（含小节里已整条收录的句子）

    def add(raw, section, lineno):
        t = _clean(raw)
        if not t or len(t) < 4 or len(t) > 240:
            return
        if t.startswith(("#", "|")):
            return
        key = re.sub(r"[《》\s]", "", t)
        if key in seen:
            return
        seen.add(key)
        texts.add(t)
        refs.append({"text": t, "type": _classify(t), "section": section, "line": lineno})

    # 1) 依据类小节
    cur_sec = ""
    in_sec = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            cur_sec = m.group(2).strip()
            in_sec = any(k in cur_sec for k in HEAD_KW)
            continue
        if not s:
            continue
        if in_sec and not s.startswith(("|", "```")):
            add(s, cur_sec, i + 1)

    # 2) 全文扫描标准号 / 书名号 / 规范手册词（已在小节整条收录的行不再重复）
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith(("|", "```", "![")):
            continue
        if _clean(s) in texts:
            continue
        if STD_RE.search(s) or (BOOKTITLE_RE.search(s) and ("标准" in s or "规范" in s or "手册" in s or "依据" in s)) \
                or (("手册" in s or "导则" in s or "指南" in s) and ("安全" in s or "设计" in s)):
            titles = BOOKTITLE_RE.findall(s)
            stds = re.findall(r"(?:GB|HG|SH|JB|AQ|ISO|IEC)\s*/?\s*T?\s*\d+[\.\-—\d]*", s, re.I)
            if titles or stds:
                for t in titles + stds:
                    add(t, "全文扫描", i + 1)
            else:
                add(s, "全文扫描", i + 1)

    # 排序：标准/规范 → 规范/文献 → 参考书/手册 → 其他；同类按出现顺序
    order = {"标准/规范": 0, "规范/文献": 1, "参考书/手册": 2, "其他依据": 3}
    refs.sort(key=lambda r: (order.get(r["type"], 9), r["line"]))
    return refs
