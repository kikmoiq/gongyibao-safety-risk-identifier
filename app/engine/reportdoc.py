# -*- coding: utf-8 -*-
"""可阅读报告文档生成：把辨识报告 dict 渲染为
  1) 自包含 HTML（用于系统内“报告预览”页 / 浏览器打印为 PDF）
  2) Word(.docx)（可直接下载阅读；内嵌机器人选型图等图片）
"""
import html
import io
import re
from pathlib import Path

W = {"极高": 4, "高": 3, "中": 2, "低": 1, "待定": 0.5}
SEV_ORDER = {"极高": 0, "高": 1, "中": 2, "低": 3, "待定": 4}
CAT_ORDER = ["综合场景", "物料", "工艺工况", "仪表自控", "点火源·静电",
             "作业·人因", "自动化·机器人", "设备", "环境·布置", "军品专项"]


def esc(s):
    return html.escape(str(s if s is not None else ""))


def _img_src(rpt, rel_path, media_url_prefix="/api/media", embed=False):
    """返回图片地址：默认走 /api/media；embed=True 时从源目录读文件并转 base64 data URI（离线可看）。"""
    rel_path = rel_path or ""
    if embed:
        sd = rpt.get("source_dir")
        if sd and rel_path:
            p = Path(sd) / rel_path
            if p.exists() and p.is_file():
                import base64
                import mimetypes
                mime = mimetypes.guess_type(str(p))[0] or "image/png"
                try:
                    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                    return f"data:{mime};base64,{b64}"
                except Exception:
                    pass
    return f"{media_url_prefix}/{rpt.get('report_id', '')}/{rel_path}"


def _sev_weight(sev):
    return W.get(sev, 0.5)


# ---------------- 统计 ----------------
def risk_rows(rpt):
    """按 工序(unit_node) × 类别 聚合：{(row,cat): {高:1,中:2,...}} 及行合计。"""
    rows, cats = {}, []
    for it in rpt.get("items", []):
        row = it.get("unit_node") or "通用 / 全文档"
        cat = it.get("category") or "其他"
        sev = it.get("severity") or "待定"
        r = rows.setdefault(row, {"bycat": {}, "score": 0, "count": 0})
        m = r["bycat"].setdefault(cat, {})
        m[sev] = m.get(sev, 0) + 1
        r["score"] += _sev_weight(sev)
        r["count"] += 1
        if cat not in cats:
            cats.append(cat)
    cats = [c for c in CAT_ORDER if c in cats] + [c for c in cats if c not in CAT_ORDER]
    ordered = sorted(rows.items(), key=lambda kv: -kv[1]["score"])
    return ordered, cats


def _label(m):
    parts = []
    if (m.get("高", 0) + m.get("极高", 0)):
        parts.append("高%d" % (m.get("高", 0) + m.get("极高", 0)))
    if m.get("中"):
        parts.append("中%d" % m["中"])
    if m.get("低"):
        parts.append("低%d" % m["低"])
    if m.get("待定"):
        parts.append("?%d" % m["待定"])
    return " ".join(parts) or "–"


def _cell_color(w, maxw):
    ratio = 0 if not maxw else min(1.0, w / maxw)
    # 红色系：白 → 深红
    stops = [(0, (255, 245, 240)), (0.5, (255, 158, 128)), (1, (136, 15, 15))]
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]; p1, c1 = stops[i + 1]
        if ratio <= p1:
            t = (ratio - p0) / (p1 - p0 or 1)
            c = tuple(round(c0[k] + (c1[k] - c0[k]) * t) for k in range(3))
            return "rgb(%d,%d,%d)" % c
    return "rgb(136,15,15)"


def _sev_color(sev):
    return {"极高": "#a10000", "高": "#d9200c", "中": "#e8890c",
            "低": "#1a7f37", "待定": "#8a94a6"}.get(sev, "#8a94a6")


# ---------------- 工序流程图（内联 SVG，折行） ----------------
def flow_svg(rpt, width=940):
    fl = rpt.get("flow") or {}
    nodes = fl.get("nodes") or []
    if not nodes:
        return "<p class='muted'>（未抽取到工序流程）</p>"
    mains = [n for n in nodes if n.get("type") == "main"]
    auxs = [n for n in nodes if n.get("type") != "main"]
    BW, BH, GX, GY, PAD = 176, 60, 22, 46, 12
    cols = max(2, (width - 2 * PAD + GX) // (BW + GX))
    rows = max(1, (len(mains) + cols - 1) // cols)
    pos = {}
    for i, n in enumerate(mains):
        r, c = divmod(i, cols)
        cc = c if r % 2 == 0 else cols - 1 - c
        pos[n["id"]] = (PAD + cc * (BW + GX), PAD + r * (BH + GY))
    aux_y = PAD + rows * (BH + GY) + 30
    for i, n in enumerate(auxs):
        pos[n["id"]] = (PAD + (i % cols) * (BW + GX), aux_y + (i // cols) * (BH + GY))
    height = aux_y + ((len(auxs) + cols - 1) // cols or 0) * (BH + GY) + 8

    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg">',
           '<defs><marker id="ar" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto">'
           '<path d="M0,0 L9,4 L0,8 z" fill="#6b7686"/></marker></defs>']
    for a, b in zip(mains, mains[1:]):
        x1, y1 = pos[a["id"]]; x2, y2 = pos[b["id"]]
        if abs(y1 - y2) < 4:
            sx = x1 + (BW if x2 > x1 else 0); ex = x2 + (0 if x2 > x1 else BW)
            out.append(f'<path d="M{sx},{y1+BH/2} L{ex},{y2+BH/2}" stroke="#6b7686" stroke-width="1.5" fill="none" marker-end="url(#ar)"/>')
        else:
            my = (y1 + BH + y2) / 2
            out.append(f'<path d="M{x1+BW/2},{y1+BH} C {x1+BW/2},{my} {x2+BW/2},{my} {x2+BW/2},{y2}" stroke="#6b7686" stroke-width="1.5" fill="none" marker-end="url(#ar)"/>')
    for e in (fl.get("edges") or []):
        if not e.get("dashed"):
            continue
        a, b = pos.get(e["from"]), pos.get(e["to"])
        if not a or not b:
            continue
        y = height - 6
        out.append(f'<path d="M{a[0]+BW/2},{a[1]+BH} C {a[0]+BW/2},{y} {b[0]+BW/2},{y} {b[0]+BW/2},{b[1]+BH}" stroke="#b78103" stroke-width="1.8" stroke-dasharray="6 4" fill="none" marker-end="url(#ar)"/>')
    for n in nodes:
        x, y = pos[n["id"]]
        sev = n.get("risk") or "待定"
        fill = {"极高": "#fdecea", "高": "#fdecea", "中": "#fff3e0", "低": "#e6f6ec"}.get(sev, "#f4f6fa")
        stroke = _sev_color(sev)
        nm = n["name"]
        t1, t2 = (nm[:10], nm[10:20]) if len(nm) > 10 else (nm, "")
        out.append(f'<rect x="{x}" y="{y}" width="{BW}" height="{BH}" rx="9" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        out.append(f'<text x="{x+BW/2}" y="{y+(24 if t2 else 32)}" text-anchor="middle" font-size="13" font-weight="600" fill="#1f2733">{esc(t1)}</text>')
        if t2:
            out.append(f'<text x="{x+BW/2}" y="{y+40}" text-anchor="middle" font-size="13" font-weight="600" fill="#1f2733">{esc(t2)}</text>')
        out.append(f'<text x="{x+BW/2}" y="{y+BH-8}" text-anchor="middle" font-size="10" fill="#6b7686">{n.get("n_items",0)} 条 · {"主工序" if n.get("type")=="main" else "辅助"}</text>')
    out.append('</svg>')
    return "".join(out)


# ---------------- HTML 报告 ----------------
HTML_CSS = """
body{font-family:"Microsoft YaHei",-apple-system,Segoe UI,sans-serif;color:#1f2733;margin:0;background:#eef1f6;}
.doc{max-width:1000px;margin:0 auto;background:#fff;padding:34px 40px;box-shadow:0 2px 12px rgba(0,0,0,.08);}
h1{font-size:24px;margin:0 0 6px;color:#1f3a5f;}
h2{font-size:19px;margin:26px 0 10px;color:#1f3a5f;border-bottom:2px solid #e8f0fe;padding-bottom:5px;}
h3{font-size:15.5px;margin:18px 0 8px;color:#1f3a5f;}
.meta{color:#6b7686;font-size:13px;margin-bottom:8px;}
table{border-collapse:collapse;width:100%;margin:8px 0 12px;font-size:12.5px;}
th,td{border:1px solid #dde3ec;padding:5px 8px;text-align:left;vertical-align:top;}
th{background:#f6f8fc;color:#44506a;}
.muted{color:#6b7686;font-size:12.5px;}
.tag{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11.5px;background:#eef1f6;color:#44506a;margin-right:5px;}
.tag.hi{background:#ffe9e9;color:#cf222e;}
.tag.mid{background:#fff0e0;color:#bc4c00;}
.tag.doc{background:#e8f0fe;color:#1f6feb;}
.item{border:1px solid #dde3ec;border-radius:8px;padding:12px 14px;margin:10px 0;page-break-inside:avoid;}
.item .kv{margin:4px 0;font-size:13px;line-height:1.65;}
.item .k{color:#6b7686;font-weight:600;}
.ev{background:#0f1b2d;color:#d7e1ee;border-radius:6px;padding:8px 10px;font-family:Consolas,monospace;font-size:11.5px;white-space:pre-wrap;}
ul.tree{list-style:none;padding-left:16px;} ul.tree li{margin:3px 0;font-size:13px;}
.cross{border-left:4px solid #8250df;background:#fbf5ff;padding:8px 10px;margin:8px 0;font-size:13px;border-radius:0 6px 6px 0;}
.robot{border:1px solid #dde3ec;border-radius:8px;padding:12px 14px;margin:12px 0;page-break-inside:avoid;}
.robot img{max-width:520px;width:100%;border:1px solid #dde3ec;border-radius:6px;margin-top:6px;}
ul.plain{padding-left:18px;font-size:13px;line-height:1.7;}
@media print{body{background:#fff;}.doc{box-shadow:none;max-width:none;padding:0;} h2{page-break-after:avoid;} .item,.robot{page-break-inside:avoid;}}
"""


def render_html(rpt, media_url_prefix="/api/media", embed_images=False):
    rid = rpt.get("report_id", "")
    st = rpt.get("stats") or {}
    rows, cats = risk_rows(rpt)
    maxcell = 1
    for _name, r in rows:
        for m in r["bycat"].values():
            s = sum(_sev_weight(k) * v for k, v in m.items())
            maxcell = max(maxcell, s)

    h = [f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
         f"<title>{esc(rpt.get('title'))}</title><style>{HTML_CSS}</style></head><body><div class='doc'>"]
    h.append(f"<h1>{esc(rpt.get('title'))}</h1>")
    h.append(f"<div class='meta'>来源：{esc(rpt.get('source_name'))}（{esc(rpt.get('source_type'))}）　"
             f"时间：{esc(rpt.get('created_at'))}　引擎：{' + '.join(rpt.get('engine') or [])}"
             f"{'　模型：' + esc(rpt['llm_info'].get('model')) if rpt.get('llm_info') else ''}</div>")

    # 1 概览
    h.append("<h2>1 报告概览</h2>")
    pu = [u for u in (rpt.get("process_units") or []) if u]
    units_cell = str(len(rpt.get('units') or [])) + (f"（工序/区域类 {len(pu)}）" if pu else "")
    h.append("<table><tr><th>辨识条目</th><th>涉及类别</th><th>单元/章节</th><th>机器人</th>"
             "<th>减少操作人数</th><th>参考文件</th><th>截断</th></tr>"
             f"<tr><td>{st.get('total',0)}</td><td>{len(st.get('by_category') or {})}</td>"
             f"<td>{esc(units_cell)}</td><td>{st.get('robot_count',0)}</td>"
             f"<td>{st.get('staff_reduced_total',0)}</td><td>{st.get('ref_count',0)}</td>"
             f"<td>{'是' if rpt.get('truncated') else '否'}</td></tr></table>")
    h.append("<h3>1.1 按类别 / 严重度分布</h3><table><tr><th>类别</th><th>条数</th><th>严重度</th><th>条数</th></tr>")
    bc = st.get("by_category") or {}; bs = st.get("by_severity") or {}
    n = max(len(bc), len(bs))
    bcl = list(bc.items()); bsl = list(bs.items())
    for i in range(n):
        a = bcl[i] if i < len(bcl) else ("", ""); b = bsl[i] if i < len(bsl) else ("", "")
        h.append(f"<tr><td>{esc(a[0])}</td><td>{esc(a[1])}</td><td>{esc(b[0])}</td><td>{esc(b[1])}</td></tr>")
    h.append("</table>")

    h.append("<h3>1.2 工序风险热力表（行=工序，列=类别；颜色越深风险越高）</h3>")
    th = "".join(f"<th>{esc(c)}</th>" for c in cats)
    h.append(f"<table><tr><th>工序 / 单元</th>{th}<th>风险分</th></tr>")
    for name, r in rows:
        tds = []
        for c in cats:
            m = r["bycat"].get(c)
            if not m:
                tds.append("<td style='background:#fff;color:#bbb'>–</td>")
            else:
                w = sum(_sev_weight(k) * v for k, v in m.items())
                col = _cell_color(w, maxcell)
                fg = "#fff" if w > maxcell * 0.55 else "#5a1a10"
                tds.append(f"<td style='background:{col};color:{fg}'>{esc(_label(m))}</td>")
        h.append(f"<tr><td>{esc(name)}</td>{''.join(tds)}<td>{r['score']:.0f}</td></tr>")
    h.append("</table>")
    h.append("<h3>1.3 工序风险排序</h3><table><tr><th>序</th><th>工序/单元</th><th>风险分</th><th>条数</th></tr>")
    for i, (name, r) in enumerate(rows[:15], 1):
        h.append(f"<tr><td>{i}</td><td>{esc(name)}</td><td>{r['score']:.0f}</td><td>{r['count']}</td></tr>")
    h.append("</table>")
    if pu:
        h.append(f"<h3>1.4 抽取到的工序 / 区域单元（{len(pu)}，与工序流程图节点一致）</h3>")
        h.append("<div>" + "".join(f"<span class='tag'>{esc(u)}</span>" for u in pu) + "</div>")
        h.append("<p class='muted'>说明：上方“单元/章节”含文档标题层级，本表仅保留可映射为工序/区域的单元，两者口径不同。</p>")

    # 2 流程图
    h.append("<h2>2 工艺流程图</h2>")
    h.append(f"<p class='muted'>{esc((rpt.get('flow') or {}).get('note',''))}</p>")
    h.append(flow_svg(rpt))
    links = (rpt.get("fault_tree") or {}).get("cross_links") or (rpt.get("flow") or {}).get("cross_links") or []
    if links:
        h.append("<h3>2.1 工序间故障 / 风险传递</h3>")
        for l in links:
            evs = "；".join(e.get("title", "") for e in (l.get("upstream_events") or [])) or "（待补充）"
            h.append(f"<div class='cross'><b>{esc(l.get('from'))} → {esc(l.get('to'))}</b>"
                     f"（经由：{esc(l.get('via'))}）<br>{esc(l.get('note'))}<br><span class='muted'>上游事件：{esc(evs)}</span></div>")

    # 3 故障树
    ft = (rpt.get("fault_tree") or {}).get("tree")
    h.append("<h2>3 初筛故障树（FTA）</h2>")
    h.append(f"<p class='muted'>{esc((rpt.get('fault_tree') or {}).get('note',''))}</p>")

    def tree_html(node, depth=0):
        t = node.get("type", "")
        badge = {"top": "顶事件", "mid": "中间事件", "event": "风险场景",
                 "leaf": "底事件", "cross": "工序传递", "gap": "缺口"}.get(t, t)
        gate = f"（{node.get('gate')}门）" if node.get("gate") else ""
        return (f"<li>{esc(node.get('name'))} <span class='tag'>{esc(badge)}</span>"
                f"<span class='tag'>{esc(node.get('severity') or '')}</span>{esc(gate)}"
                + ("<ul class='tree'>" + "".join(tree_html(c, depth + 1) for c in (node.get("children") or [])) + "</ul>" if node.get("children") else "")
                + "</li>")

    if ft:
        h.append("<ul class='tree'>" + tree_html(ft) + "</ul>")

    # 4 机器人（章节编号固定，无台账时给出空态说明）
    robots = rpt.get("robots") or []
    h.append("<h2>4 自动化装备（机器人）</h2>")
    if not robots:
        h.append("<p class='muted'>本文档未提供机器人/自动化装备台账，未识别到自动化装备。"
                 "若产线存在机器人、机械手或 AGV，建议补充“编号 / 名称 / 类型 / 负责工序 / 原操作人数 / "
                 "现操作人数 / 该工序主要风险 / 机器人新增风险 / 防爆与安全要求”台账表后重新辨识。</p>")
    for rb in robots:
        h.append(f"<div class='robot'><h3>{esc(rb.get('id'))} {esc(rb.get('name'))}"
                 f"<span class='tag doc'>{esc(rb.get('type'))}</span>"
                 f"<span class='tag'>{esc(rb.get('process'))}</span>"
                 f"{('<span class="tag">' + esc(rb.get('ex_level')) + '</span>') if rb.get('ex_level') else ''}</h3>")
        h.append("<table><tr><th>操作人数(前)</th><th>操作人数(后)</th><th>减少</th><th>新增风险项</th><th>避免风险项</th></tr>"
                 f"<tr><td>{rb.get('staff_before')}</td><td>{rb.get('staff_after')}</td>"
                 f"<td>{rb.get('staff_reduced')}</td><td>{len(rb.get('robot_risks') or [])}</td>"
                 f"<td>{len(rb.get('avoided') or [])}</td></tr></table>")
        h.append(f"<div class='kv'><span class='k'>工序内容：</span>{esc(rb.get('task'))}</div>")
        if rb.get("specs"):
            h.append("<table><tr><th>选型参数</th><th>值</th></tr>" +
                     "".join(f"<tr><td>{esc(s['k'])}</td><td>{esc(s['v'])}</td></tr>" for s in rb["specs"]) + "</table>")
        for title, key, cls in (("该工序风险因素", "proc_risks", ""),
                                ("机器人可能新增风险", "robot_risks", "mid"),
                                ("更改后避免/降低的风险", "avoided", ""),
                                ("防爆与安全要求", "safety", "")):
            arr = rb.get(key) or []
            if arr:
                h.append(f"<div class='kv'><span class='k'>{title}：</span>" +
                         "".join(f"<span class='tag {cls}'>{esc(x)}</span>" for x in arr) + "</div>")
        if rb.get("selection"):
            h.append("<div class='kv'><span class='k'>选型说明：</span>" +
                     " ".join(esc(x) for x in rb["selection"]) + "</div>")
        for im in (rb.get("images") or []):
            src = _img_src(rpt, im.get("path", ""), media_url_prefix, embed_images)
            h.append(f"<div><img src='{src}' alt='{esc(im.get('caption'))}'>"
                     f"<div class='muted'>{esc(im.get('caption'))}</div></div>")
        h.append("</div>")

    # 5 参考文件（章节编号固定，无依据章节时给出空态说明）
    refs = rpt.get("references") or []
    h.append("<h2>5 参考文件 / 设计依据</h2>")
    if not refs:
        h.append("<p class='muted'>本文档未提供“设计依据 / 参考文件”章节，未抽取到标准或规范条目。"
                 "建议按 GB 50089（民用爆炸物品工程设计安全标准）、GB 50016、GB 50058、GB 12158、"
                 "GB 15577 等核实并补充引用清单后重新辨识。</p>")
    if refs:
        groups = {}
        for r in refs:
            groups.setdefault(r.get("type") or "其他依据", []).append(r)
        for t, arr in groups.items():
            h.append(f"<h3>{esc(t)}（{len(arr)}）</h3><table><tr><th>文件</th><th>来源</th></tr>")
            for r in arr:
                h.append(f"<tr><td>{esc(r.get('text'))}</td><td class='muted'>{esc(r.get('section'))} · 第{r.get('line')}行</td></tr>")
            h.append("</table>")

    # 6 条目明细
    h.append("<h2>6 辨识条目明细</h2>")
    for it in rpt.get("items", []):
        h.append(f"<div class='item'><div><span class='tag'>{esc(it.get('id'))}</span>"
                 f"<span class='tag'>{esc(it.get('category'))}</span>"
                 f"<span class='tag {'hi' if it.get('severity') in ('高','极高') else 'mid'}'>{esc(it.get('severity'))}</span>"
                 f"<span class='tag doc'>{esc(it.get('provenance'))}</span>"
                 f"<b> {esc(it.get('title'))}</b></div>")
        for k, lab in (("unit", "所属单元"), ("factor_desc", "危险有害因素"), ("trigger_path", "触发/失效路径"),
                       ("consequence", "可能后果"), ("existing_controls", "已有控制"), ("recommendations", "建议措施"),
                       ("source", "来源出处")):
            v = it.get(k)
            if v:
                h.append(f"<div class='kv'><span class='k'>{lab}：</span>{esc(v).replace(chr(10), '<br>')}</div>")
        ev = [e for e in (it.get("evidence") or []) if e]
        if ev:
            h.append("<div class='ev'>" + esc("\n".join(ev)) + "</div>")
        h.append("</div>")

    # 7 方法与局限
    h.append("<h2>7 辨识方法说明与局限</h2><ul class='plain'>")
    for m in (rpt.get("method_notes") or []):
        h.append(f"<li>{esc(m)}</li>")
    h.append("</ul>")
    if rpt.get("warnings"):
        h.append("<h3>局限与待确认</h3><ul class='plain'>")
        for w in rpt["warnings"]:
            h.append(f"<li>{esc(w)}</li>")
        h.append("</ul>")
    h.append("<p class='muted'>本报告由《工艺包安全风险辨识系统》自动生成，条目来自原文证据；正式安全评价请以专项分析（HAZOP/LOPA/FTA/QRA）与现行标准为准。</p>")
    h.append("</div></body></html>")
    return "".join(h)


# ---------------- Word (.docx) ----------------
def build_docx(rpt, source_dir=None) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    def set_ea(run, ea="宋体"):
        rPr = run._element.get_or_add_rPr()
        rf = rPr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts"); rPr.append(rf)
        rf.set(qn("w:eastAsia"), ea)

    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = s.left_margin = s.right_margin = Inches(0.9)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"; normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def para(text="", size=None, bold=False, ea="宋体", color=None, italic=False):
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.bold = bold; r.italic = italic
        if size: r.font.size = size
        if color: r.font.color.rgb = color
        set_ea(r, ea)
        return p

    def h(level, text):
        hd = doc.add_heading(level=min(level, 4))
        r = hd.add_run(text)
        r.font.name = "微软雅黑"; set_ea(r, "微软雅黑")
        r.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
        return hd

    def table(rows, header=True):
        if not rows:
            return
        n = max(len(r) for r in rows)
        rows = [list(r) + [""] * (n - len(r)) for r in rows]
        tb = doc.add_table(rows=len(rows), cols=n); tb.style = "Table Grid"
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                cell = tb.cell(i, j)
                p = cell.paragraphs[0]
                r = p.add_run(str(val or ""))
                r.font.size = Pt(9); set_ea(r)
                if header and i == 0:
                    r.bold = True
        doc.add_paragraph()
        return tb

    st = rpt.get("stats") or {}
    rows, cats = risk_rows(rpt)

    # 封面
    t = doc.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = t.add_run(rpt.get("title") or "安全风险辨识报告")
    tr.bold = True; tr.font.size = Pt(20); tr.font.name = "微软雅黑"; set_ea(tr, "微软雅黑")
    tr.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    sub = doc.add_paragraph(); sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run(f"来源：{rpt.get('source_name')}（{rpt.get('source_type')}）　生成时间：{rpt.get('created_at')}\n"
                     f"引擎：{' + '.join(rpt.get('engine') or [])}")
    sr.font.size = Pt(10); set_ea(sr)
    doc.add_paragraph()

    h(1, "1 报告概览")
    _pu = [u for u in (rpt.get("process_units") or []) if u]
    _units_cell = str(len(rpt.get("units") or [])) + (f"（工序/区域类 {len(_pu)}）" if _pu else "")
    table([["辨识条目", "涉及类别", "单元/章节", "机器人", "减少操作人数", "参考文件"],
           [st.get("total", 0), len(st.get("by_category") or {}), _units_cell,
            st.get("robot_count", 0), st.get("staff_reduced_total", 0), st.get("ref_count", 0)]])
    if _pu:
        h(2, "1.0 抽取到的工序 / 区域单元（与工序流程图节点一致）")
        table([["序"] + list(range(1, len(_pu) + 1)), ["单元"] + _pu])
    h(2, "1.1 按类别 / 严重度分布")
    bc = list((st.get("by_category") or {}).items()); bs = list((st.get("by_severity") or {}).items())
    dist = [["类别", "条数", "严重度", "条数"]]
    for i in range(max(len(bc), len(bs))):
        a = bc[i] if i < len(bc) else ("", ""); b = bs[i] if i < len(bs) else ("", "")
        dist.append([a[0], a[1], b[0], b[1]])
    table(dist)
    h(2, "1.2 工序风险热力表（行=工序，列=类别）")
    ht = [["工序/单元"] + cats + ["风险分"]]
    for name, r in rows:
        line = [name]
        for c in cats:
            m = r["bycat"].get(c)
            line.append(_label(m) if m else "–")
        line.append(f"{r['score']:.0f}")
        ht.append(line)
    table(ht)
    h(2, "1.3 工序风险排序（Top 15）")
    rk = [["序", "工序/单元", "风险分", "条数"]]
    for i, (name, r) in enumerate(rows[:15], 1):
        rk.append([i, name, f"{r['score']:.0f}", r["count"]])
    table(rk)

    doc.add_page_break()
    h(1, "2 工艺流程图")
    para((rpt.get("flow") or {}).get("note", ""), size=Pt(9), italic=True)
    fl = rpt.get("flow") or {}
    mains = [n for n in (fl.get("nodes") or []) if n.get("type") == "main"]
    auxs = [n for n in (fl.get("nodes") or []) if n.get("type") != "main"]
    para("主链：" + " → ".join(n["name"] for n in mains), bold=True)
    if auxs:
        para("辅助节点：" + "、".join(n["name"] for n in auxs))
    ftab = [["工序", "类型", "风险", "条数", "主要工作内容"]]
    for n in (fl.get("nodes") or []):
        ftab.append([n["name"], "主工序" if n.get("type") == "main" else "辅助",
                     n.get("risk", ""), n.get("n_items", 0), (n.get("desc") or "")[:120]])
    table(ftab)
    links = (rpt.get("fault_tree") or {}).get("cross_links") or []
    if links:
        h(2, "2.1 工序间故障 / 风险传递")
        ct = [["上游", "下游", "经由物料", "上游关键事件", "说明"]]
        for l in links:
            ct.append([l.get("from"), l.get("to"), l.get("via"),
                       "；".join(e.get("title", "") for e in (l.get("upstream_events") or [])),
                       l.get("note", "")])
        table(ct)

    doc.add_page_break()
    h(1, "3 初筛故障树（FTA）")
    para((rpt.get("fault_tree") or {}).get("note", ""), size=Pt(9), italic=True)
    tree = (rpt.get("fault_tree") or {}).get("tree")

    def dump(node, lvl=0):
        if not node:
            return
        tag = {"top": "顶事件", "mid": "中间事件", "event": "风险场景", "leaf": "底事件",
               "cross": "工序传递", "gap": "缺口"}.get(node.get("type"), "")
        gate = f"[{node.get('gate')}门] " if node.get("gate") else ""
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.18 * lvl)
        r = p.add_run("• " + gate + str(node.get("name")) + f"（{tag}｜{node.get('severity') or ''}）")
        r.font.size = Pt(9.5); set_ea(r)
        if node.get("note"):
            r2 = p.add_run("　" + str(node["note"])[:120]); r2.font.size = Pt(8.5); r2.italic = True; set_ea(r2)
        for c in (node.get("children") or []):
            dump(c, lvl + 1)

    dump(tree)

    robots = rpt.get("robots") or []
    doc.add_page_break()
    h(1, "4 自动化装备（机器人）")
    if robots:
        for rb in robots:
            h(2, f"{rb.get('id')} {rb.get('name')}（{rb.get('type')}）— {rb.get('process')}"
                 + (f"　{rb.get('ex_level')}" if rb.get("ex_level") else ""))
            table([["操作人数(前)", "操作人数(后)", "减少", "新增风险项", "避免风险项"],
                   [rb.get("staff_before"), rb.get("staff_after"), rb.get("staff_reduced"),
                    len(rb.get("robot_risks") or []), len(rb.get("avoided") or [])]])
            if rb.get("task"):
                para("工序内容：" + rb["task"])
            if rb.get("specs"):
                h(3, "选型参数")
                table([["参数", "值"]] + [[s["k"], s["v"]] for s in rb["specs"]])
            for title, key in (("该工序风险因素", "proc_risks"), ("机器人可能新增风险", "robot_risks"),
                               ("更改后避免/降低的风险", "avoided"), ("防爆与安全要求", "safety")):
                if rb.get(key):
                    para(title + "：", bold=True)
                    for x in rb[key]:
                        p = doc.add_paragraph(style="List Bullet")
                        r = p.add_run(str(x)); r.font.size = Pt(9.5); set_ea(r)
            if rb.get("selection"):
                para("选型说明：", bold=True)
                for x in rb["selection"]:
                    p = doc.add_paragraph(style="List Bullet")
                    r = p.add_run(str(x)); r.font.size = Pt(9.5); set_ea(r)
            for im in (rb.get("images") or []):
                p = im.get("path", "")
                fp = None
                # python-docx 仅支持位图；SVG 等矢量图在 Word 中给出来源说明（HTML 预览可直接显示）
                embeddable = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".emf", ".wmf")
                if source_dir and p:
                    cand = Path(source_dir) / p
                    # 优先嵌入同名 .png（由 SVG 渲染而来），否则用可嵌入的位图原图
                    if cand.suffix.lower() not in embeddable or not cand.exists():
                        sibling = cand.with_suffix(".png")
                        if sibling.exists():
                            cand = sibling
                    if cand.exists() and cand.suffix.lower() in embeddable:
                        fp = cand
                if fp:
                    try:
                        cp = doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        cp.add_run().add_picture(str(fp), width=Inches(5.6))
                        cap = doc.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        cr = cap.add_run(im.get("caption") or ""); cr.font.size = Pt(9); cr.italic = True; set_ea(cr)
                    except Exception:
                        para("（选型图：%s；原图文件 %s）" % (im.get("caption") or "", p), size=Pt(9), italic=True)
                else:
                    para("（选型图：%s；原图文件 %s —— 可用“报告预览”页或对应目录查看）"
                         % (im.get("caption") or "", p), size=Pt(9), italic=True)
    else:
        para("本文档未提供机器人/自动化装备台账，未识别到自动化装备。若产线存在机器人、机械手或 AGV，"
             "建议补充“编号 / 名称 / 类型 / 负责工序 / 原操作人数 / 现操作人数 / 该工序主要风险 / "
             "机器人新增风险 / 防爆与安全要求”台账表后重新辨识。", size=Pt(9.5), italic=True)

    refs = rpt.get("references") or []
    doc.add_page_break()
    h(1, "5 参考文件 / 设计依据")
    if refs:
        groups = {}
        for r in refs:
            groups.setdefault(r.get("type") or "其他依据", []).append(r)
        for t, arr in groups.items():
            h(2, f"{t}（{len(arr)}）")
            table([["文件", "来源"]] + [[r.get("text"), f"{r.get('section')} · 第{r.get('line')}行"] for r in arr])
    else:
        para("本文档未提供“设计依据 / 参考文件”章节，未抽取到标准或规范条目。建议按 GB 50089（民用爆炸物品工程设计安全标准）、"
             "GB 50016、GB 50058、GB 12158、GB 15577 等核实并补充引用清单后重新辨识。", size=Pt(9.5), italic=True)

    doc.add_page_break()
    h(1, "6 辨识条目明细")
    for it in rpt.get("items", []):
        p = doc.add_paragraph()
        r = p.add_run(f"{it.get('id')}｜{it.get('category')}｜{it.get('severity')}｜{it.get('provenance')}　{it.get('title')}")
        r.bold = True; r.font.size = Pt(10.5); set_ea(r)
        for k, lab in (("unit", "所属单元"), ("factor_desc", "危险有害因素"), ("trigger_path", "触发/失效路径"),
                       ("consequence", "可能后果"), ("existing_controls", "已有控制"),
                       ("recommendations", "建议措施"), ("source", "来源出处")):
            v = it.get(k)
            if v:
                pp = doc.add_paragraph()
                pp.paragraph_format.left_indent = Inches(0.15)
                rr = pp.add_run(f"{lab}：{v}"); rr.font.size = Pt(9.5); set_ea(rr)
        ev = [e for e in (it.get("evidence") or []) if e]
        if ev:
            pp = doc.add_paragraph(); pp.paragraph_format.left_indent = Inches(0.15)
            rr = pp.add_run("原文证据：" + " ｜ ".join(ev)); rr.font.size = Pt(8.5)
            rr.font.name = "Consolas"; set_ea(rr, "宋体")

    h(1, "7 辨识方法说明与局限")
    for m in (rpt.get("method_notes") or []):
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(m); r.font.size = Pt(9.5); set_ea(r)
    for w in (rpt.get("warnings") or []):
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run("局限：" + w); r.font.size = Pt(9.5); set_ea(r)
    para("本报告由《工艺包安全风险辨识系统》自动生成；正式安全评价请以专项分析与现行标准为准。",
         size=Pt(9), italic=True)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
