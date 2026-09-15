# -*- coding: utf-8 -*-
"""大模型(LLM)增强：OpenAI 兼容 chat/completions。

用途：对“完全不同的工艺包”，在本地规则引擎的基础上，
让大模型依据《辨识方法》从原文提炼结构化条目（尤其命名未知物料、判定后果）。
无 key / 失败时静默返回，不影响本地规则结果。
"""
import json
import re

import httpx

from .models import PROVENANCE_LLM, CATEGORIES

_SYSTEM = """你是“工艺包安全风险辨识”分析助手。依据以下方法对给定工艺包节选做安全风险辨识：
按对象维度（物料、工艺工况、设备、仪表自控、点火源·静电、作业·人因、环境·布置、军品专项、综合场景）
提炼危险有害因素条目。每条目必须给出：unit(所属工序/单元)、category(限以上类别之一)、
title(一句话条目标题)、factor_desc(危险有害因素)、trigger_path(触发/失效路径，可多行用换行分隔)、
consequence(可能后果)、existing_controls(原文已给出的控制措施；没有则写“（原文未明确）”)、
recommendations(建议措施或待专项确认)、evidence(1~3 条原文短句作为证据)、severity(高/中/低/待定)、
confidence(高/中/低)。只依据给定原文，不要编造原文没有的数据；无法判断就标注待定。
直接输出 JSON 数组，不要输出多余文字或代码围栏。"""

_KEYS = ["unit", "category", "title", "factor_desc", "trigger_path", "consequence",
         "existing_controls", "recommendations", "evidence", "severity", "confidence"]

_CAT_SET = set(CATEGORIES)


def build_excerpt(text: str, max_chars: int) -> str:
    """挑选“有辨识价值”的行：含章节标题/安全/物料/联锁/风险/温度压力浓度等词。"""
    kws = ["安全", "风险", "物料", "SDS", "联锁", "报警", "报警", "泄漏", "危险",
           "易燃", "易爆", "有毒", "剧毒", "可燃", "聚合", "静电", "点火", "应急",
           "检维修", "置换", "操作", "储存", "℃", "MPa", "ppm", "LEL"]
    lines = text.splitlines()
    out = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            out.append(s)
            continue
        if any(k in s for k in kws):
            out.append(s[:220])
        if sum(len(x) for x in out) >= max_chars:
            break
    return "\n".join(out)[:max_chars]


def enhance(text: str, cfg: dict) -> dict:
    """调用 LLM 得到增强条目。返回 {items, ok, message, model}。"""
    llm_cfg = cfg.get("llm", {}) or {}
    base_url = (llm_cfg.get("base_url") or "").rstrip("/")
    api_key = llm_cfg.get("api_key") or ""
    model = llm_cfg.get("model") or "deepseek-chat"
    result = {"items": [], "ok": False, "message": "", "model": model}
    if not base_url or not api_key:
        result["message"] = "未配置 LLM（base_url/api_key 为空），已跳过增强。"
        return result
    excerpt = build_excerpt(text, int(llm_cfg.get("max_excerpt_chars", 12000)))
    if len(excerpt) < 200:
        result["message"] = "节选内容过少，无法增强。"
        return result

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"以下是工艺包文档节选：\n\n{excerpt}"},
        ],
        "temperature": float(llm_cfg.get("temperature", 0.2)),
        "max_tokens": int(llm_cfg.get("max_tokens", 4096)),
    }
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=240) as client:
            resp = client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            result["message"] = f"LLM HTTP {resp.status_code}: {resp.text[:200]}"
            return result
        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        items = _parse_json_items(content)
        if not items:
            result["message"] = "LLM 返回无法解析的 JSON。"
            return result
        result["items"] = items
        result["ok"] = True
        result["message"] = f"LLM 增强成功：新增 {len(items)} 条。"
    except Exception as e:  # noqa: BLE001
        result["message"] = f"LLM 调用异常：{e}"
    return result


def _parse_json_items(content: str):
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
    try:
        data = json.loads(content)
    except Exception:
        m = re.search(r"\[.*\]", content, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        row = {k: row.get(k, "") for k in _KEYS}
        ev = row.get("evidence") or []
        if isinstance(ev, str):
            ev = [ev]
        cat = row.get("category") or "综合场景"
        if cat not in _CAT_SET:
            cat = "综合场景"
        out.append({
            "unit": str(row.get("unit") or "（LLM 判定）").strip(),
            "category": cat,
            "title": str(row.get("title") or "（未命名条目）").strip(),
            "factor_desc": str(row.get("factor_desc") or "").strip(),
            "trigger_path": str(row.get("trigger_path") or "").strip(),
            "consequence": str(row.get("consequence") or "").strip(),
            "existing_controls": str(row.get("existing_controls") or "").strip(),
            "recommendations": str(row.get("recommendations") or "").strip(),
            "evidence": [str(x)[:300] for x in ev][:6],
            "severity": str(row.get("severity") or "待定").strip(),
            "confidence": str(row.get("confidence") or "中").strip(),
            "provenance": PROVENANCE_LLM,
        })
    return out
