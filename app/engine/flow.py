# -*- coding: utf-8 -*-
"""工序流程图抽取（数据驱动、初筛级）。

思路：
  1. 主工序名优先取自“风险场景表”的工序列（出现顺序≈主流程顺序）；
     若没有，则回退到文档标题中含“工段/工序/单元”的词，按出现顺序取；
  2. 含 储/罐/压缩/火炬/废水/废气/公用/冷冻 等 → 辅助节点（不进主链）；
  3. 每条工序从文档就近提取“工作内容”描述句；
  4. 条目归属：item 的 unit/source/title 含工序名 → 关联（写回 item.unit_node）；
  5. 相邻主工序连线；检测“循环/回用/返回”字样 → 追加一条虚线回流边（启发式）。

输出：{nodes:[{id,name,type(main/aux),desc,risk,item_ids,scene_ids}],
       edges:[{from,to,label,dashed}], note}
"""
import re

AUX_KW = ["储罐", "罐区", "压缩", "火炬", "公用", "废水", "废气", "三废", "冷冻",
          "空压", "蒸汽", "循环水", "膜分离", "吸附", "回收", "污水", "消防",
          "除尘", "吸收", "动力", "制冷", "净水", "中和"]
MAIN_ORDER_HINT = ["合成", "分离", "反应", "氢氰化", "异构化", "精制", "提纯",
                   "浓缩", "回收", "配制"]
CONTENT_KW = ["反应", "温度", "压力", "转化", "精制", "合成", "进料", "产出",
              "催化", "精馏", "搅拌", "循环", "分离", "收率", "氢氰化", "异构"]

# 工序/区域命名体系（兼容“××工序”与“××区域/工位/岗位”两种工艺包写法）
INLINE_UNIT_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9（）()]{2,12}(?:工序|工段|工位|岗位|作业区|区域))")
_TITLE_UNIT_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9()（）]{2,14}?(?:工段|工序|单元))")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[\.、)]|（\d+）|\(\d+\))\s*")
_BAD_UNIT_RE = re.compile(r"[与及和等、,，；;]")

# 同义工序名归并：去掉括号内容与“工序/岗位/区域”等后缀后的核心名相同 → 视为同一节点。
# 例：“合成（络合沉淀）工序”与“合成岗位”、“结晶工序”与“结晶岗位”。
_UNIT_SUFFIXES = ("作业区", "工段", "工序", "工位", "岗位", "区域", "单元", "车间", "场所")
_BRACKET_RE = re.compile(r"[（(][^）)]*[）)]")
# 全厂/全装置类通用单元：仍保留条目的 unit 归属，但不作为流程节点（避免出现“全装置”这种伪节点）
GENERIC_UNITS = {"全装置", "全厂", "全公司", "通用", "其他", "其它"}


def _unit_core(nm: str) -> str:
    """取“核心工序名”：去掉括号内容与 工序/岗位/区域 等后缀，用于同义归并。"""
    s = _BRACKET_RE.sub("", str(nm or ""))
    for suf in _UNIT_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            s = s[:-len(suf)]
            break
    return s.strip()


def _clean_unit(nm) -> str:
    return re.sub(r"\s+", "", str(nm or "")).strip("*_`#-— ")


def _bad_unit(nm: str, trusted: bool = False) -> bool:
    """过滤占位符与明显不是工序名的候选（如“（风险场景表）”）。

    trusted=True 表示来自结构化来源（风险表工序列 / “××工序：”定义行 / 标题），
    此时不做“与/及/和”启发式过滤，避免误杀“除尘与废药处理工序”这类合法名称。
    """
    if not nm or len(nm) < 2 or len(nm) > 14:
        return True
    if nm.startswith(("（", "(")) or nm.endswith("表）"):
        return True
    if any(k in nm for k in ("风险场景表", "未标注单元", "全文", "通用")):
        return True
    if trusted:
        return False
    core = nm[:-2] if nm.endswith(("工序", "工段")) else nm
    if _BAD_UNIT_RE.search(core):
        return True
    return False


def _is_def_line(text: str, names: list) -> bool:
    """该行是否为某个候选工序名的“定义行”（行首即工序名且后接冒号/逗号/句号）。"""
    t = _BULLET_RE.sub("", text)
    return any(t.startswith(o) and t[len(o):len(o) + 1] in ("：", ":", "，", ",", "。")
               for o in names if o and len(o) >= 2)


def _unit_pos(name: str, lines: list, names: list | None = None) -> int:
    """候选名的“定义位置”：优先“列表项/段落首且后接冒号”的行，其次标题行，最后首次出现行。

    注意：形如“定员：合成岗位 ≤2 人；干燥筛分岗位 ≤1 人；装盒岗位…”的**并列叙述行**会把工序名
    误拉到文档很前面，导致流程图顺序错乱；此类“非定义行且并列提及≥2 个候选名”的行不计入位置。
    """
    pool = [n for n in (names or [name]) if n and len(n) >= 2]
    first = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or name not in s:
            continue
        s2 = _BULLET_RE.sub("", s)
        if s2.startswith(name) and s2[len(name):len(name) + 1] in ("：", ":", "，", ",", "。"):
            return i
        if s.startswith("#"):
            return i
        if not _is_def_line(s, pool) and sum(1 for o in pool if o in s) >= 2:
            continue          # 并列叙述行（定员/装置一览等），不作为工序定义位置
        if first is None:
            first = i
    return first if first is not None else 10 ** 6


def _lines(text: str):
    return text.splitlines()


def find_name_lines(text: str, name: str):
    """返回文本中所有包含 name 的行号（避免子串过短误伤）。"""
    if len(name) < 2:
        return []
    return [i for i, ln in enumerate(_lines(text)) if name in ln]


def extract_desc(text: str, name: str, other_names: list, max_sent=5, max_chars=420) -> str:
    """就近抽取工序工作内容：取首个出现行，向后收集内容句直到碰到其他工序名行。"""
    lines = _lines(text)
    starts = find_name_lines(text, name)
    if not starts:
        return ""
    start = starts[0]
    out = []
    seen = set()
    # 向后收集（限制行数避免串段）
    for j in range(start, min(len(lines), start + 220)):
        ln = lines[j].strip()
        if not ln:
            continue
        if ln.startswith(("#", "|", "```", "!")):
            # 表格行跳过；标题若属于别的工段则停
            if ln.startswith("#"):
                if any(o in ln for o in other_names):
                    break
                continue
            if ln.startswith("|"):
                continue
        if any(o in ln for o in other_names if o != name and o):
            # 遇到下一个工序名（较独特时）停止收集
            if len([o for o in other_names if o and o in ln and o != name]) >= 1:
                if len(out) >= 1:
                    break
        # 只保留“内容性”句子
        if any(k in ln for k in CONTENT_KW):
            sents = re.split(r"[。；;]", ln)
            for s in sents:
                s = s.strip()
                if not s or len(s) > 120:
                    continue
                if s not in seen and any(k in s for k in CONTENT_KW):
                    seen.add(s)
                    out.append(s)
        if len(out) >= max_sent:
            break
        # 遇到非内容且已收集到内容时，若连空/纯标题多行则停
    res = "；".join(out)
    return (res[:max_chars] + "…") if len(res) > max_chars else res


def build_process_flow(text: str, items: list, scene_units: list | None = None) -> dict:
    lines_all = _lines(text)
    cand = []
    trusted = set()

    def add(nm, trust=False):
        nm = _clean_unit(nm)
        if nm in GENERIC_UNITS:          # 全厂/全装置类通用名不进流程节点
            return
        if nm and nm not in cand:
            cand.append(nm)
        if nm and trust:
            trusted.add(nm)

    # 1) 主来源：风险场景表的“工序/区域/岗位”列（保文档原序，结构化→可信）
    for u in (scene_units or []):
        add(u, True)
    # 2) 回退：条目所属单元（来自标题层级→可信）
    if not cand:
        for it in items:
            if it.get("category") in ("综合场景", "工艺工况"):
                add(it.get("unit"), True)
    # 3) 补充：“××工序：…”类定义行（工艺流程简述）与标题中的“工段/工序/单元”
    for ln in lines_all:
        s = ln.strip()
        if not s or s.startswith(("|", "![", "```", ">")):
            continue
        s2 = _BULLET_RE.sub("", s)
        m = INLINE_UNIT_RE.match(s2)
        if m and s2[len(m.group(1)):len(m.group(1)) + 1] in ("：", ":", "，", ","):
            add(m.group(1), True)
        elif s.startswith("#"):
            mt = _TITLE_UNIT_RE.search(s)
            if mt and mt.start() <= 40:
                add(mt.group(0))

    # 过滤占位符/伪节点，并按“定义位置”排序（修复主链顺序与文档原序不一致）
    cand = [nm for nm in cand if not _bad_unit(nm, nm in trusted)]
    # 注意：list.sort 排序期间原列表会被 CPython 临时清空，key 闭包必须用快照，否则读到空列表
    cand_pool = list(cand)
    cand.sort(key=lambda nm: _unit_pos(nm, lines_all, cand_pool))

    # 同义工序名归并：核心名相同者只保留“文档中先定义”的那一个，其余记为别名（仍用于条目归属）
    core2name, kept, alias = {}, [], {}
    for nm in cand:
        core = _unit_core(nm)
        if core and core in core2name:
            alias[nm] = core2name[core]
            continue
        if core:
            core2name[core] = nm
        kept.append(nm)
    cand = kept
    alias_by_node = {}
    for _a, _k in alias.items():
        alias_by_node.setdefault(_k, []).append(_a)

    truncated_nodes = len(cand) > 24
    node_names = cand[:24]

    # 4) 辅工序判定 + 建节点（保持原顺序）
    main_names, aux_names = [], []
    for nm in node_names:
        (aux_names if any(k in nm for k in AUX_KW) else main_names).append(nm)
    # 去掉过长的噪音名称
    main_names = [nm for nm in main_names if len(nm) <= 14][:16]
    aux_names = [nm for nm in aux_names if len(nm) <= 14][:8]

    nodes, edges = [], []
    all_names = main_names + aux_names
    item_to_node = {}
    for nm in main_names + aux_names:
        nid = f"f{len(nodes) + 1:02d}"
        nm_alias = alias_by_node.get(nm, [])
        rel = [it for it in items
               if _match(it, nm) or any(_match(it, a) for a in nm_alias)]
        risk = _max_severity(rel)
        desc = extract_desc(text, nm, [o for o in all_names if o != nm])
        nodes.append({
            "id": nid, "name": nm, "type": "main" if nm in main_names else "aux",
            "aliases": nm_alias,
            "desc": desc or "（未在文档中定位到该工序的描述段，请人工补充/校核）",
            "risk": risk, "n_items": len(rel),
            "item_ids": [it["id"] for it in rel][:30],
            "scene_ids": [it["id"] for it in rel if it.get("category") in ("综合场景", "工艺工况")][:12],
        })
        for it in rel:
            item_to_node[it["id"]] = nm

    # 主链边
    for a, b in zip(main_names[:-1], main_names[1:]):
        edges.append({"from": _nid(nodes, a), "to": _nid(nodes, b),
                      "label": "", "dashed": False})
    # 回流启发式
    lines_all = _lines(text)
    recycle = [ln for ln in lines_all if re.search(r"循环|回用|返回|回流|重复利用", ln)]
    if recycle and len(main_names) >= 2:
        target = None
        for ln in recycle[:20]:
            for nm in all_names:
                if nm and len(nm) >= 2 and nm in ln:
                    target = nm
                    break
            if target:
                break
        if not target:
            for nm in main_names:
                if any(k in nm for k in ("氢氰化", "反应", "合成")):
                    target = nm
                    break
        if target:
            edges.append({"from": _nid(nodes, main_names[-1]), "to": _nid(nodes, target),
                          "label": "循环/回用", "dashed": True})

    note = ("工序图由文档自动抽取（主链按文档首次定义位置排序、辅助节点单列、回流边为启发式），"
            "已自动折行排版无需左右拖动；仅供流程概览与风险定位，正式流程图请以工艺包 PFD/P&ID 为准。")
    if truncated_nodes:
        note += f"（候选工序较多，已按前 24 个建图，共识别 {len(cand)} 个候选）"

    # ---- 工序间物料/风险传递（供故障树体现“前工序→后工序”的影响） ----
    material_names = []
    for it in items:
        if it.get("category") == "物料":
            nm = (it.get("title") or "").split("：", 1)[-1].strip()
            if nm and nm not in material_names:
                material_names.append(nm)
    by_name = {n["name"]: n for n in nodes}
    sev_order = {"极高": 0, "高": 1, "中": 2, "低": 3, "待定": 4}
    lines_all = _lines(text)

    def _events_of(nm, cap=3):
        """该工序的风险场景条目（用 item_to_node 归属，避免依赖 unit_node 赋值时机）。"""
        rel = [it for it in items if item_to_node.get(it.get("id")) == nm
               and it.get("category") in ("综合场景", "工艺工况")]
        rel.sort(key=lambda x: sev_order.get(x.get("severity"), 9))
        return [{"id": it["id"], "title": it.get("title"), "severity": it.get("severity")}
                for it in rel[:cap]]

    def _block_text(nm, others):
        """该工序名首次出现后、到下一个工序名之前的整段文本（含表格行），用于推断物料。"""
        starts = find_name_lines(text, nm)
        if not starts:
            return nm
        start = starts[0]
        out = []
        for j in range(start, min(len(lines_all), start + 60)):
            ln = lines_all[j].strip()
            if not ln:
                continue
            if j > start and any(o in ln for o in others if o and o != nm and len(o) >= 2):
                break
            out.append(ln)
            if sum(len(x) for x in out) > 1600:
                break
        return " ".join(out)

    cross_links = []
    for a, b in zip(main_names, main_names[1:]):
        others = all_names
        ta = _block_text(a, others) + " " + a
        tb = _block_text(b, others) + " " + b
        via = [m for m in material_names if m in ta and m in tb][:3]
        if not via:   # 回退：取上游工序段中出现的物料（其产物/中间物）
            via = [m for m in material_names if m in ta][:2]
        if not via:   # 再回退：取下游工序段中的物料
            via = [m for m in material_names if m in tb][:2]
        via_txt = "、".join(via) if via else "中间物料/在制品"
        evs = _events_of(a)
        cross_links.append({
            "from": a, "to": b, "via": via_txt,
            "upstream_events": evs,
            "note": (f"若「{a}」的上述事件未受控，可能随【{via_txt}】带入「{b}」，"
                     f"导致后工序输入异常、负荷/配比偏离或杂质/敏感物引入，形成工序间故障传播。"
                     + ("" if evs else "（该工序暂无可关联风险场景，建议人工补充）")),
        })

    return {
        "nodes": nodes, "edges": edges, "note": note,
        "cross_links": cross_links,
        "item_to_node": item_to_node,
    }


def _match(it: dict, name: str) -> bool:
    if len(name) < 2:
        return False
    blob = (f"{it.get('unit') or ''} {it.get('source') or ''} {it.get('title') or ''} "
            f"{it.get('factor_desc') or ''} {it.get('trigger_path') or ''} "
            f"{it.get('consequence') or ''}")
    return name in blob


def _nid(nodes, name):
    for n in nodes:
        if n["name"] == name:
            return n["id"]
    return ""


def _max_severity(rel):
    order = {"极高": 0, "高": 1, "中": 2, "低": 3, "待定": 4}
    best = None
    for it in rel:
        s = it.get("severity")
        if s in order:
            if best is None or order[s] < order[best]:
                best = s
    return best or "待定"
