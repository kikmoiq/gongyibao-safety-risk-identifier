# -*- coding: utf-8 -*-
"""文档摄取：把 .md / .docx / 纯文本 统一成规范化 markdown 文本（行数组）。
- .docx 用 python-docx 按正文顺序抽取（标题→#、段落、表格→GFM 管道表）
- .md / 文本：先做 HTML 表格 → GFM 管道表 归一化（工艺包 SDS 常用 <table>）
"""
import html
import re
from pathlib import Path

_TAG_RE = re.compile(r"<[^>]+>")
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _clean_html(s: str) -> str:
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _html_table_to_pipe(block: str) -> str:
    """把一个 <table>...</table> 块转成 GFM 管道表文本。"""
    out = []
    header_done = False
    for tr in _TR_RE.findall(block):
        cells = [_clean_html(c) for c in _CELL_RE.findall(tr)]
        if not cells:
            continue
        out.append("| " + " | ".join(cells) + " |")
        if not header_done:
            out.append("| " + " | ".join(["---"] * len(cells)) + " |")
            header_done = True
    return "\n".join(out)


def normalize_markdown(text: str) -> str:
    """统一换行；把 HTML 表格块替换成 GFM 管道表；去掉图片标记。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # HTML 表格归一化（含跨行的 td 内容）
    def _repl(m):
        return "\n" + _html_table_to_pipe(m.group(0)) + "\n"

    text = re.sub(r"<table[^>]*>.*?</table>", _repl, text, flags=re.S | re.I)
    # 注意：保留 Markdown 图片行 ![alt](path)，供机器人选型图等展示；
    # 各文本扫描器均已跳过以 '![' 开头的行。
    return text


def read_md(path: str) -> tuple[str, str]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return normalize_markdown(text), Path(path).stem


def read_docx(path: str) -> tuple[str, str]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    lines = []
    for child in doc.element.body.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style_name = (para.style.name if para.style else "") or ""
            m = re.search(r"Heading\s*(\d)|标题\s*(\d)", style_name)
            if m:
                lvl = m.group(1) or m.group(2)
                try:
                    lvl = min(int(lvl), 6)
                except Exception:
                    lvl = 1
                lines.append("#" * lvl + " " + text)
            else:
                lines.append(text)
        elif tag == qn("w:tbl"):
            tbl = Table(child, doc)
            for ri, row in enumerate(tbl.rows):
                cells = []
                for cell in row.cells:
                    txt = re.sub(r"\s+", " ", cell.text).strip()
                    cells.append(txt)
                lines.append("| " + " | ".join(cells) + " |")
                if ri == 0:
                    lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
    text = normalize_markdown("\n".join(lines))
    return text, Path(path).stem


def read_source(path_or_text: str, kind: str = "text", filename: str = "") -> tuple[str, str]:
    """统一入口。kind: md / docx / text / demo / autodetect"""
    if kind in ("md", "docx"):
        path = Path(path_or_text)
        if kind == "docx":
            return read_docx(str(path))
        return read_md(str(path))
    # text / demo：path_or_text 即文本内容
    name = filename.strip() or "粘贴文本"
    return normalize_markdown(path_or_text), name
