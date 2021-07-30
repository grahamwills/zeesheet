from copy import copy

from reportlab.platypus import Flowable, Paragraph, Table, TableStyle

import common
from common import Rect
from model import Block, Element, ElementType, Run, Style
from pdf import PDF
from render import PlacedContent, PlacedFlowableContent, PlacedGroupContent, PlacedRectContent

LOGGER = common.configured_logger(__name__)


def _add_run(elements: [Element], row: [], pdf: PDF, align: str):
    if elements:
        para = pdf.make_paragraph(Run(elements), align=align)
        row.append(para)


def make_row_from_run(run: [Element], pdf: PDF, width: int) -> [Flowable]:
    items = run.items

    spacer_count = sum(e.which == ElementType.SPACER for e in items)
    divider_count = sum(e.which == ElementType.DIVIDER for e in items)

    if divider_count + spacer_count == 0:
        # just a single line
        return [pdf.make_paragraph(run)]

    # Establish spacing patterns
    if spacer_count < 2:
        alignments = ['left', 'right']
    else:
        alignments = ['left'] * (spacer_count - 1) + ['center', 'right']

    row = []
    start = 0
    spacer_idx = 0
    for i, e in enumerate(items):
        if e.which in {ElementType.SPACER, ElementType.DIVIDER}:
            _add_run(items[start:i], row, pdf, alignments[spacer_idx])
            if e.which == ElementType.SPACER:
                spacer_idx += 1
            start = i + 1

    _add_run(items[start:], row, pdf, alignments[spacer_idx])

    if divider_count == 0:
        # Make a sub-table just for this line
        return [as_table([row], width)]
    else:
        return row


def as_one_line(run: Run, pdf: PDF, width: int):
    if not any(e.which == ElementType.SPACER for e in run.items):
        # No spacers -- nice and simple
        p = pdf.make_paragraph(run)
        w, h = p.wrapOn(pdf, width, 1000)
        return p, w, h

    # Make a one-row table
    cells = [make_row_from_run(run, pdf, width)]
    return make_table(pdf, cells, width)


def table_layout(block: Block, bounds: Rect, pdf: PDF) -> PlacedContent:
    cells = [make_row_from_run(run, pdf, bounds.width) for run in block.content]
    table, w, h = make_table(pdf, cells, bounds.width)
    return PlacedFlowableContent(table, bounds.resize(width=w, height=h))


def make_table(pdf, paragraphs, width):
    table = as_table(paragraphs, width)
    w, h = table.wrapOn(pdf, width, 1000)
    return table, w, h


def _estimate_col_width(cells: [[Flowable]], col: int) -> float:
    mx = 3
    for row in cells:
        if col < len(row) and isinstance(row[col], Paragraph):
            p: Paragraph = row[col]
            t = sum(len(f.text) * f.fontSize for f in p.frags)
            mx = max(mx, t)
    return mx // 2


def as_table(cells, width: int):
    commands = [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]

    estimated_widths = [_estimate_col_width(cells, i) for i in range(0, len(cells[0]))]

    factor = width / sum(estimated_widths)
    colWidths = [w * factor for w in estimated_widths]

    return Table(cells, colWidths=colWidths, style=(TableStyle(commands)))


def center_text(p: Flowable, bounds: Rect, pdf: PDF, style:Style) -> Rect:
    w, h = p.wrapOn(pdf, bounds.width, bounds.height)
    top = bounds.top + (bounds.height - h -pdf.descender(style)) / 2
    return Rect(left=bounds.left, top=top, width=bounds.width, height=h)


def stats_runs(run: [Element], pdf: PDF) -> [Paragraph]:
    items = run.items
    row = []
    start = 0
    spacer_idx = 0
    for i, e in enumerate(items):
        if e.which in {ElementType.SPACER, ElementType.DIVIDER}:
            if len(row) == 1:
                multiplier = 1.33333333
            else:
                multiplier = 1.0
            if items[start:i]:
                row.append(pdf.make_paragraph(Run(items[start:i]), align='center', size_factor=multiplier))
            if e.which == ElementType.SPACER:
                spacer_idx += 1
            start = i + 1

    if len(row) == 1:
        multiplier = 1.33333333
    else:
        multiplier = 1.0
    if items[start:]:
        para = pdf.make_paragraph(Run(items[start:]), align='center', size_factor=multiplier)
        row.append(para)
    return row


def key_values_layout(block: Block, bounds: Rect, pdf: PDF) -> PlacedContent:
    items = [stats_runs(run, pdf) for run in block.content]

    padding = block.padding

    nRows = int(block.block_method.options['rows'])
    box_style = pdf.style(block.block_method.options['style'])
    text_style = pdf.style(block.base_style())
    text_style_1 = copy(text_style)
    text_style_1.size = text_style_1.size * 3 // 2
    H1 = text_style.size + 2 * padding
    W1 = 2 * padding + round(_estimate_col_width(items, 0))

    H2 = text_style_1.size + 2 * padding
    W2 = (H2 * 3) // 2

    LOGGER.debug("Key Values Layout for %d items, H1=%d, W1=%d", len(items), H1, W1)

    contents = []

    top = bounds.top
    left = bounds.left
    for i, cell in enumerate(items):
        if contents and i % nRows == 0:
            top = bounds.top
            left += W1 + W2 + 2 * padding
        r2 = Rect(left=left, top=top, height=H2, width=W2)
        r1 = Rect(left=r2.right - 1, top=top + (H2 - H1) / 2, width=W1 + 1, height=H1)
        contents.append(PlacedRectContent(r1, box_style, True, False))
        contents.append(PlacedRectContent(r2, box_style, True, False))

        cell[0].wrapOn(pdf, r1.width, r1.height)
        cell[1].wrapOn(pdf, r2.width, r2.height)
        contents.append(PlacedFlowableContent(cell[0], center_text(cell[0], r1, pdf, text_style)))
        contents.append(PlacedFlowableContent(cell[1], center_text(cell[1], r2, pdf, text_style_1)))
        top = r2.bottom + padding

    return PlacedGroupContent(contents)
