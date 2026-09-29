import math
import os

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from minutes.templates import MinutesTemplate, Section

FONT = "Arial"
DARK = "2B2B2B"
LIGHT = "F2F2F2"
LINE = "D9D9D9"
GRAY = RGBColor(0x66, 0x66, 0x66)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
EMPTY_NOTE = "Nenhum item registrado."
PAGE_WIDTH_CM = 17.0  # A4 minus 2 cm margins on each side


def write_minutes(
    template: MinutesTemplate,
    header: dict,
    participants: list[str],
    minutes: dict,
    output_path: str,
    logo_path: str | None = None,
) -> str:
    """
    Renders the filled minutes (the dict returned by parse_response) as a .docx
    following the layout of the template PDFs: title block, header table,
    participants, then every section in template order. Returns output_path.
    """
    doc = Document()
    _page_setup(doc)
    _title_block(doc, template, logo_path)
    _header_table(doc, template, header)
    _participants(doc, template, participants)

    headings_done: set[str] = set()
    for section in template.sections:
        _render_section(doc, section, minutes.get(section.key), headings_done)

    _footer(doc, template, header)
    doc.save(output_path)
    return output_path


# ------------------------------------------------------------------ blocks

def _page_setup(doc):
    for s in doc.sections:
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.left_margin = s.right_margin = Cm(2.0)
        s.top_margin, s.bottom_margin = Cm(2.0), Cm(1.8)
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10)
    # Word keeps a separate East Asian font name; without this the font shows as Calibri in some locales.
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.paragraph_format.space_after = Pt(4)


def _title_block(doc, template, logo_path):
    if logo_path and os.path.isfile(logo_path):
        table = doc.add_table(rows=1, cols=2)
        logo_cell, text_cell = table.rows[0].cells
        logo_cell.width, text_cell.width = Cm(5.0), Cm(PAGE_WIDTH_CM - 5.0)
        logo_cell.paragraphs[0].add_run().add_picture(logo_path, width=Cm(4.5))
        _title_runs(text_cell.paragraphs[0], text_cell.add_paragraph(), template)
    else:
        _title_runs(doc.add_paragraph(), doc.add_paragraph(), template)
    rule = doc.add_paragraph()
    rule.paragraph_format.space_after = Pt(6)
    _paragraph_border(rule, "bottom", sz=18)


def _title_runs(title_par, subtitle_par, template):
    title_par.paragraph_format.space_after = Pt(0)
    run = title_par.add_run(template.title)
    run.bold, run.font.size = True, Pt(20)
    if template.subtitle:
        sub = subtitle_par.add_run(template.subtitle)
        sub.italic, sub.font.color.rgb = True, GRAY


def _header_table(doc, template, header):
    fields = template.header
    rows = math.ceil(len(fields) / 2)
    table = doc.add_table(rows=rows, cols=4)
    _table_borders(table)
    label_w, value_w = Cm(2.6), Cm(PAGE_WIDTH_CM / 2 - 2.6)
    for i, field in enumerate(fields):
        row, col = divmod(i, 2)
        label_cell, value_cell = table.rows[row].cells[col * 2], table.rows[row].cells[col * 2 + 1]
        label_cell.width, value_cell.width = label_w, value_w
        _shade(label_cell, LIGHT)
        _cell_text(label_cell, field.label, bold=True)
        _cell_text(value_cell, str(header.get(field.key) or ""))
    _space(doc)


def _participants(doc, template, participants):
    conf = template.participants
    _heading(doc, conf.title)
    if conf.inline:
        p = doc.add_paragraph()
        p.add_run(f"{conf.label or 'Participantes'}: ").bold = True
        p.add_run(", ".join(participants))
        return
    cols = 3
    table = doc.add_table(rows=max(1, math.ceil(len(participants) / cols)), cols=cols)
    _table_borders(table)
    for i, name in enumerate(participants):
        row, col = divmod(i, cols)
        _cell_text(table.rows[row].cells[col], name)
    _space(doc)


def _render_section(doc, section: Section, value, headings_done: set[str]):
    if section.group:
        if section.group not in headings_done:
            _heading(doc, section.group)
            headings_done.add(section.group)
        _subheading(doc, section)
    else:
        _heading(doc, section.title)
        headings_done.add(section.title)

    if section.type == "paragraph":
        _paragraph(doc, value)
    elif section.type == "bullets":
        _bullets(doc, value)
    elif section.type == "topics":
        _topics(doc, value)
    elif section.type == "table":
        _table(doc, section, value)
    elif section.type == "record":
        _record(doc, section, value)


def _paragraph(doc, text):
    if text:
        doc.add_paragraph(text)
    else:
        _empty_note(doc)


def _bullets(doc, items):
    if not items:
        _empty_note(doc)
    for item in items or []:
        doc.add_paragraph(item, style="List Bullet")


def _topics(doc, topics):
    if not topics:
        _empty_note(doc)
    for topic in topics or []:
        head = doc.add_paragraph(style="List Number")
        head.paragraph_format.space_after = Pt(0)
        head.add_run(topic.get("titulo", "")).bold = True
        body = doc.add_paragraph(topic.get("resumo", ""))
        body.paragraph_format.left_indent = Cm(0.63)


def _table(doc, section, rows):
    fields = list(section.columns)
    table = doc.add_table(rows=1 + max(1, len(rows or [])), cols=len(fields) + (1 if section.id_prefix else 0))
    _table_borders(table)
    _set_widths(table, _column_widths(fields, with_id=bool(section.id_prefix)))
    labels = ([section.id_label] if section.id_prefix else []) + [f.label for f in fields]
    for j, label in enumerate(labels):
        _shade(table.rows[0].cells[j], DARK)
        _cell_text(table.rows[0].cells[j], label, bold=True, color=WHITE)
    if not rows:
        merged = table.rows[1].cells[0].merge(table.rows[1].cells[-1])
        _cell_text(merged, EMPTY_NOTE, italic=True, color=GRAY)
    for i, row in enumerate(rows or [], 1):
        values = ([row.get("id", "")] if section.id_prefix else []) + [str(row.get(f.key, "")) for f in fields]
        for j, value in enumerate(values):
            _cell_text(table.rows[i].cells[j], value)
    _space(doc)


def _record(doc, section, record):
    table = doc.add_table(rows=2, cols=len(section.fields))
    _table_borders(table)
    _set_widths(table, _column_widths(section.fields, with_id=False))
    for j, field in enumerate(section.fields):
        head, body = table.rows[0].cells[j], table.rows[1].cells[j]
        _shade(head, DARK)
        _cell_text(head, field.label, bold=True, color=WHITE)
        _cell_text(body, str((record or {}).get(field.key) or ""))
    _space(doc)


def _footer(doc, template, header):
    footer = doc.sections[0].footer
    # A two-column table keeps the page number flush right regardless of the text length.
    table = footer.add_table(rows=1, cols=2, width=Cm(PAGE_WIDTH_CM))
    _table_borders(table, edges=("top",))
    _set_widths(table, [Cm(PAGE_WIDTH_CM - 3.0), Cm(3.0)])
    left, right = table.rows[0].cells
    text = template.footer.replace("{projeto}", str(header.get("projeto") or ""))
    _cell_text(left, text, color=GRAY, size=8)
    _cell_text(right, "Página ", color=GRAY, size=8)
    right.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    num = right.paragraphs[0].add_run()
    num.font.size, num.font.color.rgb = Pt(8), GRAY
    _field(num, "PAGE")
    # The empty default paragraph would add a blank line under the table.
    footer.paragraphs[0]._p.getparent().remove(footer.paragraphs[0]._p)


# ----------------------------------------------------------------- helpers

def _heading(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(10), Pt(4)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    run.bold, run.font.size = True, Pt(11)
    _paragraph_border(p, "bottom", sz=6)


def _subheading(doc, section):
    if section.style == "bar":
        p = doc.add_paragraph()
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(6), Pt(2)
        p.paragraph_format.keep_with_next = True
        p.add_run(section.title).bold = True
        _paragraph_border(p, "left", sz=18)
        return
    _space(doc, 4)
    table = doc.add_table(rows=1, cols=1)
    cell = table.rows[0].cells[0]
    cell.width = Cm(PAGE_WIDTH_CM)
    _shade(cell, DARK)
    _cell_text(cell, section.title, bold=True, color=WHITE)
    cell.paragraphs[0].paragraph_format.keep_with_next = True


def _empty_note(doc):
    p = doc.add_paragraph()
    run = p.add_run(EMPTY_NOTE)
    run.italic, run.font.color.rgb = True, GRAY


def _space(doc, pt=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = Pt(pt)


def _column_widths(fields, with_id):
    """
    The first free-text column (action, decision, agenda) gets most of the
    row; columns with a fixed format or a value list (date, status) stay
    narrow; an ID column is narrower still.
    """
    free = [f for f in fields if not f.format and not f.values]
    wide = free[0].key if free else fields[0].key
    weights = [5 if f.key == wide else 2 for f in fields]
    id_cm = 1.3 if with_id else 0
    available = PAGE_WIDTH_CM - id_cm
    widths = [Cm(available * w / sum(weights)) for w in weights]
    return ([Cm(id_cm)] if with_id else []) + widths


def _set_widths(table, widths):
    # Word ignores per-cell widths while autofit is on, so turn it off and set every cell of each column.
    table.autofit = False
    for j, width in enumerate(widths):
        table.columns[j].width = width
        for cell in table.columns[j].cells:
            cell.width = width


def _cell_text(cell, text, bold=False, italic=False, color=None, size=10):
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run(text)
    run.bold, run.italic, run.font.size = bold, italic, Pt(size)
    if color is not None:
        run.font.color.rgb = color


def _shade(cell, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _table_borders(table, color=LINE, sz=4, edges=("top", "left", "bottom", "right", "insideH", "insideV")):
    borders = OxmlElement("w:tblBorders")
    for edge in edges:
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    table._tbl.tblPr.append(borders)


def _paragraph_border(paragraph, side, sz=6, color=DARK):
    pBdr = OxmlElement("w:pBdr")
    el = OxmlElement(f"w:{side}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:space"), "4")
    el.set(qn("w:color"), color)
    pBdr.append(el)
    paragraph._p.get_or_add_pPr().append(pBdr)


def _field(run, instruction):
    begin, end = OxmlElement("w:fldChar"), OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    end.set(qn("w:fldCharType"), "end")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    for el in (begin, instr, end):
        run._r.append(el)


if __name__ == "__main__":
    import argparse
    import json

    from minutes.templates import load_template

    parser = argparse.ArgumentParser(description="Render filled minutes (template, header, participants, minutes) as .docx")
    parser.add_argument("filled", help="JSON like minutes/tests/fixtures/ata_dell_preenchida.json")
    parser.add_argument("-o", "--output", default="ata.docx")
    parser.add_argument("--logo", help="image placed left of the title")
    args = parser.parse_args()

    with open(args.filled, encoding="utf-8") as f:
        data = json.load(f)
    path = write_minutes(load_template(data["template"]), data["header"], data["participants"], data["minutes"], args.output, args.logo)
    print(path)
