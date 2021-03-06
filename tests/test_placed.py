from collections import namedtuple
from pathlib import Path

import pytest

import layout_content
from layout_content import line_info
from flowables import Table
from layout.common import Rect
from layout.model import Run
from layout.pdf import PDF
from layout.style import Style
from content import GroupContent, ParagraphContent, RectContent, TableContent, \
    calculate_unused_width_for_group
from reportlab.platypus import Paragraph

from conftest import debug_placed_content


@pytest.fixture
def pdf() -> PDF:
    return PDF(Path("/_tmp/killme.pdf"), (500, 1000), debug=True)


@pytest.fixture
def simple() -> Paragraph:
    paragraph = Paragraph("This is some fantastical text")
    paragraph._showBoundary = True
    return paragraph


@pytest.fixture
def styled() -> Paragraph:
    paragraph = Paragraph("<para leading=20>This is <b>some</b> fantastical text</para>")
    paragraph._showBoundary = True
    return paragraph


def make_table(simple, styled, pdf, width) -> Table:
    cells = [
        [styled, simple],
        [Paragraph('Just a long piece of text that will need wrapping in most situations')],
    ]

    return Table(cells, padding=5, colWidths=[width // 2, width // 2], pdf=pdf)


def test_paragraph_on_one_line(simple, pdf):
    defined = Rect.make(left=0, top=0, width=150, height=40)
    p = ParagraphContent(simple, defined, pdf)
    assert p.requested == defined
    assert p.bad_breaks == 0
    assert p.ok_breaks == 0
    assert p.unused_width == 27
    assert p.internal_variance == 0


def test_paragraph_which_wraps_once(simple, pdf):
    defined = Rect.make(left=0, top=0, width=80, height=40)
    p = ParagraphContent(simple, defined, pdf)
    assert p.bad_breaks == 0
    assert p.ok_breaks == 1
    assert p.unused_width == 16
    assert p.internal_variance == 0


def test_paragraph_which_wraps_a_lot(simple, pdf):
    defined = Rect.make(left=0, top=0, width=30, height=40)
    p = ParagraphContent(simple, defined, pdf)
    assert p.bad_breaks == 1
    assert p.ok_breaks == 3
    assert p.unused_width == 1
    assert p.internal_variance == 0


def test_paragraph_which_wraps_badly(simple, pdf):
    defined = Rect.make(left=0, top=0, width=24, height=40)
    p = ParagraphContent(simple, defined, pdf)
    assert p.bad_breaks == 3
    assert p.ok_breaks == 2
    assert p.unused_width == 1
    assert p.internal_variance == 0


def test_styled_paragraph_on_one_line(styled, pdf):
    defined = Rect.make(left=0, top=0, width=150, height=40)
    p = ParagraphContent(styled, defined, pdf)
    assert p.bad_breaks == 0
    assert p.ok_breaks == 0
    assert p.unused_width == 25
    assert p.internal_variance == 0


def test_styled_paragraph_which_wraps_once(styled, pdf):
    defined = Rect.make(left=0, top=0, width=80, height=40)
    p = ParagraphContent(styled, defined, pdf)
    assert p.bad_breaks == 0
    assert p.ok_breaks == 1
    assert p.unused_width == 16
    assert p.internal_variance == 0


def test_styled_paragraph_which_wraps_a_lot(styled, pdf):
    defined = Rect.make(left=0, top=0, width=30, height=40)
    p = ParagraphContent(styled, defined, pdf)
    assert p.requested == defined
    assert p.bad_breaks == 2
    assert p.ok_breaks == 1
    assert p.unused_width == 1
    assert p.internal_variance == 0


def test_styled_paragraph_which_wraps_badly(styled, pdf):
    defined = Rect.make(left=0, top=0, width=24, height=40)
    p = ParagraphContent(styled, defined, pdf)
    assert p.bad_breaks == 3
    assert p.ok_breaks == 0
    assert p.unused_width == 1
    assert p.internal_variance == 0


def test_paragraph_which_wraps_because_of_newline(pdf):
    simple = Paragraph("This is some very simple <BR/>text")
    defined = Rect.make(left=0, top=0, width=200, height=40)
    p = ParagraphContent(simple, defined, pdf)
    assert p.bad_breaks == 0
    assert p.ok_breaks == 0
    assert p.unused_width == 90
    assert p.internal_variance == 0


def test_rectangle(pdf):
    r = RectContent(Rect.make(left=10, top=10, right=100, bottom=100), Style(), PDF.BOTH, pdf)
    assert r.actual == r.requested
    assert r.bad_breaks == 0
    assert r.ok_breaks == 0
    assert r.unused_width == 0
    assert r.internal_variance == 0


def test_group_bad_fits(simple, styled, pdf):
    simple_placed = ParagraphContent(simple, Rect.make(left=0, top=40, width=80, height=40), pdf)
    styled_placed = ParagraphContent(styled, Rect.make(left=80, top=5, width=24, height=40), pdf)

    gp = GroupContent([simple_placed, styled_placed], Rect.make(left=0, top=0, right=200, bottom=100))
    assert gp.actual == Rect.make(left=0, top=5, right=103, bottom=125)
    assert gp.bad_breaks == 3
    assert gp.ok_breaks == 1
    assert gp.unused_width == 113
    assert gp.internal_variance == 0


def test_group_with_space_horizontal(simple, styled, pdf):
    a = ParagraphContent(simple, Rect.make(left=10, top=40, right=200, height=40), pdf)
    b = ParagraphContent(styled, Rect.make(left=200, top=5, right=350, height=40), pdf)

    gp = GroupContent([a, b], Rect.make(left=0, top=0, right=350, bottom=500))

    assert gp.bad_breaks == 0
    assert gp.ok_breaks == 0
    assert gp.unused_width == 35 + b.actual.left - a.actual.right
    assert gp.internal_variance == 0


def test_group_with_space_vertical(simple, styled, pdf):
    a = ParagraphContent(simple, Rect.make(left=10, top=20, right=200, height=40), pdf)
    b = ParagraphContent(styled, Rect.make(left=40, top=50, right=200, height=40), pdf)

    gp = GroupContent([a, b], Rect.make(left=0, top=0, right=200, bottom=100))

    assert gp.bad_breaks == 0
    assert gp.ok_breaks == 0
    assert gp.unused_width == 61
    assert gp.internal_variance == 0


def test_group_with_space_vertical_second(simple, pdf):
    a = ParagraphContent(simple, Rect.make(left=10, top=20, right=200, height=40), pdf)
    b = ParagraphContent(Paragraph("a very long piece of text that will just fit"),
                         Rect.make(left=20, top=50, right=200, height=40), pdf)

    gp = GroupContent([a, b], Rect.make(left=0, top=0, right=200, bottom=100))

    assert gp.bad_breaks == 0
    assert gp.ok_breaks == 0
    assert gp.unused_width == 29
    assert gp.internal_variance == 0


def test_table_in_plenty_of_space(simple, styled, pdf):
    table = make_table(simple, styled, pdf, 400)
    p = TableContent(table, Rect.make(left=10, top=10, width=400, height=100), pdf)
    debug_placed_content(p, pdf)

    assert p.bad_breaks == 0
    assert p.ok_breaks == 0
    assert p.unused_width == 115
    assert p.internal_variance == 0


def test_table_with_one_wraps(simple, styled, pdf):
    table = make_table(simple, styled, pdf, 280)
    p = TableContent(table, Rect.make(left=10, top=10, width=280, height=100), pdf)

    assert p.bad_breaks == 0
    assert p.ok_breaks == 1
    assert p.unused_width == 32
    assert p.internal_variance == 2


def test_table_with_several_wraps(simple, styled, pdf):
    table = make_table(simple, styled, pdf, 180)
    p = TableContent(table, Rect.make(left=10, top=10, width=180, height=100), pdf)
    assert p.bad_breaks == 0
    assert p.ok_breaks == 3
    assert p.unused_width == 18
    assert p.internal_variance == 0


def test_table_with_terrible_wraps(simple, styled, pdf):
    table = make_table(simple, styled, pdf, 40)
    p = TableContent(table, Rect.make(left=10, top=10, width=40, height=100), pdf)

    assert p.bad_breaks == 7
    assert p.ok_breaks == 10
    assert p.unused_width == 0
    assert p.internal_variance == 3


def test_line_info():
    pdf = PDF(Path("/_tmp/killme.pdf"), (500, 1000), True)

    run = Run().add("basic test", 'default')

    p = layout_content.make_paragraph(run, pdf)
    p.wrapOn(pdf, 10, 100)

    bad_breaks, ok_breaks, unused = line_info(p)
    assert bad_breaks == 3
    assert ok_breaks == 1


def test_line_info_for_boxes():
    pdf = PDF(Path("/_tmp/killme.pdf"), (500, 1000), True)

    run = Run().add("[ ][ ][ ][ ][ ][ ][ ][ ]", 'default')

    p = layout_content.make_paragraph(run, pdf)
    p.wrapOn(pdf, 20, 100)
    bad_breaks, ok_breaks, unused = line_info(p)
    assert bad_breaks == 0
    assert ok_breaks == 7


MockContent = namedtuple('MockContent', 'requested unused_width')


def test_unused_group_of_horizontal():
    bounds = Rect.make(left=100, top=100, right=200, bottom=200)

    a = MockContent(Rect.make(left=130, top=100, right=170, bottom=200), 17)
    b = MockContent(Rect.make(left=180, top=100, right=190, bottom=200), 2)
    c = MockContent(Rect.make(left=100, top=100, right=190, bottom=200), 2)

    assert calculate_unused_width_for_group([a], bounds) == 30 + 30 + 17
    assert calculate_unused_width_for_group([a, b], bounds) == 30 + 10 + 10 + 17 + 2
    assert calculate_unused_width_for_group([c], bounds) == 10 + 2
    assert calculate_unused_width_for_group([a, c], bounds) == 10 + 2
    assert calculate_unused_width_for_group([b, c], bounds) == 10 + 2
    assert calculate_unused_width_for_group([a, b, c], bounds) == 10 + 2
