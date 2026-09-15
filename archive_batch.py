# -*- coding: utf-8 -*-
"""批量：新工艺包 → 系统辨识 → 报告归档（每包一文件夹）+ 批次对比汇总。

用法（需先启动服务）：python archive_batch.py
"""
import datetime
import json
import shutil
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
HERE = Path(__file__).resolve().parent          # 本系统目录
ROOT = HERE.parent                              # 工作区根目录（工艺包 .md 通常放这里）
OUT_ROOT = ROOT / "成果归档"
# 工艺包查找顺序：工作区根目录 → 系统目录下的 示例数据/
PKG_DIRS = [ROOT, HERE, HERE / "示例数据"]

PKGS = [
    ("硝化棉单基发射药自动化生产线工艺包_演示示例.md", "01_自动化生产线-硝化棉单基发射药"),
    ("硝化棉单基发射药生产工艺包_演示示例.md", "02_常规生产线-硝化棉单基发射药"),
    ("双基发射药连续化生产线工艺包_演示示例.md", "03_双基发射药连续化生产线"),
    ("起爆药合成与干燥筛分线工艺包_演示示例.md", "04_起爆药合成与干燥筛分线"),
    ("工业雷管装配生产线工艺包_演示示例.md", "05_工业雷管装配生产线"),
    ("单基发射药药粒包覆与混同包装线工艺包_演示示例.md", "06_药粒包覆与混同包装线"),
    ("发射药成品储存与厂内智能输送线工艺包_演示示例.md", "07_成品储存与智能输送线"),
]

TOOL_VERSION = "v0.3.1-demo"   # 由 main() 根据 /api/health 覆盖


def archive(cli, src: Path, folder: str, now: str) -> dict:
    print(f"[分析] {src.name} ...")
    r = cli.post(BASE + "/api/analyze/path", json={"path": str(src)}).json()
    rid, stem = r["report_id"], src.stem
    d = OUT_ROOT / folder
    d.mkdir(parents=True, exist_ok=True)

    shutil.copy2(src, d / f"工艺包_{stem}.md")
    (d / f"辨识报告_{stem}.docx").write_bytes(
        cli.get(BASE + f"/api/report/{rid}/document", params={"format": "docx"}).content)
    html = cli.get(BASE + f"/api/report/{rid}/document",
                   params={"format": "html", "embed": 1}).text
    (d / f"辨识报告_{stem}.html").write_text(html, encoding="utf-8")
    (d / f"辨识报告_{stem}.json").write_text(
        cli.get(BASE + f"/api/export/{rid}").text, encoding="utf-8")

    media = {im.get("path") for rb in r.get("robots", []) for im in rb.get("images", [])}
    sdir = Path(r.get("source_dir") or src.parent)
    copied = []
    for rel in sorted(x for x in media if x):
        for cand in (sdir / rel, (sdir / rel).with_suffix(".png")):
            if cand.exists():
                dst = d / "媒体" / cand.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cand, dst)
                copied.append(cand.name)

    st = r.get("stats") or {}
    flow = r.get("flow") or {}
    fta = r.get("fta") or {}
    cross = flow.get("cross_links") or []
    m = {
        "folder": folder, "stem": stem, "rid": rid,
        "total": st.get("total"),
        "cats": st.get("by_category") or {},
        "sevs": st.get("by_severity") or {},
        "units": len(r.get("units") or []),
        "robots": st.get("robot_count", 0),
        "staff": st.get("staff_reduced_total", 0),
        "refs": st.get("ref_count", 0),
        "flow_main": len([n for n in (flow.get("nodes") or []) if n.get("type") != "aux"]),
        "flow_aux": len([n for n in (flow.get("nodes") or []) if n.get("type") == "aux"]),
        "cross": len(cross),
        "fta_children": len(fta.get("nodes") or []),
        "media": len(copied),
        "html_kb": round(len(html.encode("utf-8")) / 1024),
    }

    lines = [
        f"工艺包：{src.name}",
        f"来源路径：{src}",
        f"归档时间：{now}",
        f"报告 ID：{rid}",
        "",
        "统计摘要：",
        f"  辨识条目 {m['total']} 条；单元/章节 {m['units']} 个",
        f"  机器人 {m['robots']} 台；减少操作人数合计 {m['staff']}",
        f"  参考文件 {m['refs']} 项",
        f"  工序流程：主链 {m['flow_main']} 个 + 辅助 {m['flow_aux']} 个；工序间传递 {m['cross']} 条",
        f"  按类别：{m['cats']}",
        f"  按严重度：{m['sevs']}",
        "",
        "文件说明：",
        "  工艺包_*.md         —— 工艺包原文（本次生成/使用的版本）",
        "  辨识报告_*.docx     —— Word 报告（含图，可直接阅读/编辑）",
        "  辨识报告_*.html     —— 自包含 HTML（图片已内嵌，离线可读，可打印为 PDF）",
        "  辨识报告_*.json     —— 完整数据（条目/流程/故障树/机器人/参考文件）",
        "  媒体\\...            —— 报告引用的图片（如机器人选型图 SVG+PNG）",
        "",
        "生成工具：《工艺包安全风险辨识系统》" + TOOL_VERSION,
        "提示：结果为规则/LLM 辅助的初筛辨识，正式安全评价请以专项分析（HAZOP/LOPA/FTA/QRA）与现行标准为准。",
    ]
    (d / "README.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"  -> {d.name}  条目 {m['total']}｜类 {len(m['cats'])}｜主链 {m['flow_main']}｜机器人 {m['robots']}｜参考 {m['refs']}")
    return m


def main():
    global TOOL_VERSION
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    with httpx.Client(timeout=300) as cli:
        # 服务健康检查（含版本）
        try:
            h = cli.get(BASE + "/api/health").json()
            TOOL_VERSION = "v" + str(h.get("version") or TOOL_VERSION)
            print(f"[服务] version={h.get('version')} build={h.get('build')}")
        except Exception as e:
            print(f"[错误] 无法连接服务 {BASE}：{e}")
            return 1
        for fn, folder in PKGS:
            src = next((d / fn for d in PKG_DIRS if (d / fn).exists()), None)
            if src is None:
                print(f"[跳过] 未找到工艺包：{fn}")
                continue
            rows.append(archive(cli, src, folder, now))

    # 批次对比汇总
    hdr = ["归档目录", "条目", "类别数", "单元", "主链", "辅助", "传递", "机器人", "减少人数", "参考文件", "HTML(KB)"]
    tbl = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for m in rows:
        tbl.append("| " + " | ".join(str(x) for x in [
            m["folder"], m["total"], len(m["cats"]), m["units"], m["flow_main"], m["flow_aux"],
            m["cross"], m["robots"], m["staff"], m["refs"], m["html_kb"]]) + " |")
    all_sev = {}
    for m in rows:
        for k, v in (m["sevs"] or {}).items():
            all_sev[k] = all_sev.get(k, 0) + v
    out = ["# 批次归对比汇总（新增 5 个工艺包）", "", f"生成时间：{now}", "", *tbl, "",
           f"**合计辨识条目：{sum(m['total'] or 0 for m in rows)} 条**", "",
           f"批次严重度合计：{all_sev}", "",
           "各包详情见对应归档目录下的 README.txt 与辨识报告。"]
    (OUT_ROOT / "_批次对比汇总.md").write_text("\n".join(out), encoding="utf-8")
    print("\n" + "\n".join(tbl))
    print(f"\n合计条目：{sum(m['total'] or 0 for m in rows)}；严重度合计：{all_sev}")
    print("输出目录：", OUT_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
