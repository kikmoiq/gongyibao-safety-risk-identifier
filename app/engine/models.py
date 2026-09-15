# -*- coding: utf-8 -*-
"""共享数据模型/常量：辨识条目与报告的结构约定（用 dict，便于直接 JSON 序列化）"""

# 危险有害因素分类（对应辨识维度）
CATEGORIES = [
    "物料",          # 危险物质及其特性（SDS）
    "工艺工况",      # 反应/温度压力/联锁超限等
    "设备",          # 承压、密封、转动设备失效等
    "仪表自控",      # 检测缺失/联锁失效等
    "点火源·静电",   # 明火/火花/静电/热表面/雷电等
    "作业·人因",     # 开停车/检维修/装卸等
    "自动化·机器人", # 防爆机器人/桁架机器人/机械手/AGV 等自动化装备
    "环境·布置",     # 间距/通风/多米诺/周边暴露
    "军品专项",      # 感度/殉爆/量-距离等（预留）
    "综合场景",      # 文档自带的整体风险场景
]

# 条目来源
PROVENANCE_DOC = "doc"      # 直接取自工艺包自带的风险场景表/联锁/辨识内容
PROVENANCE_RULE = "rule"    # 本地规则引擎从文档提炼
PROVENANCE_LLM = "llm"      # 大模型增强生成

SEVERITY_ORDER = {"极高": 0, "高": 1, "中": 2, "低": 3, "待定": 4}

# 条目编号前缀
ID_PREFIX = "RI"


def make_item(seq=None, **kw) -> dict:
    """生成一条标准化辨识条目（编号在编排层统一重排，seq 可省略）。"""
    item = {
        "id": f"{ID_PREFIX}-{seq:03d}" if seq is not None else f"{ID_PREFIX}-000",
        "unit": "",            # 所属单元/文档章节
        "category": "综合场景",
        "title": "",
        "factor_desc": "",     # 危险有害因素描述
        "trigger_path": "",    # 触发/失效路径（可多行，用\n分隔）
        "consequence": "",
        "existing_controls": "",
        "recommendations": "",
        "source": "",          # 来源（文档章节/表名/行号）
        "evidence": [],        # 原文证据（逐条字符串）
        "severity": "待定",
        "provenance": PROVENANCE_RULE,
        "confidence": "中",    # 高/中/低
    }
    item.update(kw)
    return item


def new_report(report_id: str, title: str, source_name: str, source_type: str) -> dict:
    return {
        "report_id": report_id,
        "title": title,
        "source_name": source_name,
        "source_type": source_type,   # md / docx / text / demo
        "created_at": None,
        "engine": [],                 # 使用的引擎：["本地规则","大模型增强"]
        "llm_info": None,             # {base_url, model} 或 None
        "units": [],                  # 识别出的单元/章节列表
        "items": [],                  # 辨识条目（多页报告的数据源）
        "flow": None,                 # 工序流程图 {nodes, edges, note}
        "fault_tree": None,           # 初筛故障树 {tree, note}
        "robots": [],                 # 自动化/机器人名录
        "references": [],             # 参考文件/设计依据
        "source_dir": None,           # 源文件目录（用于展示工艺包内图片）
        "stats": {
            "total": 0,
            "by_category": {},
            "by_severity": {},
            "by_provenance": {},
        },
        "method_notes": [],           # 本次执行的辨识步骤说明（覆盖度）
        "warnings": [],               # 局限与待确认提示
    }
