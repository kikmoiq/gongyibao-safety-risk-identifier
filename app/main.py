# -*- coding: utf-8 -*-
"""本地部署：工艺包安全风险辨识系统 Demo —— FastAPI 入口。

REST 接口（供前端与其他程序调用）：
  GET  /api/health                 健康检查
  GET  /api/config                 读配置（key 打码）
  POST /api/config                 写配置（LLM base_url/key/model…；key 留空=保留原值）
  POST /api/analyze/text           分析粘贴文本        {text, filename?, use_llm?}
  POST /api/analyze/upload         分析上传 .md/.docx  (multipart: file, use_llm?)
  GET  /api/analyze/demo           分析演示样例(己二腈工艺包本地文件, 若配置存在)
  GET  /api/reports                报告列表
  GET  /api/report/{id}            取整份报告 JSON
  GET  /api/report/{id}/items      条目分页（page,size 默认全量）
  DELETE /api/report/{id}          删除报告
  GET  /api/export/{id}            导出报告 JSON 文件

启动：python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config as conf
from .engine import orchestrator, ingest, reportdoc

BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parent
STATIC_DIR = ROOT / "static"
INDEX_HTML = STATIC_DIR / "index.html"

app = FastAPI(title="工艺包安全风险辨识系统", version="0.3.1-demo")

# 报告内存存储：{report_id: report_dict}
_REPORTS: dict[str, dict] = {}
_REPORTS_LOCK = threading.Lock()


class TextReq(BaseModel):
    text: str
    filename: str = ""
    use_llm: bool = False


class PathReq(BaseModel):
    path: str
    use_llm: bool = False


# ---------------- 页面 ----------------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    if not INDEX_HTML.exists():
        return JSONResponse({"error": "前端文件缺失"}, status_code=500)
    return FileResponse(str(INDEX_HTML))


# ---------------- 基础 ----------------
@app.get("/api/health")
def health():
    return {"status": "ok", "name": "工艺包安全风险辨识系统", "version": "0.3.1-demo",
            "build": "2026-09-10"}


# ---------------- 配置 ----------------
@app.get("/api/config")
def get_config():
    return conf.public_view(conf.load())


@app.post("/api/config")
def set_config(body: dict):
    cfg = conf.load()
    llm_new = (body.get("llm") or {}) if isinstance(body.get("llm"), dict) else {}
    llm_cur = cfg.get("llm", {})
    key = str(llm_new.get("api_key", "")).strip()
    if key:
        llm_cur["api_key"] = key          # 有新 key 才更新
    elif body.get("clear_key"):
        llm_cur["api_key"] = ""           # 显式清空
    for f in ("base_url", "model"):
        if f in llm_new and str(llm_new[f]).strip():
            llm_cur[f] = str(llm_new[f]).strip()
    for f in ("enabled", "temperature", "max_tokens", "max_excerpt_chars"):
        if f in llm_new:
            llm_cur[f] = llm_new[f]
    if "demo_package_path" in body:
        cfg["demo_package_path"] = str(body["demo_package_path"]).strip()
    saved = conf.save({"llm": llm_cur, "demo_package_path": cfg.get("demo_package_path", "")})
    return {"ok": True, "config": conf.public_view(saved)}


# ---------------- 分析 ----------------
def _run_analysis(text: str, name: str, stype: str, use_llm: bool, source_dir: str = None) -> dict:
    cfg = conf.load()
    rpt = orchestrator.analyze(text=text, source_name=name, source_type=stype,
                               use_llm=use_llm, cfg=cfg, source_dir=source_dir)
    with _REPORTS_LOCK:
        _REPORTS[rpt["report_id"]] = rpt
    return rpt


@app.post("/api/analyze/path")
def analyze_path(req: PathReq):
    """分析本地文件（.md/.docx）：与上传相比，可保留源目录以便展示工艺包内图片。"""
    p = Path(req.path)
    if not p.exists():
        raise HTTPException(404, f"文件不存在: {req.path}")
    ext = p.suffix.lower()
    if ext == ".docx":
        text, name = ingest.read_source(str(p), "docx")
        stype = "docx"
    else:
        text, name = ingest.read_source(str(p), "md")
        stype = "md"
    return _run_analysis(text, name, stype, req.use_llm, source_dir=str(p.parent))


@app.get("/api/media/{rid}/{rel:path}")
def media(rid: str, rel: str):
    """提供报告源文件目录下的图片（供机器人选型图等展示），限定在源目录内。"""
    with _REPORTS_LOCK:
        rpt = _REPORTS.get(rid)
    if not rpt or not rpt.get("source_dir"):
        raise HTTPException(404, "该报告未关联源目录（请用“按路径分析”或演示方式）")
    base = Path(rpt["source_dir"]).resolve()
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(403, "越权路径")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "图片不存在")
    import mimetypes
    mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(str(target), media_type=mime)


@app.post("/api/analyze/text")
def analyze_text(req: TextReq):
    if not req.text.strip():
        raise HTTPException(400, "文本为空")
    text, name = ingest.read_source(req.text, "text", filename=req.filename or "粘贴文本")
    return _run_analysis(text, name, "text", req.use_llm)


@app.post("/api/analyze/upload")
async def analyze_upload(file: UploadFile = File(...), use_llm: bool = Form(False)):
    fn = (file.filename or "upload").strip()
    ext = Path(fn).suffix.lower()
    data = await file.read()
    if not data:
        raise HTTPException(400, "上传文件为空")
    if ext == ".docx":
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
            tf.write(data)
            tmp = tf.name
        try:
            text, name = ingest.read_source(tmp, "docx")
        finally:
            Path(tmp).unlink(missing_ok=True)
        stype = "docx"
    elif ext in (".md", ".markdown", ".txt", ".text"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("gb18030", errors="replace")
        text = ingest.normalize_markdown(text)
        name = Path(fn).stem
        stype = "md" if ext == ".md" else "txt"
    else:
        raise HTTPException(400, f"不支持的文件类型: {ext}（支持 .md/.txt/.docx）")
    return _run_analysis(text, name, stype, use_llm)


@app.get("/api/analyze/demo")
def analyze_demo(use_llm: bool = False):
    cfg = conf.load()
    path = str(cfg.get("demo_package_path") or "").strip()
    if path and Path(path).exists():
        text, name = ingest.read_source(path, "md")
        stype, extra = "demo", f"演示数据源：{path}"
        return _run_analysis(text, name, stype, use_llm, source_dir=str(Path(path).parent))
    # 内置精简演示样例
    sample = ROOT / "data" / "演示样例_工艺包.md"
    if not sample.exists():
        raise HTTPException(404, "未找到演示样例")
    text, name = ingest.read_source(str(sample), "md")
    return _run_analysis(text, name, "demo", use_llm, source_dir=str(sample.parent))


# ---------------- 报告 ----------------
@app.get("/api/reports")
def list_reports():
    with _REPORTS_LOCK:
        items = [
            {
                "report_id": r["report_id"],
                "title": r["title"],
                "source_name": r["source_name"],
                "source_type": r["source_type"],
                "created_at": r.get("created_at"),
                "engine": r.get("engine", []),
                "stats": r.get("stats", {}),
            }
            for r in _REPORTS.values()
        ]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"reports": items}


@app.get("/api/report/{rid}")
def get_report(rid: str):
    with _REPORTS_LOCK:
        rpt = _REPORTS.get(rid)
    if not rpt:
        raise HTTPException(404, "报告不存在")
    return rpt


@app.get("/api/report/{rid}/items")
def get_items(rid: str, page: int = 1, size: int = 1):
    with _REPORTS_LOCK:
        rpt = _REPORTS.get(rid)
    if not rpt:
        raise HTTPException(404, "报告不存在")
    items = rpt.get("items", [])
    total = len(items)
    start = (page - 1) * size
    chunk = items[start:start + size]
    return {"total": total, "page": page, "size": size, "items": chunk,
            "stats": rpt.get("stats", {})}


@app.delete("/api/report/{rid}")
def delete_report(rid: str):
    with _REPORTS_LOCK:
        rpt = _REPORTS.pop(rid, None)
    if not rpt:
        raise HTTPException(404, "报告不存在")
    return {"ok": True, "deleted": rid}


@app.get("/api/report/{rid}/document")
def report_document(rid: str, format: str = "html", embed: int = 0):
    """可阅读报告文档：format=html（预览页面，embed=1 时图片内嵌为 base64，可离线保存）或 docx（下载 Word）。"""
    with _REPORTS_LOCK:
        rpt = _REPORTS.get(rid)
    if not rpt:
        raise HTTPException(404, "报告不存在")
    if format == "docx":
        data = reportdoc.build_docx(rpt, source_dir=rpt.get("source_dir"))
        safe = "".join(c for c in rpt.get("source_name", "report") if c not in '\\/:*?"<>|')
        fname = f"辨识报告_{safe}_{rid}.docx"
        headers = {
            "Content-Disposition": f"attachment; filename=\"report_{rid}.docx\"; filename*=UTF-8''{quote(fname)}"
        }
        return Response(content=data,
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers=headers)
    html = reportdoc.render_html(rpt, embed_images=bool(embed))   # 自包含 HTML（打印为 PDF 亦可用）
    return HTMLResponse(content=html)


@app.get("/api/export/{rid}")
def export_report(rid: str):
    with _REPORTS_LOCK:
        rpt = _REPORTS.get(rid)
    if not rpt:
        raise HTTPException(404, "报告不存在")
    import json as _json
    safe = "".join(c for c in rpt.get("source_name", "report") if c not in '\\/:*?"<>|')
    body = _json.dumps(rpt, ensure_ascii=False, indent=2).encode("utf-8")
    fname = f"辨识报告_{safe}_{rid}.json"
    # 中文文件名必须用 RFC 5987 形式，否则 HTTP 头 latin-1 编码会报错
    headers = {
        "Content-Disposition": f"attachment; filename=\"report_{rid}.json\"; filename*=UTF-8''{quote(fname)}"
    }
    return Response(content=body, media_type="application/json; charset=utf-8", headers=headers)
