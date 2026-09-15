# -*- coding: utf-8 -*-
"""把「生成的工艺包」与「对应辨识报告」分别落盘归档。

用法（需先启动服务）：python archive_results.py
输出：<工作区根目录>/成果归档/<序号_名称>/
       ├─ 工艺包_xxx.md            （工艺包原文副本）
       ├─ 辨识报告_xxx.docx        （Word 报告）
       ├─ 辨识报告_xxx.html        （自包含 HTML，图片已内嵌，离线可读/可打印 PDF）
       ├─ 辨识报告_xxx.json        （完整数据，供二次处理）
       ├─ 媒体\\...                （报告引用的图片，如机器人选型图）
       └─ README.txt               （归档说明与统计摘要）
"""
import datetime
import shutil
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
HERE = Path(__file__).resolve().parent          # 本系统目录
ROOT = HERE.parent
OUT_ROOT = ROOT / "成果归档"
PKG_DIRS = [ROOT, HERE, HERE / "示例数据"]

PKGS = [
    ("硝化棉单基发射药自动化生产线工艺包_演示示例.md", "01_自动化生产线-硝化棉单基发射药"),
    ("硝化棉单基发射药生产工艺包_演示示例.md", "02_常规生产线-硝化棉单基发射药"),
]


def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with httpx.Client(timeout=300) as cli:
        for fn, folder in PKGS:
            p = next((d / fn for d in PKG_DIRS if (d / fn).exists()), None)
            if p is None:
                print(f"[跳过] 未找到工艺包：{fn}")
                continue
            print(f"[分析] {p.name} ...")
            r = cli.post(BASE + "/api/analyze/path", json={"path": str(p)}).json()
            rid, stem = r["report_id"], p.stem
            d = OUT_ROOT / folder
            d.mkdir(parents=True, exist_ok=True)

            shutil.copy2(p, d / f"工艺包_{stem}.md")
            (d / f"辨识报告_{stem}.docx").write_bytes(
                cli.get(BASE + f"/api/report/{rid}/document", params={"format": "docx"}).content)
            (d / f"辨识报告_{stem}.html").write_text(
                cli.get(BASE + f"/api/report/{rid}/document",
                        params={"format": "html", "embed": 1}).text, encoding="utf-8")
            (d / f"辨识报告_{stem}.json").write_text(
                cli.get(BASE + f"/api/export/{rid}").text, encoding="utf-8")

            # 报告引用到的图片（含同名 .png 回退）一起归档
            media = set()
            for rb in r.get("robots", []):
                for im in rb.get("images", []):
                    media.add(im.get("path") or "")
            sdir = Path(r.get("source_dir") or p.parent)
            copied = []
            for rel in sorted(x for x in media if x):
                for cand in (sdir / rel, (sdir / rel).with_suffix(".png")):
                    if cand.exists():
                        dst = d / "媒体" / cand.name
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(cand, dst)
                        copied.append(cand.name)

            st = r.get("stats") or {}
            lines = [
                f"工艺包：{p.name}",
                f"来源路径：{p}",
                f"归档时间：{now}",
                f"报告 ID：{rid}",
                "",
                "统计摘要：",
                f"  辨识条目 {st.get('total')} 条；单元/章节 {len(r.get('units') or [])} 个",
                f"  机器人 {st.get('robot_count', 0)} 台；减少操作人数合计 {st.get('staff_reduced_total', 0)}",
                f"  参考文件 {st.get('ref_count', 0)} 项",
                f"  按类别：{st.get('by_category')}",
                f"  按严重度：{st.get('by_severity')}",
                "",
                "文件说明：",
                "  工艺包_*.md         —— 工艺包原文（本次生成/使用的版本）",
                "  辨识报告_*.docx     —— Word 报告（含图，可直接阅读/编辑）",
                "  辨识报告_*.html     —— 自包含 HTML（图片已内嵌，离线可读，可打印为 PDF）",
                "  辨识报告_*.json     —— 完整数据（条目/流程/故障树/机器人/参考文件）",
                "  媒体\\...            —— 报告引用的图片（如机器人选型图 SVG+PNG）",
                "",
                "生成工具：《工艺包安全风险辨识系统》v0.3.0-demo",
                "提示：结果为规则/LLM 辅助的初筛辨识，正式安全评价请以专项分析（HAZOP/LOPA/FTA/QRA）与现行标准为准。",
            ]
            (d / "README.txt").write_text("\n".join(lines), encoding="utf-8")
            print(f"  -> {d}  (条目 {st.get('total')}，媒体 {len(copied)} 个: {', '.join(copied)})")
    print("完成。输出目录：", OUT_ROOT)


if __name__ == "__main__":
    sys.exit(main())
