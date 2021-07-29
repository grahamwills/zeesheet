import enum
from dataclasses import dataclass, field
from typing import List, Optional

import docutils.frontend
import docutils.nodes
import docutils.parsers.rst
import docutils.utils
from colour import Color

import common
from model import BLACK, Block, Section, Sheet, Style

LOGGER = common.configured_logger(__name__)


class State(enum.Enum):
    READY = 0
    IN_TITLE = 2
    IN_CONTENT = 3
    IN_CONTENT_ITEM = 4


@dataclass
class Status:
    section: Optional[Section] = None
    block: Optional[Block] = None

    stack: List[docutils.nodes.Node] = field(default_factory=list)

    def _name(self, node):
        return node.__class__.__name__

    def _report(self) -> str:
        return " < ".join(self._name(s) for s in self.stack[::-1])

    def enter(self, node: docutils.nodes.Node) -> str:
        self.stack.append(node)
        return self._report()

    def depart(self, node: docutils.nodes.Node) -> str:
        report = self._report()
        last = self.stack.pop()
        if last is not node:
            raise ValueError("Inconsistent departure: expected '%s', but was '%s'"
                             % (self._name(last), self._name(node)))
        return report

    def style_modifers(self):
        bold = self.within(docutils.nodes.strong)
        italic = self.within(docutils.nodes.emphasis)
        if bold and italic:
            return 'BI'
        if bold:
            return 'B'
        if italic:
            return 'I'
        return None

    def within(self, cls):
        return any(type(n) == cls for n in self.stack)

    def finish_section(self):
        self.state = State.READY
        self.section = None
        self.block = None


class FormatError(RuntimeError):
    pass


def parse_rst(text: str) -> docutils.nodes.document:
    parser = docutils.parsers.rst.Parser()
    components = (docutils.parsers.rst.Parser,)
    settings = docutils.frontend.OptionParser(components=components).get_default_values()
    document = docutils.utils.new_document('<rst-doc>', settings=settings)
    parser.parse(text, document)
    return document


def line_of(node: docutils.nodes.Node):
    if node.line is None:
        return line_of(node.parent)
    else:
        return node.line


class StyleVisitor(docutils.nodes.NodeVisitor):
    sheet: Sheet
    style_name: Optional[str]


    def __init__(self, document, sheet: Sheet):
        super().__init__(document)
        self.sheet = sheet
        self.style_name = None

    def unknown_visit(self, node: docutils.nodes.Node) -> None:
        pass

    def unknown_departure(self, node: docutils.nodes.Node) -> None:
        pass

    def visit_title(self, node: docutils.nodes.title) -> None:
        self.style_name = node.astext()
        LOGGER.debug("Defining style '%s' using '%s'", self.style_name, node.__class__.__name__)
        raise docutils.nodes.SkipChildren

    def visit_term(self, node) -> None:
        self.style_name = node.astext()
        LOGGER.debug("Style - Defining style '%s' using '%s'", self.style_name, node.__class__.__name__)
        raise docutils.nodes.SkipChildren

    def visit_Text(self, node: docutils.nodes.Text) -> None:
        txt = node.astext().replace('\n', ' ')
        LOGGER.debug("Style - modifying '%s' with '%s'", self.style_name, txt)
        _modify_style(self.sheet.styles, self.style_name, txt)
        raise docutils.nodes.SkipChildren



class SheetVisitor(docutils.nodes.NodeVisitor):

    def __init__(self, document, sheet: Sheet):
        super().__init__(document)
        self.section_layout_method = common.parse_directive('stack')
        self.title_display_method = common.parse_directive('banner')
        self.style = 'default'
        self.current_style_def_name = None

        self.state = State.READY
        self.state = State.READY
        self.status = Status()
        self.sheet = sheet

    def change_state(self, status: State):
        LOGGER.info("   [changing state from '%s' -> '%s]", self.state.name, status.name)
        self.state = status

    def visit_comment(self, node: docutils.nodes.comment) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        txt = node.astext().strip()
        if not txt:
            return
        command = common.parse_directive(txt)
        if not command.tag:
            raise ValueError("Comment directive did not have a tag: '%s'", txt)
        if command.tag == 'section':
            LOGGER.info(".. setting section layout method: %s", command)
            self.section_layout_method = command
        elif command.tag == 'title':
            LOGGER.info(".. setting title display method: %s", command)
            self.title_display_method = command
        elif command.tag == 'style':
            LOGGER.info(".. setting style: %s", command)
            self.style = command.command
        else:
            raise ValueError("Unknown comment directive: '%s', line=%d", command, line_of(node))
        raise docutils.nodes.SkipChildren

    def visit_title(self, node: docutils.nodes.title) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        # Check to see if we are about to process style definitions
        if node.astext().lower() == 'styles':
            LOGGER.info("***** Starting style definition section and aborting regular processing")

            node.parent.walkabout(StyleVisitor(self.document, self.sheet))

            raise docutils.nodes.StopTraversal
        else:
            self.ensure_block()
            self.status.block.add_title()
            self.state = State.IN_TITLE

    def visit_term(self, node) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        self.ensure_block()
        self.status.block.add_title()
        self.state = State.IN_TITLE

    def visit_transition(self, node: docutils.nodes.Node) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        self.status.finish_section()

    def depart_section(self, node: docutils.nodes.Node) -> None:
        LOGGER.debug("Departing '%s'", self.status.depart(node))
        self.status.finish_section()

    def visit_section(self, node: docutils.nodes.Node) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        if self.status.block:
            # If we are handling blocks, this is a new section so finish the old
            self.status.finish_section()

        self.ensure_section()

    def visit_paragraph(self, node) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        if self.state == State.IN_CONTENT_ITEM:
            LOGGER.debug("Finished content item")
            self.state = State.IN_CONTENT
        else:
            LOGGER.debug("Ignoring paragraph marker")

    def visit_definition_list(self, node) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        self.status.block = None
        self.state = State.READY

    def visit_definition_list_item(self, node) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        self.status.block = None
        self.state = State.READY


    def visit_definition(self, node) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        self.state = State.IN_CONTENT

    def visit_bullet_list(self, node: docutils.nodes.bullet_list) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        if not self.status.block:
            raise FormatError("List without preceeding text to define a block title, line=%d", line_of(node))
        self.state = State.IN_CONTENT

    def visit_list_item(self, node: docutils.nodes.list_item) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        if not self.state in {State.IN_CONTENT, State.IN_CONTENT_ITEM}:
            raise FormatError("Unexpected list item outside of list, line=%d" % line_of(node))
        self.state = State.IN_CONTENT

    def visit_Text(self, node: docutils.nodes.Text) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))
        txt = node.astext().replace('\n', ' ')
        modifiers = self.status.style_modifers()
        if self.state == State.READY:
            raise RuntimeError("encountered text in unknown context")
        elif self.state == State.IN_TITLE:
            LOGGER.info("Adding to title '%s', style=%s, mods=%s", txt, self.style, modifiers)
            self.status.block.add_txt_to_title(txt, self.style, modifiers)
        elif self.state == State.IN_CONTENT:
            LOGGER.info("Creating new run : '%s', style=%s, mods=%s", txt, self.style, modifiers)
            self.status.block.add_content()
            self.status.block.add_txt_to_run(txt, self.style, modifiers)
            self.state = State.IN_CONTENT_ITEM
        elif self.state == State.IN_CONTENT_ITEM:
            LOGGER.info("Adding to run: '%s', style=%s, mods=%s", txt, self.style, modifiers)
            self.status.block.add_txt_to_run(txt, self.style, modifiers)
        else:
            print('UNPROCESSED TEXT:', txt)

    def visit_image(self, node: docutils.nodes.image) -> None:
        LOGGER.debug("Entering '%s'", self.status.enter(node))

        if not self.status.block or self.status.block.content:
            # New block for the image
            self.status.block = Block()
        self.status.block.image = node.attributes

    def unknown_visit(self, node: docutils.nodes.Node) -> None:
        LOGGER.debug("Entering '%s' (no special handling)", self.status.enter(node))

    def unknown_departure(self, node: docutils.nodes.Node) -> None:
        LOGGER.debug("Departing '%s'", self.status.depart(node))

    def ensure_block(self):
        if not self.status.block:
            self.ensure_section()
            display = self.title_display_method
            self.status.block = Block(title_method=display)
            LOGGER.info("... Adding block with display = %s", display)
            self.status.section.add_block(self.status.block)

    def ensure_section(self):
        if not self.status.section:
            layout = self.section_layout_method
            LOGGER.info("... Adding section with layout = %s", layout)
            self.status.section = Section(layout_method=layout)
            self.sheet.content.append(self.status.section)
            self.state = State.READY


def _modify_style(styles, key, txt):
    if not styles:
        # Ensure there is a default style
        styles['default'] = Style(font='Times', size=10, color=BLACK, align='left')

    s = styles.get(key, None)
    if not s:
        s = Style()
    items = dict((k.strip(), v.strip()) for k, v in tuple(pair.split('=') for pair in txt.split()))
    if not 'inherit' in items:
        items['inherit'] = 'default'
    for k, v in items.items():
        if k == 'inherit':
            parent = styles[v]
            s.color = s.color or parent.color
            s.size = s.size or parent.size
            s.font = s.font or parent.font
            s.align = s.align or parent.align
            s.background = s.background or parent.background
        elif k in {'color', 'foreground', 'fg'}:
            s.color = Color(v)
        elif k in {'background', 'bg'}:
            s.background = Color(v)
        elif k in {'size', 'fontSize', 'fontsize'}:
            s.size = float(v)
        elif k in {'font', 'family', 'face'}:
            s.font = str(v)
        elif k in {'align', 'alignment'}:
            s.align = str(v)
        elif k in {'border', 'borderColor'}:
            s.borderColor = Color(v) if v and not v in {'none', 'None'} else None
        elif k in {'width', 'borderWidth'}:
            s.borderWidth = float(v)
        else:
            raise ValueError("Illegal style definition: %s" % k)
    styles[key] = s


def read_sheet(file) -> Sheet:
    with open(file, 'r') as file:
        data = file.read()

    doc = parse_rst(data)

    sheet = Sheet()
    doc.walkabout(SheetVisitor(doc, sheet))
    sheet.fixup()

    sheet.print()
    return sheet
