/* 工艺包安全风险辨识系统 Demo —— 前端逻辑（无框架、无 CDN，离线可用） */
"use strict";

const $ = (id) => document.getElementById(id);
const CAT_ORDER = ["综合场景", "物料", "工艺工况", "仪表自控", "点火源·静电", "作业·人因", "自动化·机器人", "设备", "环境·布置", "军品专项"];

let REPORT = null;      // 当前报告
let FILTERED = [];      // 过滤后的条目（对象引用数组）
let ACTIVE = 0;         // 0=概览页，>=1 = FILTERED 中的第 ACTIVE 条
let VIEW = "overview";  // overview / items / flow / fta

/* ---------- 工具 ---------- */
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && (data.detail || data.error)) || ("HTTP " + res.status));
  return data;
}
function sevTag(s) {
  const v = String(s || "待定");
  const cls = v === "极高" || v === "高" ? "sev-high" : v === "中" ? "sev-medium" : v === "低" ? "sev-low" : "sev-pending";
  return `<span class="tag ${cls}">${esc(v)}</span>`;
}
function srcTag(p) {
  const map = { doc: ["src-doc", "工艺包自带"], rule: ["src-rule", "本地规则"], llm: ["src-llm", "大模型"] };
  const m = map[p] || ["src-doc", p];
  return `<span class="tag ${m[0]}">${m[1]}</span>`;
}
function catTag(c) { return `<span class="tag cat">${esc(c)}</span>`; }
function kv(title, val) {
  const has = val != null && String(val).trim().length > 0;
  return `<div class="kv-block"><div class="kv-title">${title}</div>
    <div class="kv-content ${has ? "" : "empty"}">${has ? esc(val) : "（原文未明确 / 待专项确认）"}</div></div>`;
}

/* ---------- 视图切换 ---------- */
function showInput() {
  $("view-input").style.display = "";
  $("view-report").style.display = "none";
  $("btnNew").style.display = "none";
  loadReportList();
}
function showReport() {
  $("view-input").style.display = "none";
  $("view-report").style.display = "";
  $("btnNew").style.display = "";
}
function setLoading(on, text) {
  $("loading").classList.toggle("show", on);
  if (text) $("loadingText").textContent = text;
}

/* ---------- 输入视图：Tabs ---------- */
document.querySelectorAll(".tabbtn").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".tabbtn").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    ["upload", "text", "demo"].forEach((t) => ($("tab-" + t).style.display = t === b.dataset.tab ? "" : "none"));
  });
});

/* ---------- 上传 ---------- */
let pickedFile = null;
$("pickFile").addEventListener("click", (e) => { e.preventDefault(); $("fileInput").click(); });
$("fileInput").addEventListener("change", () => { pickedFile = $("fileInput").files[0] || null; updateFileMeta(); });
const dz = $("dropzone");
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", (e) => {
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) { pickedFile = f; $("fileInput").files = undefined; updateFileMeta(); }
});
function updateFileMeta() {
  const box = $("fileMeta");
  if (pickedFile) {
    box.style.display = "";
    $("fileMetaText").textContent = `已选择：${pickedFile.name}（${(pickedFile.size / 1024).toFixed(1)} KB）`;
    $("btnRunUpload").disabled = false;
  } else {
    box.style.display = "none";
    $("btnRunUpload").disabled = true;
  }
}
$("btnRunUpload").addEventListener("click", async () => {
  if (!pickedFile) return;
  setLoading(true, "正在上传并辨识（.docx 会先自动转换）…");
  try {
    const fd = new FormData();
    fd.append("file", pickedFile);
    fd.append("use_llm", $("useLlmU").checked ? "true" : "false");
    const rpt = await api("/api/analyze/upload", { method: "POST", body: fd });
    openReport(rpt);
  } catch (e) { alert("分析失败：" + e.message); }
  finally { setLoading(false); }
});

/* ---------- 粘贴文本 ---------- */
$("btnRunText").addEventListener("click", async () => {
  const text = $("txtArea").value;
  if (!text.trim()) { alert("请先粘贴文本"); return; }
  setLoading(true, "正在辨识（含表格归一化与逐行扫描）…");
  try {
    const rpt = await api("/api/analyze/text", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, filename: $("txtName").value || "", use_llm: $("useLlmT").checked }),
    });
    openReport(rpt);
  } catch (e) { alert("分析失败：" + e.message); }
  finally { setLoading(false); }
});

/* ---------- 演示 ---------- */
$("btnRunDemo").addEventListener("click", async () => {
  setLoading(true, "正在辨识演示样例…");
  try {
    const rpt = await api("/api/analyze/demo?use_llm=" + ($("useLlmD").checked ? "true" : "false"));
    openReport(rpt);
  } catch (e) { alert("演示失败：" + e.message); }
  finally { setLoading(false); }
});

/* ---------- 报告列表 ---------- */
async function loadReportList() {
  try {
    const d = await api("/api/reports");
    const box = $("reportList");
    const list = d.reports || [];
    if (!list.length) { box.innerHTML = `<p class="hint">暂无。分析完成后会出现在这里。</p>`; return; }
    box.innerHTML = list.map((r) => `
      <div style="display:flex;align-items:center;gap:10px;border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:8px;background:#fbfcfe">
        <div style="flex:1">
          <div style="font-weight:600">${esc(r.title)}</div>
          <div class="meta" style="font-size:12px">${esc(r.source_name || "")} · ${esc(r.created_at || "")} · ${(r.stats && r.stats.total) || 0} 条 · ${(r.engine || []).join(" + ")}</div>
        </div>
        <button class="ghostbtn" data-open="${r.report_id}">打开</button>
      </div>`).join("");
    box.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", async () => {
      try { openReport(await api("/api/report/" + b.dataset.open)); }
      catch (e) { alert(e.message); }
    }));
  } catch (e) { /* 服务未就绪忽略 */ }
}

/* ---------- 打开报告 ---------- */
function openReport(rpt) {
  REPORT = rpt;
  ACTIVE = 0;
  buildFilterOptions();
  applyFilters(true);
  $("rTitle").textContent = rpt.title || "辨识报告";
  const meta = [];
  meta.push(`来源：${esc(rpt.source_name || "")}（${rpt.source_type || ""}）`);
  meta.push(`时间：${esc(rpt.created_at || "")}`);
  meta.push(`引擎：${(rpt.engine || []).map((x) => `<span class="chip brand">${esc(x)}</span>`).join(" ")}`);
  if (rpt.llm_info && rpt.llm_info.model) meta.push(`模型：${esc(rpt.llm_info.model)}`);
  if (rpt.truncated) meta.push(`<span class="chip" style="background:#ffe9e9;color:var(--hi)">条目已截断至上限</span>`);
  $("rMeta").innerHTML = meta.join("　");
  showReport();
  setView("overview");
}

/* ---------- 报告视图模式 ---------- */
function setView(v) {
  // 防御：未打开报告时点页签不应崩溃（曾报 Cannot read properties of null (reading 'flow')）
  if (!REPORT) { VIEW = "overview"; return; }
  VIEW = v;
  const lay = $("reportLayout"), fw = $("flowWrap"), tw = $("ftaWrap"), rw = $("robotWrap"),
        xw = $("refWrap"), dw = $("docWrap");
  const showLayout = (v === "overview" || v === "items");
  lay.style.display = showLayout ? "" : "none";
  fw.style.display = v === "flow" ? "" : "none";
  tw.style.display = v === "fta" ? "" : "none";
  rw.style.display = v === "robot" ? "" : "none";
  xw.style.display = v === "ref" ? "" : "none";
  dw.style.display = v === "doc" ? "" : "none";
  document.querySelectorAll("#modeBar .modebtn").forEach((b) => {
    b.classList.toggle("active", b.dataset.v === v);
  });
  if (v === "overview") { ACTIVE = 0; renderSideList(); renderCurrent(); }
  else if (v === "items") { renderSideList(); renderCurrent(); }
  else if (v === "flow") renderFlowView();
  else if (v === "fta") renderFtaView();
  else if (v === "robot") renderRobotView();
  else if (v === "ref") renderRefView();
  else if (v === "doc") renderDocView();
}

function jumpToItem(id) {
  if (!REPORT) return;
  const idx = REPORT.items.findIndex((x) => x.id === id);
  if (idx < 0) { alert("未找到条目 " + id); return; }
  // 重置过滤，确保该条可见
  ["filterText", "filterCategory", "filterSeverity", "filterSrc"].forEach((f) => { $(f).value = ""; });
  applyFilters(false);
  ACTIVE = idx + 1;
  setView("items");
  renderSideList();
  renderCurrent();
}
window.jumpToItem = jumpToItem;

/* 条目小按钮（流程/故障树面板复用） */
function miniItemBtn(id) {
  const it = (REPORT && REPORT.items || []).find((x) => x.id === id);
  if (!it) return "";
  return `<button class="mini-item inline" onclick="jumpToItem('${id}')"><span class="id">${id}</span> <span style="flex:1">${esc(it.title || "")}</span> ${sevTag(it.severity)} ${catTag(it.category)}</button>`;
}

function buildFilterOptions() {
  const sel = $("filterCategory");
  const opts = ['<option value="">类别：全部</option>'];
  (REPORT.stats.by_category ? Object.keys(REPORT.stats.by_category) : []).forEach((c) => {
    opts.push(`<option value="${esc(c)}">${esc(c)}（${REPORT.stats.by_category[c]}）</option>`);
  });
  sel.innerHTML = opts.join("");
}

function applyFilters(forceOverview) {
  if (!REPORT) return;
  const kw = $("filterText").value.trim().toLowerCase();
  const cat = $("filterCategory").value;
  const sev = $("filterSeverity").value;
  const src = $("filterSrc").value;
  FILTERED = (REPORT.items || []).filter((it) => {
    if (cat && it.category !== cat) return false;
    if (sev && String(it.severity) !== sev) return false;
    if (src && it.provenance !== src) return false;
    if (kw) {
      const blob = [it.title, it.unit, it.factor_desc, it.trigger_path, it.consequence,
        it.existing_controls, it.recommendations, (it.evidence || []).join(" ")].join(" ").toLowerCase();
      if (!blob.includes(kw)) return false;
    }
    return true;
  });
  if (ACTIVE > FILTERED.length) ACTIVE = 0;
  if (forceOverview) ACTIVE = 0;
  renderSideList();
  renderCurrent();
}

function renderSideList() {
  const box = $("sideList");
  if (!FILTERED.length) { box.innerHTML = `<div class="empty-msg">无匹配条目</div>`; return; }
  box.innerHTML = FILTERED.map((it, i) => `
    <button class="sideitem ${i + 1 === ACTIVE ? "active" : ""}" data-i="${i + 1}">
      <div class="t">${it.id} · ${esc(it.title || "(未命名)")}</div>
      <div class="m">${catTag(it.category)} ${sevTag(it.severity)} ${srcTag(it.provenance)}
        <span class="src-tag">${esc(it.unit || "")}</span></div>
    </button>`).join("");
  box.querySelectorAll(".sideitem").forEach((b) => b.addEventListener("click", () => {
    ACTIVE = Number(b.dataset.i); setView("items"); renderSideList(); renderCurrent();
  }));
}

/* ---------- 页面渲染 ---------- */
function renderCurrent() {
  if (!REPORT) return;
  if (ACTIVE === 0) {
    if (VIEW === "items") renderItemList();
    else renderOverview();
    return;
  }
  const it = FILTERED[ACTIVE - 1];
  if (!it) { (VIEW === "items") ? renderItemList() : renderOverview(); return; }
  renderItemPage(it, ACTIVE);
}

/* 条目总表（“条目列表”页签的首页，区别于概览） */
function renderItemList() {
  $("pageCrumb").textContent = `条目总表 · 第 0 页`;
  const rows = FILTERED.map((it, i) => `
    <tr data-i="${i + 1}" class="itemrow">
      <td class="id">${it.id}</td>
      <td>${catTag(it.category)}</td>
      <td>${sevTag(it.severity)}</td>
      <td>${srcTag(it.provenance)}</td>
      <td class="unit">${esc(it.unit || "")}</td>
      <td class="ttl">${esc(it.title || "")}</td>
    </tr>`).join("");
  $("pageBody").innerHTML = `
    <h3 style="margin:6px 0 10px">🗂 条目总表（当前筛选 <b>${FILTERED.length}</b> / 全部 ${(REPORT.items || []).length} 条）</h3>
    <p class="hint" style="margin:0 0 8px">点击任一行进入“一条目一页”详情；左侧可搜索与按类别/严重度/来源筛选（筛选后本表同步）。</p>
    <div class="itemtable-wrap"><table class="itemtable">
      <thead><tr><th>编号</th><th>类别</th><th>严重度</th><th>来源</th><th>所属单元</th><th>条目标题</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="6" class="hint">无匹配条目</td></tr>`}</tbody></table></div>`;
  $("pageBody").querySelectorAll(".itemrow").forEach((tr) => tr.addEventListener("click", () => {
    ACTIVE = Number(tr.dataset.i); renderSideList(); renderCurrent();
  }));
  $("pager").innerHTML = `<div></div><span class="mid">条目总表 · 共 ${FILTERED.length} 条</span><div></div>`;
}

function renderOverview() {
  $("pageCrumb").textContent = `第 0 页 · 报告概览`;
  const s = REPORT.stats || {};
  const cats = s.by_category || {};
  const sevs = s.by_severity || {};
  const maxCat = Math.max(1, ...Object.values(cats));
  const maxSev = Math.max(1, ...Object.values(sevs));
  // 每类的“平均严重度”，用于按风险深浅着色
  const catW = {};
  (REPORT.items || []).forEach((it) => {
    const c = it.category, w = SEVW[it.severity] || 0.5;
    catW[c] = catW[c] || { s: 0, n: 0 }; catW[c].s += w; catW[c].n += 1;
  });
  const catAvg = {}; let maxAvg = 1;
  Object.keys(catW).forEach((c) => { const a = catW[c].s / catW[c].n; catAvg[c] = a; if (a > maxAvg) maxAvg = a; });
  const bars = (obj, max, colorFn, tip) => Object.entries(obj).map(([k, v]) => {
    const color = colorFn(k, v);
    return `
    <div class="bar-row"><span class="lbl" title="${esc(tip ? tip(k) : k)}">${esc(k)}</span>
      <span class="track"><span class="fill" style="width:${(v / max * 100).toFixed(1)}%;background:${color}"></span></span>
      <span class="val">${v} 条</span></div>`;
  }).join("");
  const warn = (REPORT.warnings || []).map((w) => `<div class="warn-box">⚠️ ${esc(w)}</div>`).join("");

  // ---- 自动化/机器人摘要 ----
  const robots = REPORT.robots || [];
  const robotN = Object.entries(cats).find(([k]) => k === "自动化·机器人");
  const robotStat = robots.length
    ? `<div class="statbox"><div class="num" style="color:#6e40c9">${robots.length}</div><div class="lab">自动化装备（机器人）</div></div>` : "";
  const refStat = (REPORT.references && REPORT.references.length)
    ? `<div class="statbox"><div class="num" style="color:#0f7b6c">${REPORT.references.length}</div><div class="lab">参考文件 / 设计依据</div></div>` : "";
  const robotCard = robots.length
    ? `<div class="card" style="box-shadow:none">
        <h4 style="margin:0 0 8px">🤖 自动化装备与人员减少（点顶部“机器人”页查看每台详情）</h4>
        <div class="robot-kpis">
          <div class="robot-kpi"><div class="n" style="color:#6e40c9">${robots.length}</div><div class="l">机器人数</div></div>
          <div class="robot-kpi"><div class="n" style="color:var(--ok)">${(REPORT.stats && REPORT.stats.staff_reduced_total) || 0}</div><div class="l">减少操作人数合计</div></div>
          <div class="robot-kpi"><div class="n" style="color:var(--hi)">${robotN ? robotN[1] : 0}</div><div class="l">机器人相关条目</div></div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:6px">${robots.map((r) => `<span class="chip brand">${esc(r.name)} · ${esc(r.process)} · -${r.staff_reduced == null ? 0 : r.staff_reduced} 人</span>`).join("")}</div>
      </div>` : "";
  const unitsAll = REPORT.units || [];
  const procUnits = REPORT.process_units || [];
  const unitsCard = unitsAll.length
    ? `<div class="card" style="box-shadow:none;margin-top:10px">
        <h4 style="margin:0 0 8px">识别到的单元 / 章节（${unitsAll.length}${procUnits.length ? `）　其中工序/区域类 <b>${procUnits.length}</b>` : "）"}</h4>
        <div style="display:flex;flex-wrap:wrap;gap:6px">${unitsAll.slice(0, 60).map((u) => `<span class="chip gray">${esc(u)}</span>`).join("")}</div>
        ${unitsAll.length > 60 ? '<p class="hint">仅显示前 60 个</p>' : ""}
        <p class="hint" style="margin:6px 0 0">“单元/章节”含文档标题层级（如“一、基础信息”）；仅其中可映射为工序/区域的单元参与工序流程图与热力图行列。</p>
      </div>` : "";
  const refsAll = REPORT.references || [];
  const refsCard = refsAll.length
    ? `<div class="card" style="box-shadow:none;margin-top:10px">
        <h4 style="margin:0 0 8px">📚 参考文件 / 设计依据（${refsAll.length}，详见“参考文件”页）</h4>
        <div style="display:flex;flex-wrap:wrap;gap:6px">${refsAll.slice(0, 10).map((r) => `<span class="chip gray" title="${esc(r.text)}">${esc(r.text.length > 26 ? r.text.slice(0, 26) + "…" : r.text)}</span>`).join("")}</div>
      </div>` : "";

  // ---- 风险可视化数据（按工序/节点聚合） ----
  const heat = buildRiskRows();
  const heatHtml = heat.html;
  const rankHtml = heat.topHtml;

  $("pageBody").innerHTML = `
    <div class="stat-grid">
      <div class="statbox"><div class="num">${s.total || 0}</div><div class="lab">辨识条目总数</div></div>
      <div class="statbox"><div class="num">${Object.keys(cats).length}</div><div class="lab">涉及类别</div></div>
      <div class="statbox"><div class="num">${(REPORT.units || []).length}</div><div class="lab">识别单元/章节</div></div>
      <div class="statbox"><div class="num">${(s.by_provenance && s.by_provenance.doc) || 0}</div><div class="lab">工艺包自带条目</div></div>
      <div class="statbox"><div class="num">${(s.by_provenance && s.by_provenance.rule) || 0}</div><div class="lab">规则提炼条目</div></div>
      <div class="statbox"><div class="num">${(s.by_provenance && s.by_provenance.llm) || 0}</div><div class="lab">大模型增强条目</div></div>
      ${robotStat}
      ${refStat}
    </div>

    ${robotCard}

    <h3 style="margin:6px 0 2px">🔥 工序风险热力地图（哪道工序、哪类风险最容易出问题）</h3>
    <div class="legend">
      <span class="sw" style="background:#fff5f0"></span>无/低
      <span class="sw" style="background:#ffd6c6"></span>较低
      <span class="sw" style="background:#ff9e80"></span>中等
      <span class="sw" style="background:#e53935"></span>较高
      <span class="sw" style="background:#880f0f"></span>高
      <span style="margin-left:8px">红色越深＝该工序×该类别的风险加权越高（严重度加权：极高4/高3/中2/低1）</span>
    </div>
    ${heatHtml}

    <h3 style="margin:18px 0 2px">📈 工序风险排序（综合风险分，越高越需优先防控）</h3>
    ${rankHtml}

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="card" style="box-shadow:none"><h4 style="margin:0 0 8px">按类别分布<span class="hint" style="font-weight:400">（条长＝条数，颜色＝该类平均严重度，越红越高）</span></h4>${bars(cats, maxCat, (k) => riskRed((catAvg[k] || 1) / maxAvg), (k) => `${k}（平均严重度权重 ${(catAvg[k] || 0).toFixed(2)}）`)}</div>
      <div class="card" style="box-shadow:none"><h4 style="margin:0 0 8px">按严重度分布<span class="hint" style="font-weight:400">（颜色＝严重度等级）</span></h4>${bars(sevs, maxSev, (k) => sevColor(k))}
        <div class="legend" style="margin-top:8px">
          <span class="sw" style="background:${sevColor("极高")}"></span>极高
          <span class="sw" style="background:${sevColor("高")}"></span>高
          <span class="sw" style="background:${sevColor("中")}"></span>中
          <span class="sw" style="background:${sevColor("低")}"></span>低
          <span class="sw" style="background:${sevColor("待定")}"></span>待定
        </div>
      </div>
    </div>
    <div class="card" style="box-shadow:none;margin-top:14px">
      <h4 style="margin:0 0 6px">辨识步骤 / 方法说明</h4>
      <ul class="note-list">${(REPORT.method_notes || []).map((m) => `<li>${esc(m)}</li>`).join("")}</ul>
    </div>
    <div class="card" style="box-shadow:none;margin-top:10px">
      <h4 style="margin:0 0 6px">局限与待确认</h4>${warn || `<p class="hint">无明显提示。</p>`}
    </div>
    ${unitsCard}
    ${refsCard}
    <p class="hint" style="margin-top:12px">提示：顶栏“条目列表”为条目总表（可点行进入单页）；“报告预览”为可阅读报告（可下载 Word / 打印 PDF）；“工艺流程图 / 故障树 / 机器人 / 参考文件”为其余专题页。</p>`;
  $("pager").innerHTML = `<div></div>
    <span class="mid">概览页 · 共 ${FILTERED.length} 条匹配</span>
    <button class="primarybtn" onclick="goFirstItem()">查看第 1 条 →</button>`;
}

/* ---------- 风险热力/排序 数据 ---------- */
const SEVW = { "极高": 4, "高": 3, "中": 2, "低": 1, "待定": 0.5 };

/* 红色系色带：0=近白，1=深红（用于热力图/排序条） */
function riskRed(ratio) {
  ratio = Math.max(0, Math.min(1, Number(ratio) || 0));
  const stops = [[0, [255, 245, 240]], [0.25, [255, 214, 198]], [0.5, [255, 158, 128]],
                 [0.75, [229, 57, 53]], [1, [136, 15, 15]]];
  for (let i = 0; i < stops.length - 1; i++) {
    const [p0, c0] = stops[i], [p1, c1] = stops[i + 1];
    if (ratio <= p1) {
      const t = (ratio - p0) / (p1 - p0 || 1);
      const c = c0.map((v, k) => Math.round(v + (c1[k] - v) * t));
      return `rgb(${c[0]},${c[1]},${c[2]})`;
    }
  }
  return "rgb(136,15,15)";
}
function riskTextColor(ratio) { return ratio > 0.55 ? "#fff" : "#5a1a10"; }
function sevColor(s) {
  return { "极高": "#a10000", "高": "#d9200c", "中": "#e8890c", "低": "#1a7f37", "待定": "#8a94a6" }[s] || "#8a94a6";
}
function buildRiskRows() {
  const nodes = (REPORT.flow && REPORT.flow.nodes) || [];
  const rowMap = {};
  const init = () => ({ counts: { "极高": 0, "高": 0, "中": 0, "低": 0, "待定": 0 }, score: 0, catSev: {} });
  nodes.forEach((n) => { rowMap[n.name] = Object.assign({ name: n.name, type: n.type }, init()); });
  const genericName = "通用 / 全文档（未归属到工序的物料·作业等）";
  rowMap[genericName] = Object.assign({ name: genericName, type: "aux" }, init());

  (REPORT.items || []).forEach((it) => {
    const key = it.unit_node || "";
    const row = (key && rowMap[key]) ? rowMap[key] : rowMap[genericName];
    const sev = it.severity in SEVW ? it.severity : "待定";
    const w = SEVW[sev];
    row.counts[sev] = (row.counts[sev] || 0) + 1;
    row.score += w;
    row.catSev[it.category] = row.catSev[it.category] || { "极高": 0, "高": 0, "中": 0, "低": 0, "待定": 0 };
    row.catSev[it.category][sev] = (row.catSev[it.category][sev] || 0) + 1;
  });
  if (rowMap[genericName].score === 0) delete rowMap[genericName];

  const all = Object.values(rowMap);
  const rows = all.sort((a, b) => b.score - a.score);
  // 该工序（非通用）行
  const procRows = rows.filter((r) => r.name !== genericName && r.score > 0);
  const maxScore = Math.max(1, ...rows.map((r) => r.score));
  const maxProc = Math.max(1, ...procRows.map((r) => r.score));

  const allCats = [];
  rows.forEach((r) => Object.keys(r.catSev).forEach((c) => { if (!allCats.includes(c)) allCats.push(c); }));
  const catCols = CAT_ORDER.filter((c) => allCats.includes(c)).concat(allCats.filter((c) => !CAT_ORDER.includes(c)));
  // 单元格最大加权（用于颜色标定）
  let maxCell = 1;
  rows.forEach((r) => Object.values(r.catSev).forEach((m) => {
    let s = 0; Object.keys(m).forEach((k) => { s += (SEVW[k] || 0.5) * m[k]; }); if (s > maxCell) maxCell = s;
  }));

  function bg(w) {          // 红色系色度
    return riskRed(Math.min(1, w / (maxCell * 0.8)));
  }
  function cellLabel(m) {
    const parts = [];
    if ((m["高"] || 0) + (m["极高"] || 0) > 0) parts.push("高" + ((m["高"] || 0) + (m["极高"] || 0)));
    if (m["中"]) parts.push("中" + m["中"]);
    if (m["低"]) parts.push("低" + m["低"]);
    if (m["待定"]) parts.push("?" + m["待定"]);
    return parts.join(" ") || "–";
  }
  const thCats = catCols.map((c) => `<th>${esc(c)}</th>`).join("");
  const trs = rows.map((r) => {
    const tds = catCols.map((c) => {
      const m = r.catSev[c];
      if (!m) return `<td class="hcell" style="background:#fff;color:#bbb">–</td>`;
      let w = 0; Object.keys(m).forEach((k) => { w += (SEVW[k] || 0.5) * m[k]; });
      const ratio = Math.min(1, w / (maxCell * 0.8));
      return `<td class="hcell" style="background:${bg(w)};color:${riskTextColor(ratio)}">${cellLabel(m)}</td>`;
    }).join("");
    const chip = r.type === "main"
      ? `<span class="chip brand">主工序</span>`
      : `<span class="chip gray">${r.name.includes("通用") ? "其余" : "辅助"}</span>`;
    return `<tr><td class="rowlabel">${chip} ${esc(r.name)}</td>${tds}</tr>`;
  }).join("");

  const heatHtml = `<div class="heat-scroll"><table class="heat">
    <tr><th style="text-align:left">工序 / 单元</th>${thCats}</tr>${trs}</table></div>`;

  const rankRows = procRows.slice(0, 10);
  const topHtml = rankRows.map((r) => {
    const ratio = r.score / maxProc;
    return `
    <div class="bar-row"><span class="lbl" style="width:230px" title="${esc(r.name)}">${esc(r.name.length > 20 ? r.name.slice(0, 20) + "…" : r.name)}</span>
      <span class="track"><span class="fill" style="width:${(ratio * 100).toFixed(1)}%;background:${riskRed(ratio)}"></span></span>
      <span class="val" style="width:80px;color:${ratio > 0.6 ? "#a10000" : "#6b7686"}">${r.score.toFixed(0)} 分</span></div>`;
  }).join("") ||
    `<p class="hint">暂无工序级风险数据（条目未归属到工序）。</p>`;
  const genericNote = rowMap[genericName]
    ? `<p class="hint">注：另有 “通用/全文档” 聚合（${rowMap[genericName].score.toFixed(0)} 分）为未归属到具体工序的物料/SDS、作业等条目，未计入工序排序，详见热力地图末行与类别分布。</p>` : "";
  return { html: heatHtml, topHtml: topHtml + genericNote };
}

function renderItemPage(it, pos) {
  $("pageCrumb").textContent = `第 ${pos} 页 / 共 ${FILTERED.length} 条 · ${it.id}`;
  const ev = (it.evidence || []).filter((x) => x && String(x).trim()).map((x) => esc(x)).join("\n");
  $("pageBody").innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:14px">
      ${catTag(it.category)} ${sevTag(it.severity)} ${srcTag(it.provenance)}
      <span class="chip gray">可信度：${esc(it.confidence || "中")}</span>
      <span class="chip gray">单元：${esc(it.unit || "（未归属）")}</span>
    </div>
    <h3 style="margin:0 0 14px;line-height:1.4">${it.id}　${esc(it.title || "(未命名)")}</h3>
    ${kv("危险有害因素（factor）", it.factor_desc)}
    ${kv("触发 / 失效路径（trigger）", it.trigger_path)}
    ${kv("可能后果（consequence）", it.consequence)}
    ${kv("已有控制 / 防护（existing）", it.existing_controls)}
    ${kv("建议措施 / 待专项确认（recommendation）", it.recommendations)}
    ${it.source ? `<div class="kv-block"><div class="kv-title">来源出处</div><div class="kv-content">${esc(it.source)}</div></div>` : ""}
    ${ev ? `<div class="kv-block"><div class="kv-title">原文证据</div><div class="evidence">${ev}</div></div>` : ""}`;
  $("pager").innerHTML = `
    <span>
      ${VIEW === "items" ? `<button class="ghostbtn" id="backList">🗂 总表</button>` : ""}
      <button class="ghostbtn" ${pos <= 1 ? "disabled" : ""} id="prevItem">← 上一条</button>
    </span>
    <span class="mid">第 ${pos} / ${FILTERED.length} 条 · ${it.id}</span>
    <button class="ghostbtn" ${pos >= FILTERED.length ? "disabled" : ""} id="nextItem">下一条 →</button>`;
  const back = $("backList");
  if (back) back.addEventListener("click", () => { ACTIVE = 0; renderSideList(); renderCurrent(); });
  const prev = $("prevItem"), next = $("nextItem");
  if (prev) prev.addEventListener("click", () => { ACTIVE = Math.max(0, pos - 1); renderSideList(); renderCurrent(); });
  if (next) next.addEventListener("click", () => { ACTIVE = Math.min(FILTERED.length, pos + 1); renderSideList(); renderCurrent(); });
  $("pageBody").scrollIntoView({ block: "start", behavior: "smooth" });
}
window.goFirstItem = function () { if (FILTERED.length) { ACTIVE = 1; setView("items"); renderSideList(); renderCurrent(); } };

/* ---------- 过滤事件 ---------- */
["filterText", "filterCategory", "filterSeverity", "filterSrc"].forEach((id) => {
  $(id).addEventListener("input", () => applyFilters(false));
  $(id).addEventListener("change", () => applyFilters(false));
});
$("btnOverview").addEventListener("click", () => setView("overview"));
$("btnNew").addEventListener("click", () => { REPORT = null; FILTERED = []; $("txtArea").value = ""; pickedFile = null; $("fileInput").value = ""; updateFileMeta(); showInput(); });
/* 模式栏 */
document.querySelectorAll("#modeBar .modebtn").forEach((b) => b.addEventListener("click", () => setView(b.dataset.v)));

/* ---------- 导出 / 打印 ---------- */
$("btnExport").addEventListener("click", async () => {
  if (!REPORT) return;
  try {
    const res = await fetch("/api/export/" + REPORT.report_id);
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `辨识报告_${REPORT.source_name || "report"}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) { alert("导出失败：" + e.message); }
});
$("btnPrint").addEventListener("click", () => window.print());

/* ---------- 工艺流程图（交互式） ---------- */
let _flowSel = null;
function flowColor(risk) {
  if (risk === "极高" || risk === "高") return { fill: "#fdecea", stroke: "#cf222e" };
  if (risk === "中") return { fill: "#fff3e0", stroke: "#bc4c00" };
  if (risk === "低") return { fill: "#e6f6ec", stroke: "#1a7f37" };
  return { fill: "#f4f6fa", stroke: "#6b7686" };
}
function renderFlowView() {
  const fl = REPORT.flow;
  if (!fl || !fl.nodes.length) {
    $("flowCanvas").innerHTML = `<div class="empty-msg">未能从文档抽取到工序流程（建议上传含风险场景表/工段标题的工艺包）。</div>`;
    $("flowDetail").innerHTML = ""; $("flowNote").textContent = "";
    return;
  }
  $("flowNote").innerHTML = `📌 ${esc(fl.note || "")}　<b>操作：点击任意工序节点</b>，下方显示该工序的主要工作内容与相关风险信息；` +
    `<span class="chip gray">主工序</span> 主链按“蛇形折行”自动排版（无需左右拖动），` +
    `<span class="chip gray">辅助</span> 单列于下方，橙色虚线为“循环/回用”；节点内三段色条＝高/中/低风险条数。`;

  const mains = fl.nodes.filter((n) => n.type === "main");
  const auxs = fl.nodes.filter((n) => n.type === "aux");
  const canvas = $("flowCanvas");
  const W = Math.max(680, (canvas.clientWidth || 1000) - 26);   // 留出边距，确保不出现横向滚动
  const BW = 178, BH = 84, GX = 34, GY = 66, PAD = 18;
  const cols = Math.max(2, Math.floor((W - PAD * 2 + GX) / (BW + GX)));
  const rows = Math.max(1, Math.ceil(mains.length / cols));
  const pos = {};
  const nodeById = {};
  fl.nodes.forEach((n) => { nodeById[n.id] = n; });

  // 主链：蛇形（奇数行反向），行末折到下一行
  mains.forEach((n, i) => {
    const r = Math.floor(i / cols), c = i % cols;
    const cc = (r % 2 === 0) ? c : (cols - 1 - c);
    pos[n.id] = { x: PAD + cc * (BW + GX), y: PAD + r * (BH + GY), w: BW, h: BH };
  });
  const mainBottom = PAD + rows * (BH + GY) + 6;
  // 辅助节点：网格（最多 5 列）
  const auxCols = Math.max(2, Math.min(5, cols));
  auxs.forEach((n, i) => {
    const r = Math.floor(i / auxCols), c = i % auxCols;
    pos[n.id] = { x: PAD + c * (BW + GX), y: mainBottom + 42 + r * (BH + GY), w: BW, h: BH };
  });
  const auxRows = auxs.length ? Math.ceil(auxs.length / auxCols) : 0;
  const height = mainBottom + (auxs.length ? 42 + auxRows * (BH + GY) : 0) + 26;

  // 严重度小计（用于节点内色条）
  const sevMap = {};
  (REPORT.items || []).forEach((it) => { sevMap[it.id] = it.severity; });
  const counts = (n) => {
    const c = { high: 0, med: 0, low: 0 };
    (n.item_ids || []).forEach((id) => {
      const s = sevMap[id];
      if (s === "极高" || s === "高") c.high++; else if (s === "中") c.med++; else c.low++;
    });
    return c;
  };

  const connector = (a, b) => {
    if (Math.abs(a.y - b.y) < 4) {                    // 同一行：水平连
      const dir = b.x > a.x ? 1 : -1;
      const x1 = a.x + (dir > 0 ? a.w : 0), y1 = a.y + a.h / 2;
      const x2 = b.x + (dir > 0 ? 0 : b.w), y2 = b.y + b.h / 2;
      return `<path class="fedge" d="M${x1},${y1} L${x2},${y2}"></path>`;
    }
    // 换行：自底部弯到下一行顶部
    const x1 = a.x + a.w / 2, y1 = a.y + a.h, x2 = b.x + b.w / 2, y2 = b.y;
    const my = (y1 + y2) / 2;
    return `<path class="fedge" d="M${x1},${y1} C ${x1},${my} ${x2},${my} ${x2},${y2}"></path>`;
  };

  let svg = `<svg width="${W}" height="${height}" viewBox="0 0 ${W} ${height}">
    <defs><marker id="arrow" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto">
      <path d="M0,0 L9,4 L0,8 z" fill="#6b7686"/></marker></defs>`;
  // 主链相邻连线（不含回流）
  for (let i = 0; i < mains.length - 1; i++) {
    svg += connector(pos[mains[i].id], pos[mains[i + 1].id]);
  }
  // 循环/回流虚线（绕到图底部）
  (fl.edges || []).filter((e) => e.dashed).forEach((e) => {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) return;
    const y = height - 14, ax = a.x + a.w / 2, bx = b.x + b.w / 2;
    svg += `<path class="fedge dash" d="M${ax},${a.y + a.h} C ${ax},${y} ${bx},${y} ${bx},${b.y + b.h}"></path>`;
    svg += `<text class="fedgelab" x="${(ax + bx) / 2}" y="${y - 3}" text-anchor="middle">${esc(e.label || "循环/回用")}</text>`;
  });
  // 节点（含严重度色条）
  fl.nodes.forEach((n) => {
    const p = pos[n.id]; const c = flowColor(n.risk);
    const sel = _flowSel === n.id;
    const nm = n.name; const t1 = nm.slice(0, 9), t2 = nm.length > 9 ? nm.slice(9, 20) : "";
    const cn = counts(n); const total = cn.high + cn.med + cn.low || 1;
    const barX = p.x + 10, barY = p.y + p.h - 15, barW = p.w - 20;
    const w1 = barW * cn.high / total, w2 = barW * cn.med / total, w3 = barW * cn.low / total;
    svg += `<g class="fnode ${sel ? "selected" : ""}" data-id="${n.id}">
      <rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="10"
        fill="${c.fill}" stroke="${sel ? "#1f6feb" : c.stroke}" stroke-width="${sel ? 3 : 1.6}"></rect>
      <text x="${p.x + p.w / 2}" y="${p.y + (t2 ? 25 : 33)}" text-anchor="middle">${esc(t1)}</text>
      ${t2 ? `<text x="${p.x + p.w / 2}" y="${p.y + 42}" text-anchor="middle">${esc(t2)}</text>` : ""}
      <text x="${p.x + p.w / 2}" y="${p.y + p.h - 24}" text-anchor="middle" style="font-size:10px;fill:#6b7686">${n.n_items || 0} 条风险 · 高${cn.high}/中${cn.med}/低${cn.low}</text>
      <rect x="${barX}" y="${barY}" width="${barW}" height="5" rx="2.5" fill="#eef1f6"></rect>
      <rect x="${barX}" y="${barY}" width="${w1}" height="5" rx="2.5" fill="${sevColor("高")}"></rect>
      <rect x="${barX + w1}" y="${barY}" width="${w2}" height="5" fill="${sevColor("中")}"></rect>
      <rect x="${barX + w1 + w2}" y="${barY}" width="${w3}" height="5" fill="${sevColor("低")}"></rect>
    </g>`;
  });
  if (auxs.length) {
    svg += `<text x="${PAD}" y="${mainBottom + 22}" style="font-size:12px;fill:#6b7686">辅助 / 外围节点（储存、公用、三废、消防等，不入主链）</text>`;
  }
  svg += `</svg>`;
  canvas.innerHTML = svg;
  canvas.querySelectorAll(".fnode").forEach((g) => {
    g.addEventListener("click", () => { _flowSel = g.dataset.id; renderFlowView(); });
  });
  if (!_flowSel) _flowSel = (mains[0] || fl.nodes[0]).id;
  renderFlowDetail();
}
function renderFlowDetail() {
  const fl = REPORT.flow; const node = fl.nodes.find((n) => n.id === _flowSel);
  if (!node) { $("flowDetail").innerHTML = ""; return; }
  const itemBtn = (id) => { const it = REPORT.items.find((x) => x.id === id); return it
    ? `<button class="mini-item" onclick="jumpToItem('${id}')"><span class="id">${id}</span> <span style="flex:1">${esc(it.title || "")}</span> ${sevTag(it.severity)} ${catTag(it.category)}</button>`
    : ""; };
  $("flowDetail").innerHTML = `
    <h3 style="margin:0 0 8px">工序：${esc(node.name)}
      <span class="chip brand">${esc(node.type === "main" ? "主工序" : "辅助")}</span> ${sevTag(node.risk)}
      <span class="chip gray">${node.n_items || 0} 条相关辨识</span>
      ${((REPORT.robots || []).filter((r) => r.process === node.name)).map((r) => `<span class="chip" style="background:#f0e9ff;color:#6e40c9">🤖 ${esc(r.name)}（-${r.staff_reduced == null ? 0 : r.staff_reduced} 人）</span>`).join(" ")}</h3>
    <div class="kv-block"><div class="kv-title">主要工作内容（自动摘要，供参考）</div>
      <div class="kv-content">${esc(node.desc || "（文档中未定位到描述）")}</div></div>
    <div class="kv-block"><div class="kv-title">该工序相关风险信息（点击条目直达其详情页）</div>
      <div>${(node.item_ids || []).map(itemBtn).join("") || `<p class="hint">暂无条目归属该工序。</p>`}</div></div>`;
}

/* ---------- 机器人（自动化装备）名录 ---------- */
let _robotSel = 0;
function renderRobotView() {
  const robots = (REPORT && REPORT.robots) || [];
  const note = $("robotNote"), nav = $("robotNav"), body = $("robotBody");
  if (!robots.length) {
    note.textContent = "";
    nav.innerHTML = "";
    body.innerHTML = `<div class="empty-msg">本文档未识别到机器人/自动化装备台账。<br><span class="hint">需在文档中提供含“机器人名称 + 负责工序（+ 原/现操作人数、机器人可能新增风险）”的台账表或机器人小节。</span></div>`;
    return;
  }
  const total = robots.reduce((s, r) => s + (r.staff_reduced || 0), 0);
  note.innerHTML = `🤖 机器人/自动化装备名录：共 <b>${robots.length}</b> 台，替代人工共减少操作约 <b>${total}</b> 人。` +
    `每台机器人<b>一条目一页</b>（左侧切换）：负责工序 / 工序内容 / 减少操作人数 / 该工序风险因素 / 机器人可能新增风险 / 更改后避免的风险 / 防爆与安全要求 / 关联辨识条目。`;
  if (_robotSel >= robots.length) _robotSel = 0;
  nav.innerHTML = robots.map((r, i) => `
    <button class="robot-navitem ${i === _robotSel ? "active" : ""}" data-i="${i}">
      <div class="nm">🤖 ${esc(r.name)}</div>
      <div class="sub">${esc(r.process)} · 减少 ${r.staff_reduced == null ? "—" : r.staff_reduced} 人 · 新增风险 ${r.robot_risks.length}</div>
    </button>`).join("");
  nav.querySelectorAll(".robot-navitem").forEach((b) => b.addEventListener("click", () => { _robotSel = Number(b.dataset.i); renderRobotView(); }));

  const r = robots[_robotSel];
  const list = (arr, cls) => (arr && arr.length)
    ? `<ul class="risklist">${arr.map((x) => `<li class="${cls}">${esc(x)}</li>`).join("")}</ul>`
    : `<p class="hint">（原文未明确）</p>`;
  const staffTxt = (r.staff_before != null && r.staff_after != null) ? `${r.staff_before} → ${r.staff_after} 人` : "—";
  body.innerHTML = `
   <div class="pagehead"><span class="crumb">${r.id} · ${esc(r.name)}</span><div style="flex:1"></div>
     <button class="ghostbtn" id="rbPrev" ${_robotSel <= 0 ? "disabled" : ""}>← 上一台</button>
     <button class="ghostbtn" id="rbNext" ${_robotSel >= robots.length - 1 ? "disabled" : ""}>下一台 →</button></div>
   <div class="pagebody">
     <h3 style="margin:0 0 10px">${esc(r.name)} <span class="chip gray">${esc(r.type || "机器人")}</span>
       <span class="chip brand">${esc(r.process)}</span>${r.ex_level ? ` <span class="chip gray">${esc(r.ex_level)}</span>` : ""}</h3>
     <div class="robot-kpis">
       <div class="robot-kpi"><div class="n">${staffTxt}</div><div class="l">操作人数（改造前→后）</div></div>
       <div class="robot-kpi"><div class="n" style="color:var(--ok)">-${r.staff_reduced == null ? "—" : r.staff_reduced}</div><div class="l">减少操作人数</div></div>
       <div class="robot-kpi"><div class="n" style="color:var(--hi)">${r.robot_risks.length}</div><div class="l">机器人新增风险项</div></div>
       <div class="robot-kpi"><div class="n" style="color:var(--ok)">${r.avoided.length}</div><div class="l">避免/降低风险项</div></div>
     </div>
     <div class="kv-block"><div class="kv-title">负责工序与工序内容</div>
       <div class="kv-content">${esc(r.process)}：${esc(r.task || "（原文未明确）")}</div></div>
     ${(r.specs && r.specs.length) ? `<div class="kv-block"><div class="kv-title">选型参数</div>
       <table class="spectable">${r.specs.map((s) => `<tr><th>${esc(s.k)}</th><td>${esc(s.v)}</td></tr>`).join("")}</table></div>` : ""}
     ${(r.selection && r.selection.length) ? `<div class="kv-block"><div class="kv-title">选型说明（原文摘录）</div>
       <ul class="risklist">${r.selection.map((s) => `<li class="info">${esc(s)}</li>`).join("")}</ul></div>` : ""}
     ${(r.images && r.images.length) ? `<div class="kv-block"><div class="kv-title">选型图片 / 图样</div>
       <div class="robot-imgs">${r.images.map((im) => `<figure class="robot-img"><img src="/api/media/${REPORT.report_id}/${encodeURI(im.path)}" alt="${esc(im.caption || im.path)}" onerror="this.style.display='none';this.parentElement.insertAdjacentHTML('beforeend','<div class=\\'hint\\'>图片不可用（需用“按路径分析/演示”方式打开含图工艺包）</div>')"><figcaption>${esc(im.caption || im.path)}</figcaption></figure>`).join("")}</div></div>` : ""}
     <div class="kv-block"><div class="kv-title">该工序风险因素（改造前存在）</div>${list(r.proc_risks, "warn")}</div>
     <div class="kv-block"><div class="kv-title">机器人可能导致的风险因素（新增）</div>${list(r.robot_risks, "bad")}</div>
     <div class="kv-block"><div class="kv-title">更改后避免 / 降低的风险</div>${list(r.avoided, "good")}</div>
     <div class="kv-block"><div class="kv-title">防爆与安全要求</div>${list(r.safety, "info")}</div>
     <div class="kv-block"><div class="kv-title">关联辨识条目（点击直达）</div>
       <div>${(r.item_ids || []).map(miniItemBtn).join("") || '<p class="hint">无</p>'}</div></div>
     <div class="kv-block"><div class="kv-title">来源</div><div class="kv-content">${esc(r.source || "")}</div></div>
   </div>`;
  const p = $("rbPrev"), n = $("rbNext");
  if (p) p.addEventListener("click", () => { _robotSel = Math.max(0, _robotSel - 1); renderRobotView(); });
  if (n) n.addEventListener("click", () => { _robotSel = Math.min(robots.length - 1, _robotSel + 1); renderRobotView(); });
}

/* ---------- 参考文件 / 设计依据 ---------- */
function renderRefView() {
  const refs = (REPORT && REPORT.references) || [];
  const note = $("refNote"), body = $("refBody");
  if (!refs.length) {
    note.textContent = "";
    body.innerHTML = `<div class="empty-msg">未识别到参考文件/设计依据。<br><span class="hint">可在工艺包中加入“设计依据 / 参考文件 / 引用标准”小节，或正文含 GB、HG、AQ、ISO、《…》等条目。</span></div>`;
    return;
  }
  const groups = {};
  refs.forEach((r) => { (groups[r.type] = groups[r.type] || []).push(r); });
  const order = ["标准/规范", "规范/文献", "参考书/手册", "其他依据"];
  note.innerHTML = `📚 参考文件与设计依据：共 <b>${refs.length}</b> 项。自动从“设计依据/参考文件”小节与全文 GB/HG/AQ/ISO、《…》等识别，**需人工核对现行有效版本**；点击可在下方查看来源位置。`;
  body.innerHTML = order.filter((t) => groups[t]).map((t) => `
    <div class="card" style="box-shadow:none;margin-bottom:12px">
      <h4 style="margin:0 0 8px">${esc(t)} <span class="chip gray">${groups[t].length}</span></h4>
      <ul class="reflist">${groups[t].map((r) => `<li>${esc(r.text)} <span class="hint">（${esc(r.section || "全文")} · 第${r.line}行）</span></li>`).join("")}</ul>
    </div>`).join("");
}

/* ---------- 可阅读报告预览 ---------- */
function renderDocView() {
  if (!REPORT) return;
  const base = `/api/report/${REPORT.report_id}/document`;
  const htmlUrl = base + "?format=html";
  const fr = $("docFrame");
  if (fr.getAttribute("src") !== htmlUrl) fr.setAttribute("src", htmlUrl);
  const w = $("btnDocWord");
  if (w) w.setAttribute("href", base + "?format=docx");
  const op = $("btnDocOpen");
  if (op) op.onclick = () => window.open(htmlUrl, "_blank");
  const pr = $("btnDocPrint");
  if (pr) pr.onclick = () => {
    try { fr.contentWindow.focus(); fr.contentWindow.print(); }
    catch (e) { window.open(htmlUrl, "_blank"); }
  };
}

/* ---------- 故障树 FTA（数据驱动初筛） ---------- */
let _ftaSel = null;
const _ftaCollapsed = new Set();
function _ftaMap(node, m) { if (!node) return m; m[node.id] = node; (node.children || []).forEach((c) => _ftaMap(c, m)); return m; }
function _ftaNodeHtml(n) {
  const kids = n.children || [];
  const hasKids = kids.length > 0;
  const collapsed = _ftaCollapsed.has(n.id);
  const sev = (n.type !== "gap" && n.type !== "top") ? sevTag(n.severity) : "";
  const gate = n.gate ? `<span class="gate-badge">${esc(n.gate) === "or" ? "或门 OR" : "与门 AND"}</span>` : "";
  const toggle = hasKids ? `<span class="toggle">${collapsed ? "▶" : "▼"}</span>` : "";
  const kidsHtml = hasKids && !collapsed
    ? `<ul id="kids-${n.id}">${kids.map((c) => `<li>${_ftaNodeHtml(c)}</li>`).join("")}</ul>`
    : "";
  return `<div class="tnode ${n.type} ${_ftaSel === n.id ? "sel" : ""}" data-id="${n.id}">${toggle}<span>${esc(n.name)}</span>${sev}${gate}</div>${kidsHtml}`;
}
function renderFtaView() {
  const ft = REPORT.fault_tree;
  if (!ft || !ft.tree) { $("ftaTree").innerHTML = ""; $("ftaNote").textContent = "无故障树数据。"; return; }
  $("ftaNote").innerHTML = `🌳 ${esc(ft.note || "")}　<b>操作：点击节点展开/收起并查看详情</b>；
    <span class="tag" style="background:#0f1b2d;color:#fff">顶事件</span>
    <span class="tag" style="background:#e8f0fe;color:var(--brand)">工序中间事件</span>
    <span class="tag" style="background:#fff0e0;color:#bc4c00">风险场景(或门)</span>
    <span class="tag" style="background:#fbf5ff;color:#8250df">工序间传递</span>
    <span class="tag" style="background:#eef1f6;color:#44506a">底事件</span>
    <span class="tag" style="background:#fff;color:#cf222e;border:1px dashed #cf222e">待补/缺口</span>`;

  // 工序间故障/风险传递关系（前工序 → 后工序）
  const links = ft.cross_links || [];
  $("ftaCross").innerHTML = links.length ? (
    `<h4>🔗 工序间故障 / 风险传递关系（上游 → 下游）</h4>` +
    links.map((l) => `
      <div class="crossrow">
        <div class="crossflow">${esc(l.from)}<span class="crossarrow">→</span>${esc(l.to)}
          <span class="chip gray">经由：${esc(l.via || "中间物料")}</span></div>
        <div class="crosstext">${esc(l.note || "")}</div>
        <div>${(l.upstream_events || []).map((e) => miniItemBtn(e.id)).join("")}</div>
      </div>`).join("")
  ) : "";

  const map = _ftaMap(ft.tree, {});
  $("ftaTree").innerHTML = `<li class="root">${_ftaNodeHtml(ft.tree)}</li>`;
  $("ftaTree").querySelectorAll(".tnode").forEach((el) => {
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const id = el.dataset.id; const n = map[id];
      if (!n) return;
      _ftaSel = id;
      // 展开/收起
      if (n.children && n.children.length) {
        if (_ftaCollapsed.has(id)) { _ftaCollapsed.delete(id); } else { _ftaCollapsed.add(id); }
      }
      renderFtaView();
      renderFtaDetail(n);
    });
  });
  renderFtaDetail(map[_ftaSel] || ft.tree);
}
function renderFtaDetail(n) {
  if (!n) return;
  const itemBtn = (id) => { const it = REPORT.items.find((x) => x.id === id); return it
    ? `<button class="mini-item" onclick="jumpToItem('${id}')"><span class="id">${id}</span> <span style="flex:1">${esc(it.title || "")}</span> ${sevTag(it.severity)} ${catTag(it.category)}</button>`
    : ""; };
  const kids = n.children || [];
  $("ftaDetail").innerHTML = `
    <h3 style="margin:0 0 8px">${esc(n.name)}
      <span class="chip gray">${esc(n.type === "top" ? "顶事件" : n.type === "mid" ? "中间事件" : n.type === "event" ? "风险场景" : n.type === "leaf" ? "底事件" : "缺口")}</span>
      ${n.gate ? `<span class="gate-badge">${esc(n.gate) === "or" ? "或门 OR" : "与门 AND"}</span>` : ""}
      ${sevTag(n.severity)} ${n.unit ? `<span class="chip gray">${esc(n.unit)}</span>` : ""}</h3>
    ${n.note ? `<div class="kv-content" style="margin-bottom:8px">${esc(n.note)}</div>` : ""}
    <div class="kv-title">关联辨识条目（${(n.item_ids || []).length}）</div>
    <div>${(n.item_ids || []).map(itemBtn).join("") || `<p class="hint">暂无直接关联条目。</p>`}</div>
    <div class="hint" style="margin-top:6px">下级子事件 ${kids.length} 个${n.type === "top" ? "：下方任一工序风险子树触发即构成顶事件（简化或门）" : ""}。</div>`;
}

/* ---------- 配置弹窗 ---------- */
window.openCfg = async function () {
  try {
    const c = await api("/api/config");
    const llm = c.llm || {};
    $("cfgBase").value = llm.base_url || "";
    $("cfgModel").value = llm.model || "";
    $("cfgKey").value = "";
    $("cfgKey").placeholder = llm.api_key ? "(已设置，留空不修改)" : "sk-…";
    $("cfgDemo").value = c.demo_package_path || "";
  } catch (e) { /* ignore */ }
  $("cfgMask").classList.add("show");
};
window.closeCfg = function () { $("cfgMask").classList.remove("show"); };
$("btnConfig").addEventListener("click", openCfg);
$("cfgMask").addEventListener("click", (e) => { if (e.target === $("cfgMask")) closeCfg(); });
$("btnSaveCfg").addEventListener("click", async () => {
  const body = {
    llm: {
      base_url: $("cfgBase").value.trim(),
      api_key: $("cfgKey").value.trim(),
      model: $("cfgModel").value.trim(),
    },
    demo_package_path: $("cfgDemo").value.trim(),
  };
  try {
    await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    alert("配置已保存");
    closeCfg();
  } catch (e) { alert("保存失败：" + e.message); }
});

/* ---------- 启动 ---------- */
showInput();
