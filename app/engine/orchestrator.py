# -*- coding: utf-8 -*-
"""分析编排：本地规则（必跑）+ 大模型增强（可选）→ 一份多页报告的 JSON。"""
from datetime import datetime, timezone

from . import rules
from . import llm
from . import flow as flow_mod
from . import fta as fta_mod
from . import robots as robots_mod
from . import references as refs_mod
from .models import new_report, PROVENANCE_LLM

# 前端分类筛选顺序（与报告展示一致）
CATEGORY_ORDER = ["综合场景", "物料", "工艺工况", "仪表自控", "点火源·静电",
                  "作业·人因", "自动化·机器人", "设备", "环境·布置", "军品专项"]


def analyze(text: str, source_name: str, source_type: str, use_llm: bool,
            cfg: dict, engine_extra: str = "", source_dir: str = None) -> dict:
    """主入口。返回完整 report dict。source_dir 用于解析/展示工艺包内的图片。"""
    # 1) 本地规则
    res = rules.extract(text)
    items = list(res["items"])
    units = list(res["units"])
    method_notes = list(res.get("method_notes", []))
    warnings = list(res.get("warnings", []))
    engine_used = ["本地规则引擎"]

    # 1.5) 自动化 / 机器人台账
    rb_robots, rb_items = robots_mod.extract_robots(text, items, base_dir=source_dir)
    if rb_robots or rb_items:
        items.extend(rb_items)
        method_notes.append(f"⑥ 自动化/机器人：识别机器人（含防爆/桁架/机械手/AGV）{len(rb_robots)} 台，"
                            f"生成机器人条目 {len(rb_items)} 条（含各工序定员减少）。")

    # 2) 大模型增强（可选）
    llm_info = None
    if use_llm:
        engine_used.append("大模型增强")
        enh = llm.enhance(text, cfg)
        if enh["ok"]:
            items.extend(enh["items"])
            llm_info = {"base_url": cfg.get("llm", {}).get("base_url", ""),
                        "model": enh.get("model", "")}
            method_notes.append(f"⑤ 大模型增强：新增 {len(enh['items'])} 条（对未知物料/后果判定的补充）。")
        else:
            warnings.append(f"大模型增强未生效：{enh.get('message', '')}")
    else:
        method_notes.append("⑤ 未启用大模型增强：如对“完全不同工艺包”需智能补名/判定，请在 API 配置后重跑。")

    if engine_extra:
        method_notes.append(engine_extra)

    # 3) 统一重编号，保证唯一
    items = _renumber(items)

    # 3.5) 工序流程图 + 条目归属 + 初筛故障树
    fl = flow_mod.build_process_flow(text, items, scene_units=res.get("scene_units"))
    by_id = {it["id"]: it for it in items}
    for it in items:
        it["unit_node"] = fl.get("item_to_node", {}).get(it["id"], "")
    # 机器人编号与关联条目
    robot_ids = {it["id"] for it in items if it.get("category") == "自动化·机器人"}
    for i, rb in enumerate(rb_robots, 1):
        rb["id"] = f"RB-{i:02d}"
        rb["item_ids"] = [it["id"] for it in items
                          if it["id"] in robot_ids and rb["name"] and rb["name"] in (it.get("title") or "")]
        if not rb["item_ids"]:
            rb["item_ids"] = [it["id"] for it in items
                              if it["id"] in robot_ids and (it.get("unit") or "") == rb["process"]]
    ft = fta_mod.build_fault_tree(fl, items, source_name)
    # 参考文件 / 设计依据
    refs = refs_mod.extract_references(text)
    if refs:
        method_notes.append(f"⑦ 参考文件/设计依据：抽取 {len(refs)} 项（标准规范、手册、参考书等）。")

    # 4) 汇总
    report_id = _new_id()
    rpt = new_report(report_id, _title(source_name), source_name, source_type)
    rpt["created_at"] = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    rpt["engine"] = engine_used
    rpt["llm_info"] = llm_info
    rpt["units"] = units
    # 与工序流程图节点一致的“工序/区域单元”（用于区分“页章标题”与“工序单元”）
    rpt["process_units"] = [n.get("name") for n in (fl.get("nodes") or []) if n.get("name")]
    rpt["items"] = items
    rpt["flow"] = {k: v for k, v in fl.items() if k != "item_to_node"}
    rpt["fault_tree"] = ft
    rpt["robots"] = rb_robots
    rpt["references"] = refs
    rpt["source_dir"] = source_dir
    rpt["method_notes"] = method_notes
    rpt["warnings"] = warnings
    rpt["truncated"] = bool(res.get("truncated"))

    st = rpt["stats"]
    st["total"] = len(items)
    st["robot_count"] = len(rb_robots)
    st["staff_reduced_total"] = sum((r.get("staff_reduced") or 0) for r in rb_robots)
    st["ref_count"] = len(refs)
    for it in items:
        st["by_category"][it["category"]] = st["by_category"].get(it["category"], 0) + 1
        st["by_severity"][it["severity"]] = st["by_severity"].get(it["severity"], 0) + 1
        st["by_provenance"][it["provenance"]] = st["by_provenance"].get(it["provenance"], 0) + 1
    st["by_category"] = {k: st["by_category"].get(k, 0) for k in CATEGORY_ORDER if st["by_category"].get(k)}
    return rpt


def _renumber(items):
    for i, it in enumerate(items, 1):
        it["id"] = f"RI-{i:03d}"
    return items


def _title(name: str) -> str:
    base = name or "未命名工艺包"
    return f"《{base}》安全风险辨识报告"


def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]
