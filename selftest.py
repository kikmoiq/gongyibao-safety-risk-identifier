# -*- coding: utf-8 -*-
"""开发自测：真实己二腈文档 → 报告（流程/故障树/归属）质量检查。"""
import collections
import sys
import time

sys.path.insert(0, r"e:\桌面\工艺包\安全风险辨识系统")
from app.engine import orchestrator, ingest

t0 = time.time()
default = r"e:\桌面\工艺包\硝化棉单基发射药生产工艺包_演示示例.md"
path = sys.argv[1] if len(sys.argv) > 1 else default
text, name = ingest.read_source(path, "md")
rpt = orchestrator.analyze(text, name, "md", False, {"llm": {}})
fl = rpt["flow"]
print("条目=%d 耗时%.1fs" % (rpt["stats"]["total"], time.time() - t0))
print("类别:", rpt["stats"]["by_category"])
print("严重度:", rpt["stats"]["by_severity"])
print("来源:", rpt["stats"]["by_provenance"])
print("流程节点描述长度:", {n["name"]: len(n["desc"]) for n in fl["nodes"]})
print("工序间传递链数:", len(fl.get("cross_links", [])))
for l in fl.get("cross_links", [])[:3]:
    print("  ", l["from"], "->", l["to"], "| via:", l["via"], "| 上游事件:", [e["title"] for e in l["upstream_events"]])
print("FTA cross_links:", len(rpt["fault_tree"].get("cross_links", [])))
print("robots:", len(rpt.get("robots", [])), "| 减少人数合计:", rpt["stats"].get("staff_reduced_total"))
for r in rpt.get("robots", [])[:6]:
    print("   ", r["id"], r["name"], "|", r["process"], "| 减少", r["staff_reduced"], "人 | 条目", r["item_ids"])
print("主工序:", [n["name"] for n in fl["nodes"] if n["type"] == "main"])
print("辅助:", [n["name"] for n in fl["nodes"] if n["type"] == "aux"])
print("边:", [(e["from"], e["to"], e.get("label")) for e in fl["edges"]])
cnt = collections.Counter(it["unit_node"] for it in rpt["items"])
print("条目归属(>0):", dict(list(cnt.items())[:14]))
ft = rpt["fault_tree"]
print("FTA 顶:", ft["tree"]["name"])


def walk(n, d=0):
    print("  " * d + "-", n["type"], "|", n["name"][:36], "| sev=", n.get("severity"),
          "| kids=", len(n.get("children") or []))
    for c in (n.get("children") or [])[:3]:
        walk(c, d + 1)


walk(ft["tree"], 0)
