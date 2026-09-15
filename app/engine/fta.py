# -*- coding: utf-8 -*-
"""数据驱动“初筛故障树”（FTA）：把辨识条目组织成 顶事件→工段中间事件→风险场景→底事件 的树。

重要：本树由规则从辨识条目与文档关键词生成，布尔关系简化为“或”，
仅用于梳理“工序间故障/风险相互影响”与定位，正式 FTA 需人工校核顶事件、
逻辑门（与/或）与概率数据后使用。
"""
import re

# 场景关键词 → 可能的底层致因关键词（启发式关联）
REL = {
    "超温|失控|热失控": ["冷却", "联锁", "搅拌", "SIS", "切料", "温度", "循环水"],
    "泄漏": ["密封", "探测", "检测", "腐蚀", "置换", "盲板", "负压", "检维修", "垫片"],
    "爆炸|燃爆|燃烧": ["静电", "火花", "明火", "防爆", "接地", "动火", "LEL", "氧化剂", "防爆电气"],
    "聚合|自催化|堵塞": ["阻聚", "稳定剂", "温度", "TBC", "抑制剂"],
    "中毒|窒息": ["HCN", "探测", "通风", "负压", "密闭", "监测", "气体"],
    "干烧|再沸器": ["液位", "低报警", "再沸器", "液位低"],
    "超压|破裂": ["泄压", "安全阀", "联锁", "压力", "爆破片"],
    "火灾|着火": ["热表面", "可燃", "防烫", "保温", "泄漏"],
    "粉尘|倒料|装药": ["静电", "除尘", "通风", "摩擦", "明火"],
}

CAUSE_CATS = {"仪表自控", "点火源·静电", "作业·人因"}
_id = [0]


def _nid(prefix="t"):
    _id[0] += 1
    return f"{prefix}{_id[0]:03d}"


def _norm_sev(it):
    return {"极高": 0, "高": 1, "中": 2, "低": 3}.get(it.get("severity"), 9)


def _blob(it):
    return f"{it.get('title') or ''} {it.get('factor_desc') or ''} {it.get('trigger_path') or ''}"


def _is_cause(it):
    if it.get("category") in CAUSE_CATS:
        return True
    # 物料中只取“聚合/自燃/爆燃”相关作为底事件候选
    if it.get("category") == "物料" and any(k in _blob(it) for k in ("聚合", "自燃", "自催化", "极易燃", "爆炸")):
        return True
    return False


def _match_scene_cause(scene_blob, cause_blob):
    """若 cause 的关键词能对 scene 的关键词群给出致因，返回匹配关键字名列表。"""
    hits = []
    for key, kws in REL.items():
        if re.search(key, scene_blob):
            for kw in kws:
                if kw and kw in cause_blob:
                    hits.append(kw)
                    break
    return hits


def build_fault_tree(flow: dict, items: list, report_title: str = "") -> dict:
    _id[0] = 0
    node_map = {n["id"]: n for n in flow.get("nodes", [])}
    main_nodes = [n for n in flow.get("nodes", []) if n.get("type") == "main"]
    by_node = {}
    for n in flow.get("nodes", []):
        by_node[n["name"]] = n
    cross_by_to = {c.get("to"): c for c in flow.get("cross_links", [])}

    causes_pool = [it for it in items if _is_cause(it)]
    used_cause_ids = set()
    children = []

    # 每个主工序 → 子树
    for nd in main_nodes:
        scenes = [it for it in items if it.get("unit_node") == nd["name"]
                  and it.get("category") in ("综合场景", "工艺工况")]
        scenes.sort(key=_norm_sev)
        scenes = scenes[:6]
        if not scenes:
            # 回退：按名称命中且属于风险相关类别的条目
            scenes = [it for it in items
                      if nd["name"] and nd["name"] in f"{it.get('unit') or ''}{it.get('source') or ''}"
                      and it.get("category") in ("综合场景", "工艺工况", "仪表自控",
                                                 "作业·人因", "点火源·静电")]
            scenes = sorted(scenes, key=_norm_sev)[:3]
        sub_children = []
        for sc in scenes:
            sblob = _blob(sc)
            leaves = []
            for c in causes_pool:
                if c["id"] in used_cause_ids:
                    continue
                if _match_scene_cause(sblob, _blob(c)):
                    leaves.append(c)
                    used_cause_ids.add(c["id"])
                if len(leaves) >= 4:
                    break
            sc_node = {
                "id": _nid("e"), "name": f"{sc.get('title') or '风险场景'}",
                "type": "event", "gate": "or", "unit": nd["name"],
                "severity": sc.get("severity"), "item_ids": [sc["id"]],
                "note": "由辨识条目生成的风险场景（或门）；底层致因需校核。",
                "children": [
                    {
                        "id": _nid("b"), "name": c.get("title") or "底事件",
                        "type": "leaf", "gate": None,
                        "unit": c.get("unit") or "",
                        "severity": c.get("severity"),
                        "item_ids": [c["id"]], "note": "",
                        "children": [],
                    }
                    for c in leaves
                ],
            }
            if not sc_node["children"]:
                sc_node["children"].append({
                    "id": _nid("b"), "name": "（保护层失效/外部诱因：待专项补全底事件）",
                    "type": "gap", "gate": None, "unit": nd["name"],
                    "severity": "待定", "item_ids": [], "note": "规则未能从文档中匹配到具体底事件，需人工细化。",
                    "children": [],
                })
            sub_children.append(sc_node)

        # 跨工序传递：来自上游工序的“带病物料/风险传播”
        cross = cross_by_to.get(nd["name"])
        if cross:
            x_leaves = []
            for ev in cross.get("upstream_events", []):
                x_leaves.append({
                    "id": _nid("b"), "name": f"上游事件：{ev.get('title') or '（未命名）'}",
                    "type": "leaf", "gate": None, "unit": cross.get("from") or "",
                    "severity": ev.get("severity"), "item_ids": [ev["id"]] if ev.get("id") else [],
                    "note": f"来自「{cross.get('from')}」；未受控将随【{cross.get('via')}】传递至本工序。",
                    "children": [],
                })
            if not x_leaves:
                x_leaves.append({
                    "id": _nid("b"), "name": "上游工序输入异常（待识别）", "type": "gap",
                    "gate": None, "unit": cross.get("from") or "", "severity": "待定",
                    "item_ids": [], "note": "上游工序暂无可关联风险场景，需人工补充其传递风险。",
                    "children": [],
                })
            sub_children.insert(0, {
                "id": _nid("x"), "name": f"⚠ 上游传递风险：来自「{cross.get('from')}」（经由 {cross.get('via')}）",
                "type": "cross", "gate": "or", "unit": nd["name"], "severity": "高",
                "item_ids": [e["id"] for e in cross.get("upstream_events", []) if e.get("id")],
                "note": cross.get("note", ""),
                "children": x_leaves,
            })

        if not sub_children:
            sub_children.append({
                "id": _nid("e"), "name": f"{nd['name']}：主要风险（待识别/待人工补充场景）",
                "type": "event", "gate": "or", "unit": nd["name"],
                "severity": "待定", "item_ids": [], "note": "该工序暂无风险场景条目。",
                "children": [],
            })
        children.append({
            "id": _nid("m"), "name": f"{nd['name']}：工序风险子树",
            "type": "mid", "gate": "or", "unit": nd["name"],
            "severity": nd.get("risk") or "待定", "item_ids": nd.get("item_ids", []),
            "note": "工序级中间事件（或门）。", "children": sub_children,
        })

    # 共性致因（未分配给具体场景的底事件）
    leftover = [c for c in causes_pool if c["id"] not in used_cause_ids]
    if leftover:
        children.append({
            "id": _nid("m"), "name": "共性致因（跨工序：保护层 / 点火源 / 作业 / 物料聚合）",
            "type": "mid", "gate": "or", "unit": "",
            "severity": "中", "item_ids": [c["id"] for c in leftover][:20],
            "note": "在多个工序均有出现可能的底事件，未单独挂到某场景。",
            "children": [
                {
                    "id": _nid("b"), "name": c.get("title") or "底事件", "type": "leaf",
                    "gate": None, "unit": c.get("unit") or "",
                    "severity": c.get("severity"), "item_ids": [c["id"]], "note": "",
                    "children": [],
                }
                for c in leftover[:12]
            ],
        })

    tree = {
        "id": _nid("top"),
        "name": "装置（系统）重大危险事件（初筛顶事件）",
        "type": "top", "gate": "or", "unit": "",
        "severity": "高", "item_ids": [],
        "note": ("由各工段高风险场景“或”汇聚而成。本树为数据驱动初筛结果："
                 "逻辑门简化为或、无概率/频次，仅用于梳理工序间故障传播与风险影响，"
                 "正式 FTA 需人工校核。"),
        "children": children,
    }
    return {
        "tree": tree,
        "cross_links": flow.get("cross_links", []),
        "note": ("初筛故障树：顶事件—工段中间事件—风险场景—底事件，并含“上游传递风险”体现工序间联系；"
                 "或门为主，需人工校核布尔关系与补全底事件。"),
    }
