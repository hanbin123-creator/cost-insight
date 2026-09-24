"""板块3 渲染层：docxtpl 标量替换 + python-docx 动态插表/嵌图 + LibreOffice PDF。

渲染链路（合规审计定案：容器内唯一可行的双格式链路）：
1. docxtpl：89 标量占位符直接替换；6 动态表格占位符替换为哨兵文本 @@TBL:名@@
2. python-docx 后处理：定位哨兵段落 → 插入真实表格（Table Grid 兜底无样式）；
   趋势图/结构图 PNG 嵌在 4.1 表后与 2.2 节后（嵌图为 PNG，非图表库，不违 ECharts 约束）
3. PDF：检测 soffice（LibreOffice headless）→ 转换；本机缺失则跳过并如实记录
   （部署镜像内置 LibreOffice，开发机降级不影响 docx 主交付）

None 显示为 "—"（显示格式化豁免计算禁令，数值本身已在 report_data 算好）。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import docx
from docx.shared import Cm
from docxtpl import DocxTemplate

from .charts import ChartBuilder
from .compute import CostCalculator
from .mapping import MAPPING  # import 即触发 placeholder_map.yaml 双层校验（启动即炸）
from .report_data import ReportContextBuilder
from .report_gen import SectionResult, generate_report_sections

# 模板路径可用 REPORT_TEMPLATE 覆盖（消防演习/多模板场景；默认官方模板）
TEMPLATE = Path(os.environ["REPORT_TEMPLATE"]) if os.environ.get("REPORT_TEMPLATE") \
    else Path(__file__).resolve().parent.parent / "assets" / "report_template.docx"

TABLE_HEADERS = {
    "原材料成本明细表格": ["序号", "原材料名称", "本月单价(元/盒)", "上月单价(元/盒)",
                         "环比变动", "变动原因初步判断"],
    "近6个月成本趋势表格": ["月份", "产量(盒)", "单位材料(元/盒)", "单位人工(元/盒)",
                            "单位制造费用(元/盒)", "单位成本(元/盒)", "环比变动"],
    "原材料价格跟踪表格": ["原材料", "年初价", "本月价", "涨幅", "市场趋势", "对材料成本影响"],
    "对标差异表格": ["对比维度", "中药一厂", "中药二厂", "差异金额", "差异率", "方向"],
    "改进建议表格": ["序号", "建议事项", "责任部门", "优先级", "预期效果", "建议完成时间"],
    "整改任务表格": ["任务编号", "任务标题", "责任人", "优先级", "来源", "截止时间"],
}

# 量价分解表（看板排版方案一延伸到 Word）：锚定 3.1.2 材料成本变动归因段插入，
# 数字取自 metrics.decomposition（代码同源），季度报告口径不同不插入（不硬凑）
DECOMP_HEADERS = ["材料", "价格(元/kg)", "用量(kg/盒)",
                  "价格效应(元/盒)", "用量效应(元/盒)", "口径"]


def _fmt_pair(prev, curr) -> str:
    """变迁对格式化：整数浮点保留一位小数（138.0 不丢成 138），与前端 decomp.ts 同口径。"""
    def f(v):
        return f"{v:.1f}" if isinstance(v, float) and v.is_integer() else str(v)
    return f"{f(prev)}→{f(curr)}"


def _decomp_rows(decomp) -> list[list[str]]:
    """Decomposition 列表 → Word 表行（显示格式化，值不变；与前端 decomp.ts 同口径）。"""
    rows = []
    for d in decomp:
        if d.method == "market_price":
            price = _fmt_pair(d.price_prev, d.price_curr)
            qty = _fmt_pair(d.qty_prev, d.qty_curr)
            basis = "行情价分解"
        elif d.method == "stable_price_assumption":
            price, qty, basis = "稳价假设", "—", "稳价假设·行情未覆盖"
        else:
            price, qty, basis = "—", "—", "数据缺失·不分解"
        pe = "—" if d.price_effect is None else f"{d.price_effect:+.4f}"
        qe = "—" if d.qty_effect is None else f"{d.qty_effect:+.4f}"
        rows.append([d.material, price, qty, pe, qe, basis])
    return rows

_SOFICE_CANDIDATES = [
    shutil.which("soffice"),
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def find_soffice() -> str | None:
    """定位 soffice。Windows 上优先 soffice.com（控制台版）：
    soffice.exe 是 GUI 子系统程序，会脱离控制台、stdout 丢失且首启易挂起；
    .com 是同目录的控制台宿主，行为可预期。"""
    for c in _SOFICE_CANDIDATES:
        if c and Path(c).exists():
            com = Path(c).with_suffix(".com")
            return str(com) if com.exists() else c
    return None


# ---------- matplotlib 嵌图（PNG，非图表库） ----------
_BUNDLED_FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "NotoSansSC-Regular.ttf"


def _setup_matplotlib_cjk() -> None:
    """中文字体三级降级（修复 N1：评委环境无托管运行时必炸）：
    1. 项目自带 assets/fonts/NotoSansSC-Regular.ttf（SIL OFL 许可，可随分发）——部署/评测唯一依赖
    2. daimon_runtime.setup_plot（本机开发便利路径，存在即用）
    3. 系统常见中文字体名兜底
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager

    if _BUNDLED_FONT.exists():
        font_manager.fontManager.addfont(str(_BUNDLED_FONT))
        name = font_manager.FontProperties(fname=str(_BUNDLED_FONT)).get_name()
        matplotlib.rcParams["font.family"] = name
    else:
        try:
            sys.path.insert(0, str(Path(sys.executable).parent.parent.parent))
            from daimon_runtime import setup_plot  # noqa
            setup_plot()
        except Exception:
            matplotlib.rcParams["font.sans-serif"] = [
                "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "sans-serif"]
    matplotlib.rcParams["axes.unicode_minus"] = False


def make_chart_pngs(charts: ChartBuilder, product: str, month: str,
                    out_dir: Path) -> dict[str, Path]:
    _setup_matplotlib_cjk()
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    s = charts.series_data(product)
    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=150)
    ax.plot(s["months"], s["unit_cost"], marker="o", label="单位成本", color="#2e6da4")
    for name, data in s["series"].items():
        ax.plot(s["months"], data, marker=".", label=name)
    ax.set_ylabel("元/盒")
    ax.legend(fontsize=8, ncol=4)
    ax.grid(alpha=0.3)
    ax.set_title("近6月单位成本与要素走势")
    p = out_dir / f"trend_{product}_{month}.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    paths["trend"] = p

    st = charts.structure_data(product, month)
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=150)
    inner_vals = [i["value"] for i in st["inner"]]
    inner_labels = [f'{i["name"]} {i["value"]}' for i in st["inner"]]
    outer_vals = [o["value"] for o in st["outer"]]
    wedges1, _ = ax.pie(inner_vals, radius=0.62, labels=inner_labels,
                        labeldistance=0.45, textprops={"fontsize": 8},
                        colors=["#2e6da4", "#6aa84f", "#e69138"])
    ax.pie(outer_vals, radius=1.0, labels=None,
           colors=["#4472c4", "#8faadc", "#c5d9f1", "#a9d18e", "#c6e0b4",
                   "#e2efda", "#f4b183", "#f8cbad", "#ffd966", "#fff2cc"],
           wedgeprops={"width": 0.38, "edgecolor": "white"})
    ax.set_title("本月成本构成（内环要素 / 外环明细）")
    p = out_dir / f"structure_{product}_{month}.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    paths["structure"] = p
    return paths


# ---------- docxtpl → python-docx 后处理 ----------
def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))  # 58000.0 → 58000（显示格式化豁免，值未变）
    return str(v)


def _apply_table_style(table) -> None:
    """动态表样式对齐模板实测参数（从官方模板 tblBorders 提取）：
    全边框 single/4/黑 + 表头灰底 D9D9D9 加粗。模板用 Normal Table + 直接格式化，
    无命名样式可继承，必须手工 XML——参数已与模板逐页视觉比对一致。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), "000000")
        borders.append(el)
    tblPr.append(borders)
    for cell in table.rows[0].cells:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "D9D9D9")
        cell._tc.get_or_add_tcPr().append(shd)
        for para in cell.paragraphs:
            for run in para.runs:
                run.font.bold = True


def _insert_table_after(doc: docx.Document, paragraph, headers: list[str],
                        rows: list[list],
                        widths_cm: list[float] | None = None,
                        font_pt: float | None = None) -> None:
    table = doc.add_table(rows=len(rows) + 1, cols=len(headers))
    for j, h in enumerate(headers):
        table.rows[0].cells[j].text = h
    for i, row in enumerate(rows, 1):
        for j, v in enumerate(row):
            table.rows[i].cells[j].text = _fmt(v)
    _apply_table_style(table)
    if font_pt:
        # 密集数字表降字号（实测：模板默认字号下变迁串超出列宽被腰斩）
        from docx.shared import Pt as _Pt
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        run.font.size = _Pt(font_pt)
    if widths_cm:
        # 固定列宽防长数字串折断（实测 PDF 中 0.0258→0.0254 被腰斩）：
        # autofit 会按内容挤压列宽；tblLayout=fixed + 逐格设宽 + tblGrid 同步
        # （LibreOffice 优先读 tblGrid，只设 tcW 不生效——实机踩坑）
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm as _Cm
        table.autofit = False
        layout = OxmlElement("w:tblLayout")
        layout.set(qn("w:type"), "fixed")
        table._tbl.tblPr.append(layout)
        grid = table._tbl.tblGrid
        for j, col in enumerate(grid.findall(qn("w:gridCol"))):
            col.set(qn("w:w"), str(int(widths_cm[j] * 567)))  # 1cm = 567 twips
        for row in table.rows:
            for j, cell in enumerate(row.cells):
                cell.width = _Cm(widths_cm[j])
    paragraph._p.addnext(table._tbl)


def _insert_picture_after(doc: docx.Document, anchor_element, png: Path,
                          width_cm: float = 15.0) -> None:
    p = doc.add_paragraph()
    p.add_run().add_picture(str(png), width=Cm(width_cm))
    anchor_element.addnext(p._p)


def render_docx(ctx: dict, sections: dict[str, SectionResult],
                pngs: dict[str, Path], out_path: Path,
                template: Path = TEMPLATE, decomp=None) -> None:
    tpl_ctx: dict = {}
    for k, v in ctx.items():
        if k.startswith("__rows__"):
            name = k[len("__rows__"):]
            tpl_ctx[name] = f"@@TBL:{name}@@"   # 哨兵，后处理插真表
        else:
            tpl_ctx[k] = _fmt(v)
    for name, sec in sections.items():
        suffix = "" if sec.source == "llm" else f"（{sec.source}）"
        tpl_ctx[name] = sec.text + suffix

    with tempfile.TemporaryDirectory() as tmp:
        stage1 = Path(tmp) / "stage1.docx"
        tpl = DocxTemplate(str(template))
        tpl.render(tpl_ctx)
        tpl.save(str(stage1))

        doc = docx.Document(str(stage1))
        # 动态表格：哨兵段落 → 真表，随后删除哨兵段落
        for para in list(doc.paragraphs):
            text = para.text
            for name, headers in TABLE_HEADERS.items():
                if f"@@TBL:{name}@@" in text:
                    _insert_table_after(doc, para, headers, ctx[f"__rows__{name}"],
                                        widths_cm=_TABLE_WIDTHS.get(name))
                    if name == "近6个月成本趋势表格" and "trend" in pngs:
                        _insert_picture_after(doc, para._p, pngs["trend"])
                    para._p.getparent().remove(para._p)
                    break
        # 结构图：找 2.2 节后的第一张表，图插其后
        if "structure" in pngs:
            body = list(doc.element.body)
            for idx, el in enumerate(body):
                if el.tag.endswith("}p") and "2.2" in "".join(el.itertext()) \
                        and "成本结构" in "".join(el.itertext()):
                    for el2 in body[idx + 1:]:
                        if el2.tag.endswith("}tbl"):
                            _insert_picture_after(doc, el2, pngs["structure"])
                            break
                    break
        # 量价分解表：锚定 3.1.2 标题，插在其正文段之后（表格管明细，正文讲逻辑）
        if decomp:
            paras = list(doc.paragraphs)
            for idx, para in enumerate(paras):
                if "3.1.2" in para.text and "归因" in para.text:
                    anchor = paras[idx + 1] if idx + 1 < len(paras) else para
                    _insert_table_after(doc, anchor, DECOMP_HEADERS,
                                        _decomp_rows(decomp),
                                        widths_cm=[2.2, 2.5, 3.1, 2.15, 2.15, 2.4],
                                        font_pt=9)
                    break
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _enable_update_fields(doc)
        doc.save(str(out_path))


# 动态表固定列宽（cm）：长文本表 autofit 会挤成"每行几个字"并跨页断裂，
# 固定宽 + 9pt 密排是实测后的版式结论（分解表同款教训，见日志30）
_TABLE_WIDTHS = {
    # 序号 / 建议事项 / 责任部门 / 优先级 / 预期效果 / 建议完成时间
    "改进建议表格": [1.2, 5.2, 2.0, 1.6, 3.6, 2.4],
    # 任务编号 / 标题 / 责任人 / 优先级 / 来源 / 截止时间
    "整改任务表格": [2.6, 4.6, 1.8, 1.4, 3.4, 2.2],
}


def _enable_update_fields(doc) -> None:
    """打开/转换时刷新域：目录页码与页脚"第X页 共N页"域的缓存值随之重建。
    模板域结果缓存停留在模板原页数（如"共44页"），内容增删页后不刷新即穿帮。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        el = OxmlElement("w:updateFields")
        el.set(qn("w:val"), "true")
        settings.append(el)


# ---------- PDF 转换（四层稳定性设计） ----------

def _outline_headings(doc) -> list[tuple[int, str]]:
    """提取大纲级别 0-2 的标题（模板用 outlineLvl 而非 Heading 样式）。
    "整体解决方案"是页眉横幅文本，不是目录条目，剔除。"""
    from docx.oxml.ns import qn
    out = []
    for p in doc.paragraphs:
        text = " ".join(p.text.split())
        if not text or text == "整体解决方案":
            continue
        pPr = p._p.pPr
        if pPr is None:
            continue
        lvl = pPr.find(qn("w:outlineLvl"))
        if lvl is None:
            continue
        lv = int(lvl.get(qn("w:val")))
        if lv <= 2:
            out.append((lv + 1, text))
    return out


def _heading_pages(pdf_path: Path, headings: list[tuple[int, str]]) -> tuple[list[tuple[int, str, int]], list[str]]:
    """在 PDF 逐页文本中按文档顺序定位标题页码（空白归一化后包含匹配）。
    返回 (条目(级别,标题,物理页码), 逐页文本)——逐页文本供页码口径换算复用。"""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        pages = ["".join(pdf[i].get_textpage().get_text_range().split())
                 for i in range(len(pdf))]
        raw = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    finally:
        pdf.close()  # Windows 文件锁：不关句柄会卡死第二遍转换的产物覆盖
    res, start = [], 0
    for lv, text in headings:
        key = "".join(text.split())
        found = next((i + 1 for i in range(start, len(pages)) if key in pages[i]),
                     None)
        if found is None:  # 顺序定位失败则全局兜底，仍失败才放弃该条目
            found = next((i + 1 for i in range(len(pages)) if key in pages[i]),
                         None)
        if found is not None:
            res.append((lv, text, found))
            start = found - 1
    return res, raw


def _write_static_toc(doc, entries: list[tuple[int, str, int]]) -> int:
    """把模板 TOC 域（缓存停留在"右键更新域"占位文本）替换为静态目录行：
    标题 + 点线前导 + 右对齐页码。LibreOffice headless 转换不刷新 TOC 域，
    两遍转换是确定性正解；footer 的页数域由 updateFields 照常动态刷新。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    toc_p = None
    for p in doc.paragraphs:
        if p._p.findall(".//" + qn("w:instrText")) and any(
                "TOC" in (t.text or "")
                for t in p._p.findall(".//" + qn("w:instrText"))):
            toc_p = p._p
            break
    if toc_p is None or not entries:
        return 0
    parent = toc_p.getparent()
    idx = list(parent).index(toc_p)
    parent.remove(toc_p)
    for lv, text, page in reversed(entries):
        p = OxmlElement("w:p")
        pPr = OxmlElement("w:pPr")
        tabs = OxmlElement("w:tabs")
        tab = OxmlElement("w:tab")
        tab.set(qn("w:val"), "right")
        tab.set(qn("w:leader"), "dot")
        tab.set(qn("w:pos"), "8500")
        tabs.append(tab)
        pPr.append(tabs)
        if lv > 1:
            ind = OxmlElement("w:ind")
            ind.set(qn("w:left"), str(360 * (lv - 1)))
            pPr.append(ind)
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:after"), "60")
        pPr.append(sp)
        p.append(pPr)
        r = OxmlElement("w:r")
        if lv == 1:
            rPr = OxmlElement("w:rPr")
            rPr.append(OxmlElement("w:b"))
            r.append(rPr)
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = text
        r.append(t)
        r.append(OxmlElement("w:tab"))
        t2 = OxmlElement("w:t")
        t2.text = str(page)
        r.append(t2)
        p.append(r)
        parent.insert(idx, p)
    return len(entries)


def _footer_total_mismatch(pdf_path: Path) -> tuple[int, int | None]:
    """返回 (实际页数, 页脚声明的总页数)。页脚无"共N页"则 declared=None。"""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        actual = len(pdf)
        m = re.search(r"共\s*(\d+)\s*页",
                      pdf[actual - 1].get_textpage().get_text_range())
        return actual, (int(m.group(1)) if m else None)
    finally:
        pdf.close()


def _freeze_numpages(doc, total: int) -> int:
    """NUMPAGES 域在分节重排页码下 LibreOffice 会算错（实测物理 10 页显示
    "共11页"）——校验不符时将 NUMPAGES 域冻结为实测静态值；PAGE 域保持动态。
    返回冻结的域个数。"""
    from docx.oxml.ns import qn
    patched = 0
    seen = set()
    for section in doc.sections:
        for footer in (section.footer, section.first_page_footer,
                       section.even_page_footer):
            if id(footer._element) in seen:
                continue
            seen.add(id(footer._element))
            # 页码域可能嵌在页脚文本框（w:txbxContent）内——footer.paragraphs
            # 够不到，必须全树迭代（实机调试发现，见开发日志31）
            for p in footer._element.iter(qn("w:p")):
                instrs = [t for t in p.findall(".//" + qn("w:instrText"))
                          if "NUMPAGES" in (t.text or "")]
                if not instrs:
                    continue
                runs = p.findall(qn("w:r"))
                # 按域分段：begin..end 为一个段；NUMPAGES 段整体换成静态文本 run，
                # 其余域（如 PAGE）原样保留——页脚文本框内两类域共存，不能误拆
                result, i = [], 0
                while i < len(runs):
                    r = runs[i]
                    fld = r.find(qn("w:fldChar"))
                    if fld is not None and fld.get(qn("w:fldCharType")) == "begin":
                        seg, j = [r], i + 1
                        while j < len(runs):
                            seg.append(runs[j])
                            f2 = runs[j].find(qn("w:fldChar"))
                            if f2 is not None and f2.get(qn("w:fldCharType")) == "end":
                                break
                            j += 1
                        instr = " ".join(
                            (x.find(qn("w:instrText")).text or "") for x in seg
                            if x.find(qn("w:instrText")) is not None)
                        if "NUMPAGES" in instr:
                            rPr_src = next((x.find(qn("w:rPr")) for x in seg
                                            if x.find(qn("w:t")) is not None), None)
                            r_new = p.makeelement(qn("w:r"), {})
                            if rPr_src is not None:
                                r_new.append(rPr_src)
                            t = r_new.makeelement(qn("w:t"), {})
                            t.text = str(total)
                            r_new.append(t)
                            result.append(r_new)
                            patched += 1
                        else:
                            result.extend(seg)
                        i = j + 1
                    else:
                        result.append(r)
                        i += 1
                for r in runs:
                    p.remove(r)
                for r in result:
                    p.append(r)
    return patched


def _render_pdf_with_toc(docx_path: Path) -> tuple[Path | None, str | None, int]:
    """两遍半转换：首遍测标题实际页码 → 静态目录回填 docx → 终遍出正式 PDF，
    末页校验页脚总数（NUMPAGES 域在分节重排页码下会算错，不符则冻结为静态值
    再转一遍）。任一步失败降级保留上一遍结果，版式问题永不阻塞出货。
    返回 (pdf, warn, 目录条数)。"""
    first, warn1 = render_pdf(docx_path)
    if first is None:
        return None, warn1, 0
    try:
        doc = docx.Document(str(docx_path))
        entries, page_texts = _heading_pages(first, _outline_headings(doc))
        # 页码口径换算：前置页（封面/编制/目录）无页脚编号，正文从"第 1 页"
        # 重起——目录页码必须与读者看到的页脚编号一致，而非物理页码
        f0 = next((i + 1 for i, t in enumerate(page_texts)
                   if re.search(r"第\s*1\s*页", t)), None)
        if f0:
            entries = [(lv, t, p - f0 + 1) for lv, t, p in entries if p >= f0]
        if not entries:
            return first, warn1, 0
        n = _write_static_toc(doc, entries)
        doc.save(str(docx_path))
    except Exception as e:  # 目录回填失败：首遍 PDF 原样交付
        return first, f"目录回填失败（{e}），PDF 为首遍无目录版本", 0
    second, warn2 = render_pdf(docx_path)
    if second is None:
        return first, f"目录版转换失败（{warn2}），PDF 为首遍无目录版本", 0
    if Path(first) != Path(second):
        Path(first).unlink(missing_ok=True)  # 同名同路径时 second 即最终版，勿删
    # 末遍校验：页脚"共N页"与实际页数不符 → NUMPAGES 冻结为静态值再转一遍
    actual, declared = _footer_total_mismatch(second)
    if declared is not None and declared != actual:
        doc = docx.Document(str(docx_path))
        if _freeze_numpages(doc, actual):
            doc.save(str(docx_path))
            third, warn3 = render_pdf(docx_path)
            if third is not None:
                a2, d2 = _footer_total_mismatch(third)
                if d2 == a2:
                    return third, warn1, n
                return third, (warn1 or "") + f"；页脚总数仍不符({d2}/{a2})", n
        return second, (warn1 or "") + f"；页脚总数不符({declared}/{actual})，冻结失败", n
    return second, warn1, n
_CONVERT_TIMEOUT = 60.0   # 单次硬超时：实测正常转换 5-15s，60s 已 4 倍冗余
_POLL_INTERVAL = 2.0      # 文件守望者轮询间隔

# 瞬时故障签名（值得重试）：profile 锁 / 占用类；其余一律确定性故障立即报错
_TRANSIENT_SIGNS = ("lock", "Lock", "profile", "Profile", "busy", "Busy", "占用")


def _kill_tree(proc: subprocess.Popen) -> None:
    """强制收尾进程树。Windows 上 soffice 会 fork 子进程，必须 taskkill /T。"""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            proc.kill()
    except Exception:
        pass  # 收尾失败不掩盖主流程——进程已超时必死，只是死得体面与否


def _convert_once(soffice: str, docx_path: Path, profile: Path,
                  timeout: float, poll: float):
    """单次转换：文件守望者 + 硬超时 + 死因分类。
    返回 (pdf_path|None, err|None, transient: bool)。

    守望者（②号冤案平反）：LibreOffice 无头模式常见病是"PDF 早转完，
    进程赖着不退"。旧方案把这判成失败白等超时。现每 poll 秒查产物，
    大小连续两轮稳定即判定成功，主动杀进程收尾——转完即走。"""
    pdf = docx_path.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)  # 防陈旧产物骗过守望者
    proc = subprocess.Popen(
        [soffice, "--headless", "--norestore",
         f"-env:UserInstallation={profile.as_uri()}",
         "--convert-to", "pdf", "--outdir",
         str(docx_path.parent), str(docx_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + timeout
    last_size, stable = -1, 0
    while True:
        rc = proc.poll()
        if pdf.exists():
            size = pdf.stat().st_size
            if size > 0 and size == last_size:
                stable += 1
                if stable >= 2:      # 连续两轮大小不变 → 已写完
                    if rc is None:
                        _kill_tree(proc)   # 进程不退没关系，产物已确认
                    return pdf, None, False
            else:
                stable, last_size = 0, size
        if rc is not None:
            if rc == 0 and pdf.exists():
                return pdf, None, False
            err = proc.stderr.read().decode(errors="replace")[:200] \
                if proc.stderr else ""
            if rc == 0:
                return None, "退出码 0 但产物缺失（转换静默失败）", False
            transient = any(s in err for s in _TRANSIENT_SIGNS)
            return None, f"退出码 {rc}: {err or '（无 stderr）'}", transient
        if time.monotonic() > deadline:
            _kill_tree(proc)
            return None, f"转换超时（{timeout:.0f}s，已强制收尾进程树）", True
        time.sleep(poll)


def render_pdf(docx_path: Path, _log: list | None = None,
               _timeout: float = _CONVERT_TIMEOUT,
               _poll: float = _POLL_INTERVAL) -> tuple[Path | None, str | None]:
    """soffice 可用则转 PDF；不可用返回 (None, 原因)——如实降级。

    四层稳定性（最坏耗时 2×60s=2 分钟，比旧方案 6 分钟压缩 3 倍）：
    - 起飞前检查：soffice / docx 任一缺失，秒级报错不重试（必死局不白等）
    - 文件守望者：产物大小稳定即成功，主动收尾进程——"转完进程不退"的
      偶发故障直接平反，不再消耗超时预算
    - 硬超时 60s：实测正常转换 5-15s 的 4 倍冗余，不是拍脑袋砍的
    - 死因分类重试：瞬时签名（profile 锁/占用）才重试一次；确定性故障
      （损坏/权限/静默失败）立即报错——重试救不了的病不浪费一分钟。
      每次尝试与成功均 print 留痕；_log/_timeout/_poll 供测试注入。"""
    soffice = find_soffice()
    if not soffice:
        return None, "本机未检测到 LibreOffice（soffice），PDF 未生成；部署镜像内置后自动生成"
    if not docx_path.exists():
        return None, f"docx 不存在，无法转换: {docx_path}"

    def _emit(msg: str) -> None:
        print(f"[render_pdf] 警告: {msg}")
        if _log is not None:
            _log.append(msg)

    last_err = ""
    for attempt in (1, 2):
        profile = Path(tempfile.mkdtemp(prefix="lo_profile_"))
        pdf, err, transient = _convert_once(soffice, docx_path, profile,
                                            _timeout, _poll)
        if pdf is not None:
            if attempt > 1:
                _emit(f"PDF 转换第 {attempt} 次尝试成功（重试机制生效）")
            return pdf, None
        last_err = err
        if not transient:
            _emit(f"PDF 转换第 {attempt} 次尝试失败（{err}）"
                  "——确定性故障，重试无意义，立即报错")
            return None, f"soffice 转换失败（确定性故障，未重试）: {last_err}"
        _emit(f"PDF 转换第 {attempt} 次尝试失败（{err}）"
              + ("，自动重试一次" if attempt == 1 else "，不再重试"))
    return None, f"soffice 转换两次均失败: {last_err}"


# ---------- 编排入口 ----------
_THEME_LABEL = {"monthly": "月度", "quarterly": "季度", "topical": "专题"}


def build_report(calc: CostCalculator, retriever, llm, product: str, month: str,
                 out_dir: Path, theme: str = "monthly",
                 quarter: str | None = None) -> dict:
    """板块3 主入口：上下文 → 文本段落 → 嵌图 → 渲染 → (可选)PDF。

    theme（赛题 5.1.3 三主题）：monthly=月度 / quarterly=季度（quarter=Q1/Q2，
    指标走产量加权合成口径）/ topical=专题（复用对标/告警链路，月度数据锚点）。
    返回 {docx, pdf, warnings, verification, sections_source, theme}。"""
    if theme not in _THEME_LABEL:
        raise ValueError(f"未知报告主题: {theme}（可选 {sorted(_THEME_LABEL)}）")
    label = _THEME_LABEL[theme]
    charts = ChartBuilder(calc)
    ctx = ReportContextBuilder(calc).build(product, month, theme=theme, quarter=quarter)
    sections, suggestions, verification = generate_report_sections(
        calc, retriever, llm, product, month, theme=theme, quarter=quarter)

    # LLM 建议合并进 6.3 表（责任部门/优先级沿用规则映射：措辞归模型，定性归代码）
    if llm is not None and suggestions:
        from .report_data import _DEPT_RULES
        rows = []
        for i, s in enumerate(suggestions, 1):
            dept, prio = ("采购部", "高") if any(
                k in s for k in ("采购", "锁价", "行情", "材料", "药材")) else ("生产部", "中")
            rows.append([str(i), s, dept, prio, "抑制成本异常涨幅", "次月25日前"])
        ctx["__rows__改进建议表格"] = rows

    anchor = f"2026-{quarter}" if theme == "quarterly" else month
    # 量价分解表（看板方案一延伸）：月度/专题用月度口径分解；季度报告口径不同，不硬凑
    decomp = [] if theme == "quarterly" else calc.metrics(product, month).decomposition
    with tempfile.TemporaryDirectory() as tmp:
        pngs = make_chart_pngs(charts, product, month, Path(tmp))
        docx_path = out_dir / f"{product}_{anchor}_{label}成本分析报告.docx"
        render_docx(ctx, MAPPING.section_context(sections), pngs, docx_path,
                    decomp=decomp)

    pdf_path, pdf_warn, toc_n = _render_pdf_with_toc(docx_path)
    warnings = [pdf_warn] if pdf_warn else []
    return {"docx": str(docx_path), "pdf": str(pdf_path) if pdf_path else None,
            "warnings": warnings, "verification": verification, "theme": theme,
            "toc_entries": toc_n,
            "sections_source": {k: v.source for k, v in sections.items()}}
