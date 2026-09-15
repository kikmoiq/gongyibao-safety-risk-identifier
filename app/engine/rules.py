# -*- coding: utf-8 -*-
"""本地规则引擎：把规范化后的工艺包文本，按《安全风险辨识方案》的逻辑提炼成辨识条目。

策略（保守、可追溯，全部来自原文证据）：
  1. 识别“风险场景表”（含 风险场景/风险等级/点火源/管控 列）→ 逐行成条（provenance=doc）
  2. 识别“标签-值(SDS)两列表” → 每个物料成条，摘录 危险性类别/燃爆危险/健康危害 等
  3. 扫描叙事文本中的 联锁/报警阈值（℃ MPa ppm %LEL 等）→ 参数超限条目
  4. 扫描叙事文本中的 点火源、作业类关键词 → 条目
通用文本中的“物料名”可能无法自动命名 → 标注待补，建议大模型增强。
"""
import re

from .models import (
    CATEGORIES, PROVENANCE_DOC, PROVENANCE_RULE,
    make_item,
)

# ---------- 常量 ----------
MAX_ITEMS_TOTAL = 160        # 单报告条目上限（防巨文档刷屏）
CAP_BY_KIND = {"scene": 60, "sds": 60, "interlock": 40, "ignition": 15, "work": 15, "mil": 12}

SEV_KW = {"极高风险": "极高", "高风险": "高", "中风险": "中", "低风险": "低"}
SEV_GUESS_HIGH = ["剧毒", "爆炸性混合物", "极易燃", "燃烧爆炸", "爆炸危险", "易爆炸"]
SEV_GUESS_MED = ["有毒", "可燃", "腐蚀", "易燃", "聚合", "窒息"]

MATERIAL_HAZ_KW = ["易燃", "易爆", "可燃", "有毒", "剧毒", "腐蚀", "爆炸性混合物",
                   "窒息", "助燃", "聚合", "易挥发", "氧化剂", "自燃", "职业接触限值"]

HAZARD_LABELS = ["危险性类别", "燃爆危险", "危险特性", "健康危害", "侵入途径",
                 "有害燃烧产物", "闪点", "爆炸上限", "爆炸下限", "引燃温度",
                 "职业接触限值", "灭火方法", "稳定性", "禁忌物", "急性毒性"]

INTERLOCK_WORDS = ["联锁", "报警", "切断", "泄压", "停车", "SIS", "ESD", "高报",
                   "低报", "超温", "超压", "置换", "紧急", "低联锁", "高联锁"]
NUM_UNIT_RE = re.compile(r"(≥|>|大于|不低于|≤|<|小于|不高于|=|至|~)?\s*\d+(?:\.\d+)?\s*(℃|°C|°F|MPa|bar|kPa|ppm|%LEL|Vol%|vol%|m³|m3|t/a|kg/h)")
IGNITION_KW = ["明火", "电火花", "电气火花", "火花", "静电", "热表面", "雷电", "机械火花",
               "摩擦", "撞击", "杂散", "射频", "高温表面"]
WORK_KW = ["检维修", "动火", "受限空间", "开车", "停车", "置换", "吹扫", "装卸",
           "引料", "倒料", "加料", "排污", "取样", "巡检", "堵漏"]
# 军品（火炸药/发射药/装药等）专项线索 → 单列“军品专项”类别
MIL_KW = ["感度", "撞击感度", "摩擦感度", "静电感度", "殉爆", "量-距离", "量—距离",
          "定员定量", "自加速分解", "热分解", "安定性", "钝感", "钝化剂", "起爆",
          "在线药量", "抗爆间", "泄爆面", "冲击波", "破片", "静电敏感", "含水率"]

KNOWN_MATERIALS = ["1,3-丁二烯", "丁二烯", "氢氰酸", "HCN", "液氨", "氨气", "甲醇",
                   "甲烷", "己二腈", "ADN", "戊烯腈", "丙烯腈", "乙腈", "催化剂",
                   "氯化锌", "亚磷酸酯", "镍络合物", "一氧化碳", "二氧化碳", "硫化氢",
                   "氧气", "氮气", "硫酸", "氢氧化钠"]


# ---------- 文本基础工具 ----------
def split_cells(line: str):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
def is_sep(line: str) -> bool:
    return bool(SEP_RE.match(line)) and "-" in line


def clip(s: str, n: int = 140) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n] + "…"


# ---------- 解析文档 → 结构 ----------
class Doc:
    """轻量文档结构：行、表区域、标题面包屑、单元列表。"""

    def __init__(self, text: str):
        self.lines = text.splitlines()
        self.n = len(self.lines)
        self.in_table = [False] * self.n          # 是否落在表块内
        self.table_blocks = []                    # dict: start,end,rows,row_lineno
        self._scan_tables()
        self.units = []                           # 检测到的标题（作为单元候选）

    def _scan_tables(self):
        i = 0
        n = self.n
        while i < n:
            ln = self.lines[i].strip()
            if ln.startswith("|"):
                start = i
                block = []
                lineno = []
                while i < n and self.lines[i].strip().startswith("|"):
                    raw = self.lines[i]
                    # 跳过分隔行
                    if not is_sep(raw):
                        block.append(raw)
                        lineno.append(i + 1)
                    i += 1
                if block:
                    rows = [split_cells(b) for b in block]
                    # 若首行是分隔符样式头（已去掉），直接存
                    self.table_blocks.append({
                        "start": start, "end": i,
                        "rows": rows, "lineno": lineno,
                        "raw": block,
                    })
                    for j in range(start, i):
                        self.in_table[j] = True
                continue
            i += 1

    def headings(self):
        """产出 (level, text, lineno) 标题列表"""
        for idx, line in enumerate(self.lines):
            m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
            if m:
                yield len(m.group(1)), m.group(2).strip(), idx + 1


def heading_before(lines, pos, n, level_cap=6):
    """返回 pos 行之前最近的标题路径（含级别），用于归属单元。"""
    stack = []
    for j in range(pos - 1, -1, -1):
        m = re.match(r"^(#{1,6})\s+(.*)$", lines[j].strip())
        if m:
            lv = len(m.group(1))
            txt = m.group(2).strip()
            stack = [x for x in stack if x[0] >= lv]
            stack.insert(0, (lv, txt))
            if lv == 1 or len(stack) >= 4:
                break
    if not stack:
        return "", ""
    unit = stack[-1][1]
    path = " / ".join(t for _, t in stack[-3:])
    return unit, path


# ---------- 风险场景表识别 ----------
# 主判据：“场景类”表头词（常规工艺包）
RISK_HEAD_KW = ["风险场景", "主要风险", "危险工况", "事故场景", "风险辨识"]
# 辅判据：非常规表头（如“序号｜工房岗位｜危险源｜风险描述｜风险等级｜可能点火源｜…”）
RISK_LEVEL_KW = ["风险等级", "风险级别", "危险等级"]
RISK_COL_HINT = ["点火源", "管控", "对策", "防控", "后果", "原因", "措施",
                 "危险源", "风险描述", "事故类型", "危害因素", "危险有害因素"]


def _looks_risk_table(tb):
    rows = tb["rows"]
    if len(rows) < 2:
        return None
    head = rows[0]
    joined = "|".join(str(x) for x in head)
    # 机器人/自动化台账表交给 robots 模块处理，避免误判为风险场景表
    if "机器人" in joined and any(k in joined for k in ("负责工序", "原操作人数", "机器人名称", "AGV")):
        return None
    if any(k in joined for k in RISK_HEAD_KW):
        return head
    # 兜底：无“风险场景”字样，但“风险等级 + 管控/点火源/后果类列”齐备，同样按风险表处理
    # （例：起爆药线的“危险源/风险描述”式表头，此前会整表漏读）
    if (len(head) >= 3
            and any(k in joined for k in RISK_LEVEL_KW)
            and any(k in joined for k in RISK_COL_HINT)):
        return head
    return None


def _kv_table(tb):
    """若为 标签→值 两列表（允许夹杂跨列分段标题行，如“第X部分 …”）则返回 {label: value}。

    典型来源：工艺包 SDS 表（化学品中文名称 | 值、危险性类别 | 值 …）。
    """
    rows = tb["rows"]
    if len(rows) < 2:
        return None
    pairs = []          # 两列数据行
    section_seen = 0    # 单列分段标题行数量
    for r in rows:
        if len(r) == 1:
            section_seen += 1
            continue
        if len(r) != 2:
            return None
        pairs.append(r)
    if len(pairs) < 3:
        return None
    kv = {}
    for k, v in pairs:
        key = clip(k, 40)
        if key and not key.lower().startswith(("序号", "编号", "项", "no", "#")):
            kv[key] = v
    name_keys = ("化学品中文名称", "品名", "中文名称", "名称", "产品名称", "物料名称", "化学名称")
    if any(nk in kv for nk in name_keys):
        return kv
    return None


# ---------- 主提取 ----------
def extract(text: str) -> dict:
    doc = Doc(text)
    items = []
    counters = {"scene": 0, "sds": 0, "interlock": 0, "ignition": 0, "work": 0, "mil": 0}
    seen_lines = set()
    warnings = []
    method_notes = []
    scene_units = []   # 风险场景表工序（文档原顺序，供流程主链）

    def push(kind, item):
        if counters[kind] >= CAP_BY_KIND.get(kind, 60):
            return False
        counters[kind] += 1
        items.append(item)
        return True

    # ---- A) 表块处理：风险场景表 与 SDS 键值表 ----
    scene_rows_total = 0
    sds_tables = 0
    for tb in doc.table_blocks:
        head = _looks_risk_table(tb)
        if head is not None:
            head_map = {clip(str(h)): ci for ci, h in enumerate(head)}
            # 允许列名含多词，如 “风险场景” 或 “序号/工序/风险场景/风险等级/…”。
            def col(*names):
                for nm in names:
                    for hk, ci in head_map.items():
                        if nm in hk or hk in nm:
                            return ci
                return None

            c_seq, c_scene, c_level, c_ign, c_ctrl = (
                col("序号", "编号"), col("风险场景", "风险", "场景"),
                col("风险等级"), col("点火源"), col("管控", "对策", "防控", "措施"),
            )
            c_impr = col("建议", "改进", "整改", "提升")
            c_haz = col("危险源", "危险有害因素", "危害因素", "危险因素", "事故类型")
            c_unit = col("工序", "单元", "装置", "工段", "部位", "节点", "系统",
                         "区域", "工位", "岗位", "工房", "工区", "作业区", "场所", "车间")
            if c_unit is None:
                # 列名未命中（如按“区域/岗位”组织风险表）：退而取“非 序号/场景/等级/点火源/管控/建议”的首个列
                for _ci in range(len(head)):
                    if _ci not in {c_seq, c_scene, c_level, c_ign, c_ctrl, c_impr, c_haz}:
                        c_unit = _ci
                        break
            first_col_is_seq = c_seq == 0 or (
                c_seq is None and c_unit is None and head and clip(str(head[0])) in ("序号", "编号", "#", "No."))
            for row, ln in zip(tb["rows"][1:], tb["lineno"][1:]):
                if len(row) <= 1:
                    continue
                scene = str(row[c_scene]) if c_scene is not None and c_scene < len(row) else ""
                if not scene:
                    continue
                scene_rows_total += 1
                if c_unit is not None and c_unit < len(row) and str(row[c_unit]).strip():
                    unit_txt = str(row[c_unit]).strip()
                elif first_col_is_seq:
                    unit_txt = ""
                else:
                    unit_txt = str(row[0]) if len(row) > 1 else ""
                if unit_txt == scene:
                    unit_txt = ""
                if unit_txt and unit_txt not in scene_units:
                    scene_units.append(unit_txt)
                impr = (str(row[c_impr]) if c_impr is not None and c_impr < len(row) else "").strip()
                haz = (str(row[c_haz]) if c_haz is not None and c_haz < len(row) else "").strip()
                sev_raw = (str(row[c_level]) if c_level is not None and c_level < len(row) else "")
                sev = SEV_KW.get(sev_raw.strip(), sev_raw.strip() or "待定")
                ign = (str(row[c_ign]) if c_ign is not None and c_ign < len(row) else "")
                ctrl = (str(row[c_ctrl]) if c_ctrl is not None and c_ctrl < len(row) else "")
                cat = "综合场景"
                if any(k in scene for k in ["超温", "失控", "聚合", "放热", "配比"]):
                    cat = "工艺工况"
                elif any(k in scene for k in ["干烧", "泄漏火灾", "着火"]):
                    cat = "综合场景"
                elif "泄漏" in scene and ("爆炸" in scene or "燃" in scene):
                    cat = "综合场景"
                it = make_item(
                    unit=unit_txt or "（未标注单元）",
                    category=cat,
                    title=f"场景：{clip(scene, 60)}",
                    factor_desc=f"工艺包自带风险场景：{scene}",
                    trigger_path=(("点火源：" + ign) if ign else ""),
                    existing_controls=(ctrl if ctrl else ""),
                    consequence="（结合物料特性与单元条件判断，建议转 HAZOP 深化）",
                    recommendations=(impr if impr else "校核保护层充分性（独立 DCS/SIS、探测器、泄放、应急），确定残余风险是否可接受。"),
                    source=f"{heading_before(doc.lines, tb['start'], doc.n)[1]} · 风险场景表 第{ln}行",
                    evidence=[f"场景：{scene}", f"风险等级：{sev}" if sev else "",
                              f"危险源：{haz}" if haz else "",
                              f"点火源：{ign}" if ign else "", f"管控：{ctrl}" if ctrl else "",
                              f"建议改进：{impr}" if impr else ""],
                    severity=sev, provenance=PROVENANCE_DOC, confidence="高",
                )
                push("scene", it)
            continue

        kv = _kv_table(tb)
        if kv is not None:
            name = kv.get("化学品中文名称") or kv.get("品名") or kv.get("中文名称") or \
                   kv.get("名称") or kv.get("产品名称") or ""
            if name and name not in ("无资料", "-"):
                sds_tables += 1
                parts = []
                # 兼容不同工艺包的标签写法：危险性类别/危险分类/危险类别、燃爆危险/燃爆特性/危险特性
                for lab in ("危险性类别", "危险分类", "危险类别", "燃爆危险", "燃爆特性", "危险特性"):
                    if kv.get(lab):
                        parts.append(f"{lab}：{clip(kv[lab], 160)}")
                health = kv.get("健康危害") or kv.get("侵入途径")
                fac = "\n".join(parts)
                if health:
                    fac += f"\n健康危害：{clip(health, 160)}"
                sev = "待定"
                blob = " ".join(parts) + " " + (health or "")
                if any(k in blob for k in SEV_GUESS_HIGH):
                    sev = "高"
                elif any(k in blob for k in SEV_GUESS_MED):
                    sev = "中"
                sev_note = ""
                if sev == "待定":
                    # SDS 未标注危险性类别时给“规则建议值”，并明确标注待人工确认（不消除不确定性）
                    if any(k in name for k in ("包装", "管壳", "脚线", "器具", "托盘", "支架", "垫片")):
                        sev = "低"
                    else:
                        sev = "中"
                    sev_note = "（严重度为规则建议值，待人工确认）"
                controls = []
                for lab in ("操作注意事项", "储存注意事项", "灭火方法"):
                    if kv.get(lab):
                        controls.append(f"{lab}：{clip(kv[lab], 120)}")
                it = make_item(
                    unit=heading_before(doc.lines, tb["start"], doc.n)[1] or "物料安全",
                    category="物料",
                    title=f"物料辨识：{clip(name, 30)}",
                    factor_desc=fac or "（SDS 危险性信息，需人工核对）",
                    consequence=f"{name} 若泄漏/失控可能引发火灾爆炸或中毒等事故，具体以现场存量为准。",
                    existing_controls="\n".join(controls[:2]) if controls else "",
                    recommendations=("按 SDS 落实操作/储存要求；核对职业接触限值、探测报警阈值与存量（重大危险源）。"
                                     + sev_note),
                    source=f"{heading_before(doc.lines, tb['start'], doc.n)[1]} · SDS 表（{tb['lineno'][0]} 行起）",
                    evidence=[f"{lab}：{clip(val, 200)}" for lab, val in kv.items()
                              if val and val not in ("无资料", "-")][:8],
                    severity=sev, provenance=PROVENANCE_DOC, confidence="高",
                )
                push("sds", it)
            continue

    # ---- B) 叙事文本扫描（跳过表内行）----
    def narrative_context(pos):
        return heading_before(doc.lines, pos, doc.n)

    for idx, line in enumerate(doc.lines):
        if doc.in_table[idx]:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "```", ">", "![")):
            continue
        # 过长整行（可能是整段复制）只取前 220 字作证据
        snippet = clip(stripped, 220)
        unit, path = narrative_context(idx)

        # 联锁/安全阈值
        if any(k in stripped for k in INTERLOCK_WORDS) and NUM_UNIT_RE.search(stripped):
            if len(stripped) <= 400:
                seen_lines.add(idx)
                it = make_item(
                    unit=unit or "工艺/控制",
                    category="仪表自控" if any(k in stripped for k in ["联锁", "SIS", "ESD", "报警", "低联锁", "高联锁"]) else "工艺工况",
                    title=clip("关键安全参数/联锁：" + _short(stripped), 70),
                    factor_desc=clip(stripped, 200),
                    consequence="参数越限可能导致超温/超压/泄漏等危险工况；联锁缺失或失效将放大后果。",
                    existing_controls=clip(stripped, 200),
                    recommendations="核对联锁独立性（SIS 独立于 DCS）、报警/联锁定值与最大可信事故匹配性；转 LOPA 校核。",
                    source=f"{path} · 第{idx + 1}行",
                    evidence=[snippet],
                    severity="高" if any(k in stripped for k in ["联锁", "超温", "超压", "切断"]) else "中",
                    provenance=PROVENANCE_RULE, confidence="高",
                )
                push("interlock", it)

        # 军品专项（感度/殉爆/量-距离/安定性等）——优先于点火源/作业识别
        if any(k in stripped for k in MIL_KW):
            if idx not in seen_lines and len(stripped) <= 400:
                seen_lines.add(idx)
                found = [k for k in MIL_KW if k in stripped]
                it = make_item(
                    unit=unit or "（军品专项）",
                    category="军品专项",
                    title="军品专项辨识：" + "/".join(found[:3]),
                    factor_desc=clip(stripped, 240),
                    trigger_path=f"军品专项线索：{'、'.join(found[:5])}；需结合感度/殉爆/量-距离专项评价。",
                    consequence="火炸药/发射药类物质在摩擦、撞击、静电等能量作用下可能意外点火，进而殉爆或造成人员伤害。",
                    existing_controls="（按原文 / 兵器行业规范核查）",
                    recommendations="开展撞击/摩擦/静电感度测试与 DSC 热分析；按定员定量与安全距离控制在线药量，设置抗爆间/泄爆面防殉爆。",
                    source=f"{path} · 第{idx + 1}行",
                    evidence=[snippet],
                    severity="高" if any(k in stripped for k in ("殉爆", "感度", "自加速分解", "在线药量")) else "中",
                    provenance=PROVENANCE_RULE, confidence="中",
                )
                push("mil", it)

        # 点火源（非表格、非联锁行内重复）
        if any(k in stripped for k in IGNITION_KW) and "点火源" not in unit:
            if idx not in seen_lines and len(stripped) <= 300:
                seen_lines.add(idx)
                found = [k for k in IGNITION_KW if k in stripped]
                it = make_item(
                    unit=unit or "（全文）",
                    category="点火源·静电",
                    title="点火源识别：" + "/".join(found),
                    factor_desc=clip(stripped, 200),
                    trigger_path=f"点火源类型：{'、'.join(found)}；需判断是否与可燃/爆炸性气氛同时存在",
                    consequence="在爆炸性/可燃环境中出现点火源可导致火灾或爆炸。",
                    existing_controls="（按防爆分区与原文核查）",
                    recommendations="核对防爆电气选型、静电接地/跨接、动火管控、防雷接地等是否到位。",
                    source=f"{path} · 第{idx + 1}行",
                    evidence=[snippet],
                    severity="中", provenance=PROVENANCE_RULE, confidence="中",
                )
                push("ignition", it)

        # 作业类
        if any(k in stripped for k in WORK_KW):
            if idx not in seen_lines and len(stripped) <= 300:
                seen_lines.add(idx)
                found = [k for k in WORK_KW if k in stripped]
                it = make_item(
                    unit=unit or "（作业）",
                    category="作业·人因",
                    title="作业活动辨识：" + "/".join(found),
                    factor_desc=clip(stripped, 220),
                    consequence="作业时机不当或防护缺失可能引入点火源、毒物暴露或人身伤害。",
                    existing_controls="（按原文/规程）",
                    recommendations="作业许可与监护、置换分析、个体防护、限量与定员管理。",
                    source=f"{path} · 第{idx + 1}行",
                    evidence=[snippet],
                    severity="中", provenance=PROVENANCE_RULE, confidence="中",
                )
                push("work", it)

    # ---- 标题单元列表 ----
    units = []
    for lv, txt, ln in doc.headings():
        if lv <= 3 and txt and txt not in units:
            units.append(txt)
        if len(units) >= 80:
            break

    # ---- 方法与局限说明 ----
    method_notes.append(f"① 风险场景表：识别 {scene_rows_total} 行（若工艺包自带，直接作为辨识基线）；")
    method_notes.append(f"② SDS/标签-值表：识别 {sds_tables} 个物料块（摘录危险性类别/健康危害等）；")
    method_notes.append(f"③ 联锁/安全阈值：提炼 {counters['interlock']} 处（温度/压力/浓度等）；")
    method_notes.append(f"④ 点火源、作业活动、军品专项等叙事线索：点火源 {counters['ignition']} 处、"
                        f"作业 {counters['work']} 处、军品专项 {counters['mil']} 处。")
    if scene_rows_total == 0:
        warnings.append("未在文档中检测到“风险场景/风险辨识”表格，建议以人工或大模型逐节点辨识。")
    if sds_tables == 0:
        warnings.append("未检测到结构化 SDS 键值表：若文档为纯叙述，物料特性条目可能缺失，建议启用“大模型增强”。")
    warnings.append("规则引擎无法为“完全不同工艺包”自动命名未知物料/未知感度参数，相关条目已标注，建议大模型增强或人工补名后复核。")

    # 排序：先 doc 后 rule；同类别按严重度
    order = {PROVENANCE_DOC: 0, PROVENANCE_RULE: 1, "llm": 2}
    sev_o = {"极高": 0, "高": 1, "中": 2, "低": 3, "待定": 4}
    items.sort(key=lambda it: (order.get(it["provenance"], 9), sev_o.get(it["severity"], 9)))
    total = len(items)
    return {
        "items": items[:MAX_ITEMS_TOTAL],
        "units": units,
        "scene_units": scene_units,
        "method_notes": method_notes,
        "warnings": warnings,
        "truncated": total > MAX_ITEMS_TOTAL,
        "counters": counters,
    }


def _short(s: str) -> str:
    """从一句中抽较短的“关键词+数值”片段作标题。"""
    m = re.search(r"(.{0,18}?(?:联锁|报警|超温|超压|切断|泄压|置换|SIS|ESD|停车).{0,24})", s)
    if m:
        return clip(m.group(1), 56)
    return clip(s, 56)
