# -*- coding: utf-8 -*-
"""自动化/机器人辨识：从工艺包中抽取“机器人台账”并生成专属条目与风险因素。

支持两种来源：
  1. 机器人台账表（表头含 机器人 名称 + 负责工序/减少人数 等列）——首选；
  2. 含机器人名称（防爆机器人/桁架机器人/机械手/AGV…）的小节，按“字段：值”行解析（回退）。

输出：
  robots: [{id,name,type,process,task,staff_before,staff_after,staff_reduced,
            proc_risks,[robot_risks],[avoided],[safety],ex_level,evidence,item_ids}]
  items : 每台机器人 1 条辨识条目（category=自动化·机器人），并入主报告参与热力图/流程图。
"""
import re

from .models import PROVENANCE_DOC, make_item

ROBOT_TYPES = ["防爆机器人", "桁架机器人", "辅助机械手", "上下料机械手", "机械手",
               "AGV", "自动导引车", "搬运机器人", "巡检机器人", "协作机器人", "机器人"]

# 机器人“新增/可能引发”的风险线索
ROBOT_RISK_KW = ["失控", "误动作", "碰撞", "撞击", "挤压", "夹持失效", "跌落", "掉落",
                 "温升", "过热", "过载", "卡滞", "松动", "定位偏差", "精度", "通信中断",
                 "断网", "急停", "防爆失效", "静电", "电池", "充电", "倾覆", "超速",
                 "协作", "人机", "安全光幕", "视觉", "失电", "驱动机", "轨迹"]

# 否定语境：明确“未配置/未设置机器人”等表述不得判为机器人风险线索
ROBOT_NEG_RE = re.compile(
    r"未(配置|设置|采用|使用|安装|部署|引入|涉及|含|设|配备|建)| "
    r"无(机器人|机械手|AGV|自动化|相关设备)| "
    r"不(配置|设置|采用|使用|安装|部署|引入|配备)| "
    r"没有(机器人|机械手|AGV)|非自动化|不具备自动化|不含(机器人|机械手)")

COL_KEYS = {
    "id": ["编号", "序号", "位号"],
    "name": ["机器人名称", "名称", "设备名称"],
    "type": ["类型", "种类", "类别"],
    "process": ["负责工序", "应用工序", "所在工序", "工序"],
    "task": ["工序内容", "工作内容", "作业内容", "职责", "承担任务"],
    "staff_before": ["原操作人数", "原人数", "改造前", "原定员"],
    "staff_after": ["现操作人数", "现人数", "改造后", "现定员"],
    "staff": ["减少人数", "人数", "定员"],
    "proc_risks": ["该工序", "工序主要风险", "原有风险", "工序风险"],
    "robot_risks": ["机器人新增", "机器人可能", "机器人导致", "新增风险", "机器人风险"],
    "avoided": ["避免", "降低", "消除"],
    "safety": ["防爆", "安全要求", "标准", "安全措施", "防护"],
}


# ---------- 基础工具 ----------
def _sep(line):
    return bool(re.match(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$", line)) and "-" in line


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _iter_tables(lines):
    """产出 (start_idx, header_cells, data_rows) —— 连续的管道表块。"""
    i, n = 0, len(lines)
    while i < n:
        if lines[i].strip().startswith("|"):
            start = i
            block = []
            while i < n and lines[i].strip().startswith("|"):
                if not _sep(lines[i]):
                    block.append(lines[i].strip())
                i += 1
            if len(block) >= 2:
                yield start, _cells(block[0]), [_cells(b) for b in block[1:]]
            continue
        i += 1


def _find_col(header, keys):
    for ci, h in enumerate(header):
        for k in keys:
            if k and k in h:
                return ci
    return None


def _split_list(text):
    if not text:
        return []
    parts = re.split(r"[；;、/｜|\n]+", str(text))
    return [p.strip() for p in parts if p.strip() and p.strip() not in ("-", "无", "—")]


def _num(text):
    if text is None:
        return None
    m = re.search(r"(\d+)", str(text))
    return int(m.group(1)) if m else None


# ---------- 主提取 ----------
def extract_robots(text: str, items: list, base_dir: str = None):
    lines = text.splitlines()
    robots = []
    robot_items = []
    used_rows = set()

    for start, header, rows in _iter_tables(lines):
        hj = " ".join(header)
        if "机器人" not in hj and "AGV" not in hj.upper():
            continue
        if not any(k in hj for k in ("工序", "人数", "工作内容", "职责")):
            continue
        cols = {k: _find_col(header, v) for k, v in COL_KEYS.items()}
        if cols["name"] is None or cols["process"] is None:
            continue
        for r in rows:
            def cell(key):
                ci = cols.get(key)
                return r[ci] if (ci is not None and ci < len(r)) else ""
            name = cell("name")
            if not name or "无" == name:
                continue
            process = cell("process")
            if not process:
                continue
            robot = _build_robot(
                name, cell("type"), process, cell("task"),
                _num(cell("staff_before")), _num(cell("staff_after")), _num(cell("staff")),
                cell("proc_risks"), cell("robot_risks"), cell("avoided"), cell("safety"),
                source=f"{process or '机器人'} · 机器人台账表 第{start + 1}行")
            robots.append(robot)
        used_rows.add(start)

    # 回退：按“机器人名称”小节 + 字段行解析
    if not robots:
        robots = _robot_sections(lines)

    # 补充：选型参数 / 选型说明 / 选型图片
    for rb in robots:
        _enrich(rb, lines)

    # 生成辨识条目（每台机器人 1 条）
    for rb in robots:
        rb_item = _robot_item(rb)
        robot_items.append(rb_item)

    # 机器人风险叙述扫描（非表格中含机器人风险关键词的行）
    for idx, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith(("|", "#", "```", "![")):
            continue
        if (any(t in s for t in ROBOT_TYPES) and any(k in s for k in ROBOT_RISK_KW)
                and len(s) <= 400 and not ROBOT_NEG_RE.search(s)):
            robot_items.append(make_item(
                unit=_guess_process(s) or "（自动化装备）",
                category="自动化·机器人",
                title="机器人风险线索：" + s[:36],
                factor_desc=s[:220],
                trigger_path="自动化装备（机器人/机械手/AGV）在运行、协同或维护过程中的失效或误动作",
                consequence="可能造成物料跌落/碰撞摩擦/局部温升/人员伤害，或引发燃爆等次生事故。",
                existing_controls="（按原文 / 机器人安全规范核查）",
                recommendations="落实急停与安全光幕、防爆等级校核、限速与防撞、通信中断安全停车、末端夹持失效保护等。",
                source=f"机器人相关叙述 · 第{idx + 1}行",
                evidence=[s[:220]],
                severity="高" if any(k in s for k in ("失控", "碰撞", "防爆失效", "温升", "跌落")) else "中",
                provenance=PROVENANCE_DOC, confidence="中"))

    return robots, robot_items


def _build_robot(name, rtype, process, task, before, after, reduced_cell,
                 proc_risks, robot_risks, avoided, safety, source=""):
    if before is not None and after is not None:
        reduced = max(0, before - after)
    else:
        reduced = reduced_cell
    ex = ""
    ms = re.search(r"(Ex[\s\w\.\-]{1,20})", f"{safety} {task} {name}")
    if ms:
        ex = ms.group(1).strip()
    # 类型推断
    if not rtype or len(str(rtype)) > 12:
        rtype = next((t for t in ROBOT_TYPES if t in name), "机器人")
    return {
        "id": "",  # 报告层统一编号
        "name": name.strip(),
        "type": (rtype or "").strip(),
        "process": process.strip(),
        "task": (task or "").strip(),
        "staff_before": before, "staff_after": after, "staff_reduced": reduced,
        "proc_risks": _split_list(proc_risks),
        "robot_risks": _split_list(robot_risks),
        "avoided": _split_list(avoided),
        "safety": _split_list(safety),
        "ex_level": ex,
        "source": source,
        "specs": [], "selection": [], "images": [],
        "evidence": [_clip(p) for p in
                     [f"{process}：{task}", proc_risks, robot_risks, avoided, safety] if p],
        "item_ids": [],
    }


def _robot_item(rb):
    proc = "；".join(rb["proc_risks"][:3]) or "（原文未明确）"
    newr = "；".join(rb["robot_risks"][:4]) or "（原文未明确）"
    avoided = "；".join(rb["avoided"][:3])
    staff = ""
    if rb["staff_before"] is not None and rb["staff_after"] is not None:
        staff = f"定员由 {rb['staff_before']} 人减至 {rb['staff_after']} 人（减少 {rb['staff_reduced']} 人）"
    elif rb["staff_reduced"] is not None:
        staff = f"减少操作人数约 {rb['staff_reduced']} 人"
    fac = "\n".join([
        f"【机器人】{rb['name']}（{rb['type']}）负责工序：{rb['process']}",
        f"【工序内容】{rb['task'] or '（原文未明确）'}",
        f"【减少操作人数】{staff or '（原文未明确）'}",
        f"【该工序风险因素】{proc}",
        f"【机器人可能导致的风险】{newr}",
        f"【更改后避免/降低的风险】{avoided or '（原文未明确）'}",
    ])
    return make_item(
        unit=rb["process"],
        category="自动化·机器人",
        title=f"{rb['name']}｜{rb['process']}",
        factor_desc=fac,
        trigger_path=newr,
        consequence="机器人失效/误动作可能造成物料跌落、碰撞摩擦、局部温升或人员伤害，并可能成为点火源。",
        existing_controls="；".join(rb["safety"][:4]) or "（按机器人安全规范核查）",
        recommendations=("校核防爆等级与危险区域匹配、急停/安全光幕与联锁、末端夹持失效保护、"
                         "限速防撞与通信中断安全停车；核定人机协同安全距离与定员。"),
        source=rb.get("source") or "机器人台账",
        evidence=rb.get("evidence", []),
        severity="高" if rb["robot_risks"] else "中",
        provenance=PROVENANCE_DOC, confidence="高",
    )


def _enrich(rb, lines):
    """从文档中补充该机器人的：选型参数(specs)、选型说明(selection)、选型图片(images)。"""
    name, typ = rb.get("name", ""), rb.get("type", "")
    tokens = re.findall(r"[Rr]\d", name)
    if "AGV" in name.upper():
        tokens.append("AGV")
    tokens = [t for t in dict.fromkeys(tokens) if t] or [name]
    ctx = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        hit = (name and name in s) or (typ and typ in s and len(typ) >= 2)
        if hit:
            for j in range(max(0, i - 2), min(len(lines), i + 8)):
                t = lines[j].strip()
                # 遇到下一个标题行（非本工序小节）即停止，避免跨机器人串取
                if j > i and t.startswith("#"):
                    break
                ctx.append(t)

    # 选型参数（键：值）
    specs, seen = [], set()
    spec_keys = ["型号", "负载", "臂展", "重复定位精度", "定位精度", "防护等级", "防爆等级",
                 "IP", "自由度", "轴数", "最大速度", "速度", "夹持力", "通讯", "通信",
                 "电池", "续航", "尺寸", "重量", "功率", "额定"]
    for ln in ctx:
        for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z/]{2,10})\s*[:：]\s*([^，。；;|]{1,42})", ln):
            k, v = m.group(1).strip(), m.group(2).strip()
            if any(sk in k for sk in spec_keys) and (k, v) not in seen:
                seen.add((k, v))
                specs.append({"k": k, "v": v})

    # 选型说明
    selection = []
    for ln in ctx:
        s = ln.strip().lstrip("-*# ").strip()
        if s.startswith(("|", "!", "`")):
            continue
        if 6 <= len(s) <= 240 and any(w in s for w in
                                      ("选型", "型号", "参数", "配置", "精度", "负载",
                                       "防爆等级", "防护等级", "自由度", "安全光幕")):
            if s not in selection:
                selection.append(re.sub(r"\s+", " ", s))

    # 选型图片（markdown 图片，图注/邻近文本/文件名命中该机器人）
    images = []
    for i, ln in enumerate(lines):
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", ln.strip())
        if not m:
            continue
        cap, path = m.group(1) or "", m.group(2)
        hit = any(tk and (tk in cap or tk in path) for tk in tokens)
        if hit and (cap or path):
            images.append({"path": path, "caption": cap})

    rb["specs"] = specs[:16]
    rb["selection"] = selection[:10]
    rb["images"] = images[:8]
    return rb


def _guess_process(s):
    """从一句话中推断所属“工序/工位”；推断不到返回空串（由调用方给通用单元名）。

    注意：不要退化成“（机器人）/（机械手）”这类把装备类型当单元名的伪单元。
    """
    m = re.search(r"([\u4e00-\u9fa5]{2,12}(?:工序|工段|工位|岗位))", s)
    return m.group(1) if m else ""


def _clip(s, n=200):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else s[:n] + "…"


def _robot_sections(lines):
    """回退：以含机器人名称的标题/行起，收集“字段：值”。"""
    robots = []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if any(t in s for t in ROBOT_TYPES) and len(s) <= 40 and not s.startswith("|"):
            name = s.lstrip("# ").strip()
            task = risks = avoided = safety = process = ""
            for j in range(i + 1, min(n, i + 12)):
                t = lines[j].strip()
                if not t:
                    continue
                if any(x in t for x in ("负责工序", "应用工序", "工序：")):
                    process = t.split("：")[-1]
                elif any(x in t for x in ("工序内容", "工作内容", "职责")):
                    task = t.split("：")[-1]
                elif "机器人" in t and "风险" in t:
                    risks = t.split("：")[-1]
                elif "避免" in t or "降低" in t:
                    avoided = t.split("：")[-1]
                elif "防爆" in t or "安全" in t:
                    safety = t.split("：")[-1]
            robot = _build_robot(name, "", process or "（未标注工序）", task,
                                 None, None, None, "", risks, avoided, safety,
                                 source=f"第{i + 1}行")
            robots.append(robot)
        i += 1
    return robots
