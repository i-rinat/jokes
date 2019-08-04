from collections import namedtuple
from datetime import datetime
from pprint import pprint
import cairo
import gi
import math
import time
import sys
import json

gi.require_version('Gtk', '3.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo  # noqa: E402

Color = namedtuple('Color', ['r', 'g', 'b'])
ColorPair = namedtuple('ColorPair', ['foreground', 'background'])
Point = namedtuple('Point', ['x', 'y'])

main_window = None


class Obj(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class Terminal(object):
    def __init__(self, node, terminal_type, idx, get_coords):
        self.node = node
        self.terminal_type = terminal_type
        self.idx = idx
        self.get_coords = get_coords

    def __eq__(self, other):
        return self.node == other.node and \
               self.terminal_type == other.terminal_type and \
               self.idx == other.idx


def force_int(value, base=10):
    if type(value) == int:
        return value

    if type(value) == str:
        return int(value, base)

    return 0


def curve_position(t, x0, y0, x1, y1, x2, y2, x3, y3):
    c0 = (1 - t) * (1 - t) * (1 - t)
    c1 = 3 * t * (1 - t) * (1 - t)
    c2 = 3 * t * t * (1 - t)
    c3 = t * t * t

    return Point(c0 * x0 + c1 * x1 + c2 * x2 + c3 * x3,
                 c0 * y0 + c1 * y1 + c2 * y2 + c3 * y3)


def draw_rounded_rectangle(ctx, x, y, w, h, r, top_tilt):
    pi_2 = math.pi / 2
    ctx.new_sub_path()
    ctx.arc(x + w - r + top_tilt, y + r, r, - pi_2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, pi_2)
    ctx.arc(x + r, y + h - r, r, pi_2, 2 * pi_2)
    ctx.arc(x + r + top_tilt, y + r, r, 2 * pi_2, 3 * pi_2)
    ctx.close_path()


class Wire(object):

    DOT_RADIUS = 10
    DOT_COLOR = Color(1, 0, 0)
    LINE_COLOR = Color(0, 0, 0)
    CURVE_OFFSET = 200
    LINE_WIDTH = 3

    def __init__(self, start=None, end=None, phase_getter=lambda: 0):
        self.start = start
        self.end = end
        self.phase = 0
        self.phase_getter = phase_getter
        self._update_phase(first_time=True)

    @staticmethod
    def _curve_offset(start_pos, end_pos):
        diff = (end_pos.y - start_pos.y) / 100
        return Wire.CURVE_OFFSET * min(diff * diff, 1)

    def _draw_dot(self, ctx, start_pos, end_pos, curve_offset):
        self._update_phase()
        t, _ = math.modf(self.phase)  # t is in [0..1]

        cur_pos = curve_position(t, *start_pos,
                                 start_pos.x + curve_offset, start_pos.y,
                                 end_pos.x - curve_offset, end_pos.y,
                                 *end_pos)

        pattern = cairo.RadialGradient(*cur_pos, 0, *cur_pos, self.DOT_RADIUS)
        pattern.add_color_stop_rgba(0, *self.DOT_COLOR, 1)
        pattern.add_color_stop_rgba(1, *self.DOT_COLOR, 0)
        ctx.set_source(pattern)
        ctx.arc(*cur_pos, self.DOT_RADIUS, 0, 2 * math.pi)
        ctx.fill()

    def _draw_wire(self, ctx, start_pos, end_pos, curve_offset):
        ctx.set_source_rgba(*Wire.LINE_COLOR)
        ctx.set_line_width(Wire.LINE_WIDTH)
        ctx.move_to(*start_pos)
        ctx.curve_to(start_pos.x + curve_offset, start_pos.y,
                     end_pos.x - curve_offset, end_pos.y, *end_pos)
        ctx.stroke()

    @staticmethod
    def draw_wire(ctx, start_pos, end_pos):
        ctx.set_source_rgba(*Wire.LINE_COLOR)
        ctx.set_line_width(Wire.LINE_WIDTH)
        ctx.move_to(*start_pos)
        ctx.line_to(*end_pos)
        ctx.stroke()

    def draw(self, ctx):
        if not self.start or not self.end:
            return

        start_pos = self.start.get_coords()
        end_pos = self.end.get_coords()
        if not start_pos or not end_pos:
            return

        curve_offset = self._curve_offset(start_pos, end_pos)
        self._draw_wire(ctx, start_pos, end_pos, curve_offset)
        self._draw_dot(ctx, start_pos, end_pos, curve_offset)

    def _update_phase(self, first_time=False):
        phase = self.phase_getter()
        self.phase = phase


class Node(object):

    # Intersection test result type.
    BODY = 0
    TERMINAL = 1

    # Terminal type.
    INPUT = 0
    OUTPUT = 1

    # Appearance.
    TEXT_COLOR = Color(0, 0, 0)
    BODY_COLOR = ColorPair(Color(0, 0, 0), Color(1, 1, 1))
    FROZEN_COLOR = ColorPair(Color(0.95, 0.95, 1), Color(0.7, 0.7, 1))
    TERMINAL_COLOR = ColorPair(Color(0, 0, 0), Color(0.7, 0.7, 0.7))
    HIGHLIGHT_COLOR = Color(0.1, 0.2, 0.2)

    CORNER_RADIUS = 10
    TERMINAL_RADIUS = 10
    SQUISH_Y_FACTOR = 5
    SQUISH_X_FACTOR = 2
    TILT_FACTOR = 1
    FONT_FACE = 'Sans'
    FONT_SIZE = 26
    TEXT_FILL_FACTOR = 0.7

    Intersection = namedtuple('Intersection', ['type', 'value'])

    # Precalculated constants.
    TERMINAL_RADIUS_SQUARED = TERMINAL_RADIUS * TERMINAL_RADIUS

    def __init__(self, title="?", n_inputs=1, n_outputs=1, func=None, x=0, y=0,
                 width=100, height=100, deleter=lambda _: None,
                 phase_getter=lambda: 0):
        self.title = title
        self.n_inputs = n_inputs
        self.n_outputs = n_outputs
        self.func = func
        self.deleter = deleter
        self.frozen = False
        self.cached = Obj()

        self.orig_width = width
        self.orig_height = height
        self.x = x
        self.y = y
        self.value = ''
        self.operation = ''
        self.phase = 0
        self.phase_getter = phase_getter
        self._update_phase(first_time=True)
        self.menu = None
        self.draw_functions = []
        self.input_values = {}
        self.output_values = {}

    def move(self, x, y):
        self.x = x
        self.y = y

    def get_pos(self):
        return Point(self.x, self.y)

    def _update_phase(self, first_time=False):
        phase = self.phase_getter() if not self.frozen else 0
        if self.phase == phase and not first_time:
            return

        self.phase = phase
        self.x_tilt = Node.TILT_FACTOR * math.sin(math.pi * (phase + 0.5))
        s = math.fabs(math.sin(math.pi * phase))
        s2 = s * s
        self.bottom = Node.SQUISH_Y_FACTOR * (s ** (1.0/3) - 1)
        self.left = - Node.SQUISH_X_FACTOR * s2 / 2.0
        self.width = self.orig_width + Node.SQUISH_X_FACTOR * s2
        self.height = self.orig_height - Node.SQUISH_Y_FACTOR * s2
        self.top = self.bottom - self.height

    def draw_shadow(self, ctx):
        self._update_phase()
        ctx.save()
        ctx.translate(self.x + self.orig_width * 0.5, self.y)
        ctx.scale(1, 0.2)
        p = cairo.RadialGradient(0, 0, 0, 0, 0, self.orig_width * 0.5)
        p.add_color_stop_rgba(0, 0, 0, 0, 0.6)
        p.add_color_stop_rgba(0.5, 0, 0, 0, 0.6)
        p.add_color_stop_rgba(1, 0, 0, 0, 0)
        ctx.set_source(p)
        ctx.rectangle(- 0.6 * self.orig_width, - 0.6 * self.orig_height,
                      1.2 * self.orig_width, 1.2 * self.height)
        ctx.fill()
        ctx.restore()

    def draw(self, ctx, highlighted_terminal=None):
        self._update_phase()
        ctx.save()
        ctx.translate(self.x, self.y)
        ctx.set_line_width(4)
        draw_rounded_rectangle(ctx, self.left, self.top, self.width,
                               self.height, Node.CORNER_RADIUS, self.x_tilt)
        ctx.set_source_rgb(*(Node.FROZEN_COLOR.background if self.frozen
                             else self.BODY_COLOR.background))
        ctx.fill_preserve()
        ctx.set_source_rgb(*(Node.FROZEN_COLOR.foreground if self.frozen
                             else self.BODY_COLOR.foreground))
        ctx.stroke()

        def highlighted(terminal_type, idx):
            res = highlighted_terminal is not None and \
                  highlighted_terminal.node == self and \
                  highlighted_terminal.terminal_type == terminal_type and \
                  highlighted_terminal.idx == idx
            return res

        for k in range(self.n_inputs):
            c = self._get_terminal_pos(Node.INPUT, k)
            ctx.arc(c.x, c.y, Node.TERMINAL_RADIUS, 0, 2 * math.pi)
            bg_color = Node.HIGHLIGHT_COLOR if highlighted(Node.INPUT, k) \
                else Node.TERMINAL_COLOR.background
            ctx.set_source_rgb(*bg_color)
            ctx.fill_preserve()
            ctx.set_source_rgb(*Node.TERMINAL_COLOR.foreground)
            ctx.stroke()

        for k in range(self.n_outputs):
            c = self._get_terminal_pos(Node.OUTPUT, k)
            ctx.arc(c.x, c.y, self.TERMINAL_RADIUS, 0, 2 * math.pi)
            bg_color = Node.HIGHLIGHT_COLOR if highlighted(Node.OUTPUT, k) \
                else Node.TERMINAL_COLOR.background
            ctx.set_source_rgb(*bg_color)
            ctx.fill_preserve()
            ctx.set_source_rgb(*Node.TERMINAL_COLOR.foreground)
            ctx.stroke()

        for df in self.draw_functions:
            df(ctx)
        ctx.restore()

    def get_title(self):
        return self.title

    def freeze(self, freeze):
        self.frozen = bool(freeze)

    def _get_terminal_pos(self, terminal_type, idx):
        self._update_phase()
        if terminal_type == Node.INPUT:
            if self.n_inputs == 0 or idx < 0 or idx >= self.n_inputs:
                return None
            relative_y = (idx + 0.5) / self.n_inputs
            return Point(self.left + (1 - relative_y) * self.x_tilt,
                         self.top + relative_y * self.height)

        elif terminal_type == Node.OUTPUT:
            if self.n_outputs == 0 or idx < 0 or idx >= self.n_outputs:
                return None
            relative_y = (idx + 0.5) / self.n_outputs
            return Point(self.left + self.width +
                         (1 - relative_y) * self.x_tilt,
                         self.top + relative_y * self.height)
        else:
            return None

    def _get_terminal_absolute_pos(self, terminal_type, idx):
        pos = self._get_terminal_pos(terminal_type, idx)
        return Point(pos.x + self.x, pos.y + self.y)

    def get_terminal(self, terminal_type, idx):
        return Terminal(self, terminal_type, idx,
                        lambda:
                            self._get_terminal_absolute_pos(terminal_type,
                                                            idx))

    def get_intersections(self, absolute_x, absolute_y):
        self._update_phase()
        x = absolute_x - self.x
        y = absolute_y - self.y

        for k in range(self.n_inputs):
            tx, ty = self._get_terminal_pos(Node.INPUT, k)
            dist_squared = (tx - x) * (tx - x) + (ty - y) * (ty - y)
            if dist_squared <= Node.TERMINAL_RADIUS_SQUARED:
                return Node.Intersection(Node.TERMINAL,
                                         self.get_terminal(Node.INPUT, k))

        for k in range(self.n_outputs):
            tx, ty = self._get_terminal_pos(Node.OUTPUT, k)
            dist_squared = (tx - x) * (tx - x) + (ty - y) * (ty - y)
            if dist_squared <= Node.TERMINAL_RADIUS_SQUARED:
                return Node.Intersection(Node.TERMINAL,
                                         self.get_terminal(Node.OUTPUT, k))

        if x >= self.left and x <= self.left + self.width and \
           y >= self.top and y <= self.bottom:
            return Node.Intersection(Node.BODY, self)

        return None

    def set_input(self, idx, value):
        self.input_values[idx] = value

    def set_output(self, idx, value):
        self.output_values[idx] = value

    def get_input(self, idx):
        if idx in self.input_values:
            return self.input_values[idx]
        return None

    def get_output(self, idx):
        if idx in self.output_values:
            return self.output_values[idx]
        return None

    def reset_inputs(self):
        self.input_values = {}

    def reset_outputs(self):
        self.output_values = {}

    def calculate(self):
        raise Exception("override this method")


def _generate_menu_from_description(menu_description, n_columns=1):
    menu = Gtk.Menu()
    row = 0
    column = 0

    for m in menu_description:
        if m[1] == 'title':
            row += 1 if column != 0 else 0  # Start from a new row.
            item = Gtk.MenuItem(label=m[0])
            item.set_sensitive(False)
            item.get_children()[0].set_markup('<b>' + m[0] + '</b>')
            if n_columns > 1:
                item.set_property('halign', Gtk.Align.CENTER)
            menu.attach(child=item, left_attach=0, right_attach=n_columns,
                        top_attach=row, bottom_attach=(row + 1))
            row += 1
            column = 0

        elif m[1] == 'item':
            item = Gtk.MenuItem(label=m[0])
            item.connect('activate', m[2])
            menu.attach(child=item, left_attach=column,
                        right_attach=(column + 1), top_attach=row,
                        bottom_attach=(row + 1))
            column = (column + 1) % n_columns
            row += 1 if column == 0 else 0
        elif m[1] == 'separator':
            row += 1 if column != 0 else 0  # Start from a new row.
            item = Gtk.SeparatorMenuItem()
            menu.attach(child=item, left_attach=0, right_attach=n_columns,
                        top_attach=row, bottom_attach=(row + 1))
            row += 1
            column = 0
        else:
            raise Exception("Unknown menu item type: {}".format(m[1]))

    menu.show_all()
    return menu


def ask_string(title='', description='', old_text=''):
    dialog = Gtk.MessageDialog(parent=main_window, modal=True,
                               message_type=Gtk.MessageType.QUESTION,
                               buttons=Gtk.ButtonsType.OK_CANCEL,
                               text=description)
    dialog.set_title(title)
    entry = Gtk.Entry()
    entry.set_size_request(100, 0)
    entry.set_text(str(old_text))
    entry.set_activates_default(True)

    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    hbox.pack_start(entry, True, True, 10)
    dialog.get_content_area().add(hbox)
    ok_btn = dialog.get_widget_for_response(response_id=Gtk.ResponseType.OK)
    ok_btn.set_can_default(True)
    ok_btn.grab_default()

    dialog.show_all()

    res = dialog.run()
    res_text = entry.get_text()
    dialog.destroy()

    return res_text if res == Gtk.ResponseType.OK else None


class TextNode(Node):
    def __init__(self, **kwargs):
        Node.__init__(self, **kwargs)
        self.cached.text = None
        self.cached.surface = None
        self.draw_functions.append(self._render_title)

    def get_text_surface(self, ctx, text):
        if self.cached.text == text:
            return self.cached.surface

        layout = PangoCairo.create_layout(ctx)
        layout.set_text(text, -1)
        descr = Pango.font_description_from_string(self.FONT_FACE)
        descr.set_size(Pango.SCALE * self.FONT_SIZE)
        layout.set_font_description(descr)
        PangoCairo.update_layout(ctx, layout)
        t = layout.get_pixel_size()
        scale = min(self.TEXT_FILL_FACTOR * self.width / (t.width + 1),
                    self.TEXT_FILL_FACTOR * self.height / (t.height + 1))
        if scale < 1:
            descr.set_size(scale * Pango.SCALE * self.FONT_SIZE)
            layout.set_font_description(descr)
            PangoCairo.update_layout(ctx, layout)

        t = layout.get_pixel_size()

        surface = ctx.get_target().create_similar(cairo.Content.COLOR_ALPHA,
                                                  t.width, t.height)
        new_ctx = cairo.Context(surface)
        new_ctx.set_source_rgb(*self.TEXT_COLOR)
        PangoCairo.show_layout(new_ctx, layout)

        self.cached.surface = surface
        self.cached.text = text
        return self.cached.surface

    def _render_title(self, ctx):
        surface = self.get_text_surface(ctx, self.get_title())
        surf_width, surf_height = surface.get_width(), surface.get_height()
        ctx.save()
        ctx.translate(self.left + self.width / 2.0 - surf_width / 2.0,
                      self.top + self.height / 2.0 - surf_height / 2.0)
        ctx.set_source_surface(surface)
        ctx.paint()
        ctx.restore()


class RegisterNode(TextNode):
    def __init__(self, value=0, **kwargs):
        TextNode.__init__(self, n_inputs=1, n_outputs=1, **kwargs)
        self.value = value

        self.menu = _generate_menu_from_description((
            ('Register Node', 'title', None),
            ('Set Value', 'item', lambda _: self.invoke_ask_value_dialog()),
            ('Freeze', 'item', lambda _: self.freeze(True)),
            ('Thaw', 'item', lambda _: self.freeze(False)),
            ('Remove', 'item', lambda _: self.deleter(self)),
        ), n_columns=1)

    def get_title(self):
        return ':{}'.format(self.value)

    def invoke_ask_value_dialog(self):
        text = ask_string(title='New Constant Value',
                          description='Enter new constant value:',
                          old_text=str(self.value))
        if text:
            self.value = force_int(text, 0)
            self.set_output(0, self.value)

    def calculate(self):
        if not self.frozen:
            input_0 = self.get_input(0)
            if input_0 is not None:
                self.value = force_int(input_0)

        self.set_output(0, self.value)


class ArithmeticNode(TextNode):
    def __init__(self, operation='+', **kwargs):
        TextNode.__init__(self, n_inputs=2, n_outputs=1, **kwargs)
        self.operation = operation
        self.value = None

        self.menu = _generate_menu_from_description((
            ('Arithmetic Node', 'title', None),
            ('Freeze', 'item', lambda _: self.freeze(True)),
            ('Thaw', 'item', lambda _: self.freeze(False)),
            ('(+)', 'item', lambda _: self.set_operation('+')),
            ('(×)', 'item', lambda _: self.set_operation('×')),
            ('(-)', 'item', lambda _: self.set_operation('-')),
            ('(/)', 'item', lambda _: self.set_operation('/')),
            ('(%)', 'item', lambda _: self.set_operation('%')),
            ('Remove', 'item', lambda _: self.deleter(self)),
        ), n_columns=2)

    def set_operation(self, operation):
        self.operation = operation

    def get_title(self):
        return self.operation

    def calculate(self):
        input_0 = self.get_input(0)
        input_1 = self.get_input(1)
        if input_0 is not None and input_1 is not None:
            input_0 = force_int(input_0)
            input_1 = force_int(input_1)
            if self.operation == '+':
                self.value = input_0 + input_1
            elif self.operation == '×':
                self.value = input_0 * input_1
            elif self.operation == '-':
                self.value = input_0 - input_1
            elif self.operation == '/':
                self.value = None if input_1 == 0 else input_0 // input_1
            elif self.operation == '%':
                self.value = None if input_1 == 0 else input_0 % input_1
            else:
                self.value = None
        else:
            self.value = None

        self.set_output(0, self.value)


class PointNode(TextNode):
    def __init__(self, **kwargs):
        TextNode.__init__(self, n_inputs=2, n_outputs=1, **kwargs)
        self.menu = _generate_menu_from_description((
            ('Point Node', 'title', None),
            ('Freeze', 'item', lambda _: self.freeze(True)),
            ('Thaw', 'item', lambda _: self.freeze(False)),
            ('Remove', 'item', lambda _: self.deleter(self)),
        ), n_columns=1)
        self.value = None
        self.set_output(0, self.value)

    def get_title(self):
        return '(x, y)'

    def calculate(self):
        if self.frozen:
            return

        input_0 = self.get_input(0)
        input_1 = self.get_input(1)
        if input_0 is not None and input_1 is not None:
            self.value = Point(force_int(input_0), force_int(input_1))
        else:
            self.value = None

        self.set_output(0, self.value)


class GraphNode(Node):
    FILL_FACTOR = 0.9
    NX = 40
    NY = 40
    GRID_LINE_COLOR = Color(0, 0, 0)
    POINT_COLOR = Color(1, 0, 1)
    GRID_LINE_WIDTH = 0.2

    def __init__(self, **kwargs):
        Node.__init__(self, n_inputs=8, n_outputs=0, width=300, height=300,
                      **kwargs)
        self.menu = _generate_menu_from_description((
            ('Graph Node', 'title', None),
            ('Clear', 'item', lambda _: self.clear()),
            ('Remove', 'item', lambda _: self.deleter(self)),
        ), n_columns=1)

        self.draw_functions.append(self._render_graphics)
        self.pixels = set()

    def _render_graphics(self, ctx):
        left = self.left + self.width * (1 - self.FILL_FACTOR) / 2
        top = self.top + self.height * (1 - self.FILL_FACTOR) / 2
        width = self.width * self.FILL_FACTOR
        height = self.height * self.FILL_FACTOR

        x_step = width / self.NX
        y_step = height / self.NY

        ctx.set_source_rgb(*self.GRID_LINE_COLOR)
        ctx.set_line_width(self.GRID_LINE_WIDTH)

        for k in range(0, self.NX + 1):
            ctx.move_to(left + k * x_step, top)
            ctx.line_to(left + k * x_step, top + height)

        for k in range(0, self.NY + 1):
            ctx.move_to(left, top + k * y_step)
            ctx.line_to(left + width, top + k * y_step)

        ctx.stroke()

        ctx.set_source_rgb(*self.POINT_COLOR)
        for p in self.pixels:
            if 0 <= p.x and p.x < self.NX and 0 <= p.y and p.y < self.NY:
                ctx.rectangle(left + x_step * p.x,
                              top + height - y_step * p.y - y_step,
                              x_step, y_step)

        ctx.fill()

    def calculate(self):
        for k in range(self.n_inputs):
            input_val = self.get_input(k)
            if type(input_val) == Point:
                self.pixels.add(input_val)

    def clear(self):
        self.pixels = set()


class ConditionalNode(TextNode):
    def __init__(self, operation='>', **kwargs):
        TextNode.__init__(self, n_inputs=4, n_outputs=1, height=150, **kwargs)
        self.operation = operation
        self.value = None

        self.menu = _generate_menu_from_description((
            ('Conditional Node', 'title', None),
            ('Freeze', 'item', lambda _: self.freeze(True)),
            ('Thaw', 'item', lambda _: self.freeze(False)),
            ('(>)', 'item', lambda _: self.set_operation('>')),
            ('(<)', 'item', lambda _: self.set_operation('<')),
            ('(=)', 'item', lambda _: self.set_operation('=')),
            ('(≠)', 'item', lambda _: self.set_operation('≠')),
            ('(≥)', 'item', lambda _: self.set_operation('≥')),
            ('(≤)', 'item', lambda _: self.set_operation('≤')),
            ('Remove', 'item', lambda _: self.deleter(self)),
        ), n_columns=2)

    def set_operation(self, operation):
        self.operation = operation

    def get_title(self):
        return self.operation

    def calculate(self):
        input_0 = self.get_input(0)
        input_1 = self.get_input(1)
        condition_holds = False
        if input_0 is not None and input_1 is not None:
            input_0 = force_int(input_0)
            input_1 = force_int(input_1)

            if self.operation == '>':
                condition_holds = (input_0 > input_1)

            elif self.operation == '<':
                condition_holds = (input_0 < input_1)

            elif self.operation == '=':
                condition_holds = (input_0 == input_1)

            elif self.operation == '≠':
                condition_holds = (input_0 != input_1)

            elif self.operation == '≥':
                condition_holds = (input_0 >= input_1)

            elif self.operation == '≤':
                condition_holds = (input_0 <= input_1)

        if condition_holds:
            self.set_output(0, self.get_input(2))
        else:
            self.set_output(0, self.get_input(3))


class Showtime(Gtk.Window):

    CANVAS_MOVE_SPEED = 1
    GRID_STEP = 50

    # states
    class State:
        DEFAULT = 0
        MOVING_NODE = 1
        CREATING_WIRE = 2
        MOVING_CANVAS = 3

    def __init__(self, bpm):
        Gtk.Window.__init__(self, title="Showtime Komputeishon")

        self.set_size_request(1366, 768)
        self.connect('destroy', Gtk.main_quit)

        drawing_area = Gtk.DrawingArea()
        drawing_area.connect('draw', self.handle_draw_event)
        drawing_area.connect('motion-notify-event',
                             self.handle_mouse_move_event)
        drawing_area.connect('button-press-event',
                             self.handle_mouse_press_event)
        drawing_area.connect('button-release-event',
                             self.handle_mouse_release_event)
        self.connect('key-press-event', self.handle_key_press_event)

        drawing_area.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
        drawing_area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        drawing_area.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
        drawing_area.add_events(Gdk.EventMask.BUTTON_MOTION_MASK)

        self.drawing_area = drawing_area
        self.add(drawing_area)
        self.show_all()

        self._create_menus()

        self.state = self.State.DEFAULT
        self.phase = 0
        self.current = Obj()
        self.current.pos = Point(0, 0)
        self.current.origin = Point(0, 0)
        self.current.node = None
        self.current.highlighted_terminal = None
        self.current.element = None
        self.nodes = []
        self.wires = []
        self.bpm = bpm
        self.frame_timestamps = set()
        self.fps = 0
        self.next_step = int(time.time() * self.bpm / 60.0 + 1)
        self.surface = None

        GLib.timeout_add(16, self.handle_tick)

    def add_node_at(self, node_class, x, y):
        node = node_class(deleter=self._delete_node,
                          phase_getter=self._phase_func,
                          x=(self.current.origin.x + x),
                          y=(self.current.origin.y + y))
        self.nodes.append(node)
        return node

    def _delete_node(self, node):
        self.nodes = list(filter(lambda n: n != node, self.nodes))
        self.wires = list(filter(lambda w: w.start.node != node and
                                 w.end.node != node,
                                 self.wires))

    def _disconnect_terminal(self, terminal):
        if self.current.element is None or \
           self.current.element.type != Node.TERMINAL:
            return
        t = self.current.element.value
        self.wires = list(filter(lambda w: w.start != t and w.end != t,
                                 self.wires))

    def _create_menus(self):
        self.menus = Obj()
        self.menus.blank_space = _generate_menu_from_description((
            ('Add Node', 'title', None),
            ('Register', 'item',
             lambda _: self.add_node_at(RegisterNode, *self.current.pos)),
            ('Arithmetic', 'item',
             lambda _: self.add_node_at(ArithmeticNode, *self.current.pos)),
            ('Point', 'item',
             lambda _: self.add_node_at(PointNode, *self.current.pos)),
            ('Conditional', 'item',
             lambda _: self.add_node_at(ConditionalNode, *self.current.pos)),
            ('Graph', 'item',
             lambda _: self.add_node_at(GraphNode, *self.current.pos)),
            ('', 'separator', None),
            ('Schema', 'title', None),
            ('Save', 'item', lambda _: print('TODO: save')),
            ('Load', 'item', lambda _: print('TODO: load')),
        ), n_columns=2)

        self.menus.terminal = _generate_menu_from_description((
            ('Terminal', 'title', None),
            ('Disconnect', 'item', self._disconnect_terminal),
        ), n_columns=1)

    def _phase_func(self):
        return self.phase

    def add_wire(self, start, end):
        if start.node == end.node:
            return

        wire_ends = (start.terminal_type, end.terminal_type)
        if wire_ends == (Node.INPUT, Node.OUTPUT):
            start, end = end, start
        elif wire_ends == (Node.OUTPUT, Node.INPUT):
            pass  # Just what we wanted.
        else:
            # Ignoring input-input and output-output wires.
            return

        self.wires = list(filter(lambda w: w.end != end, self.wires))
        wire = Wire(start=start, end=end, phase_getter=self._phase_func)
        self.wires.append(wire)

    def draw_canvas(self, geometry, ctx):
        ctx.set_source_rgb(0.3, 0.5, 0.5)
        ctx.paint()

        ctx.set_source_rgb(0, 0, 0)

        gx = int(self.current.origin.x / self.GRID_STEP)
        gy = int(self.current.origin.y / self.GRID_STEP)

        x = gx * self.GRID_STEP - self.current.origin.x
        n = gx
        while x < geometry.width:
            ctx.set_line_width(0.3 if n % 5 == 0 else 0.15)
            ctx.move_to(x, 0)
            ctx.line_to(x, geometry.height)
            ctx.stroke()
            x += self.GRID_STEP
            n += 1

        y = gy * self.GRID_STEP - self.current.origin.y
        n = gy
        while y < geometry.height:
            ctx.set_line_width(0.3 if n % 5 == 0 else 0.15)
            ctx.move_to(0, y)
            ctx.line_to(geometry.width, y)
            ctx.stroke()
            y += self.GRID_STEP
            n += 1

        ctx.save()
        ctx.set_source_rgba(0, 0, 0, 0.2)
        ctx.arc(-self.current.origin.x, -self.current.origin.y,
                5, 0, 2 * math.pi)
        ctx.fill()
        ctx.restore()

    def draw_metainfo(self, ctx):
        ctx.save()
        ctx.scale(2, 2)
        ctx.set_source_rgb(0, 0, 0)
        ctx.move_to(2, 9)
        ctx.show_text('origin: ({:.0f},{:.0f})'.format(*self.current.origin))
        ctx.move_to(2, 19)
        ctx.show_text('nodes: {}'.format(len(self.nodes)))
        ctx.move_to(2, 29)
        ctx.show_text('wires: {}'.format(len(self.wires)))
        ctx.move_to(2, 39)
        ctx.show_text('fps: {}'.format(self.fps))
        ctx.restore()

    def update_fps_counter(self):
        current_timestamp = time.time()
        self.frame_timestamps = \
            set(filter(lambda ts: ts > current_timestamp - 1,
                       self.frame_timestamps))
        self.frame_timestamps.add(current_timestamp)
        self.fps = len(self.frame_timestamps)

        # Avoid flickering 61/60.
        self.fps = self.fps if self.fps != 61 else 60

    def get_cached_image_surface(self, width, height):
        if self.surface is not None and \
           self.surface.get_width() == width and \
           self.surface.get_height() == height:
            return self.surface

        self.surface = cairo.ImageSurface(cairo.Format.RGB24, width, height)
        return self.surface

    def handle_draw_event(self, widget, ctx):

        orig_ctx = ctx
        a = widget.get_allocation()
        surface = self.get_cached_image_surface(a.width, a.height)
        ctx = cairo.Context(surface)

        self.update_fps_counter()

        self.draw_canvas(widget.get_allocation(), ctx)

        ctx.save()
        ctx.translate(- self.current.origin.x, - self.current.origin.y)

        for wire in self.wires:
            wire.draw(ctx)

        if self.state == self.State.CREATING_WIRE and \
           self.wire_end_pos is not None:
            Wire.draw_wire(ctx, self.wire_start.get_coords(),
                           self.wire_end_pos)

        for node in self.nodes:
            node.draw_shadow(ctx)

        for node in self.nodes:
            node.draw(ctx,
                      highlighted_terminal=self.current.highlighted_terminal)

        ctx.restore()

        self.draw_metainfo(ctx)

        orig_ctx.set_source_surface(surface, 0, 0)
        orig_ctx.paint()

    def calculate(self):
        for wire in self.wires:
            value = wire.start.node.get_output(wire.start.idx)
            wire.end.node.set_input(wire.end.idx, value)

        for node in self.nodes:
            node.reset_outputs()
            node.calculate()
            node.reset_inputs()

    def handle_tick(self):
        self.phase = time.time() * self.bpm / 60.0
        self.drawing_area.queue_draw()
        if self.phase > self.next_step:
            self.next_step = self.next_step + 1
            self.calculate()

        return True

    def handle_mouse_move_event(self, widget, event):
        diff = Point(event.x - self.current.pos.x,
                     event.y - self.current.pos.y)
        self.current.pos = Point(event.x, event.y)

        if self.state == self.State.MOVING_NODE:
            self.moving_node.x = event.x - self.moving_node_offset.x
            self.moving_node.y = event.y - self.moving_node_offset.y

        elif self.state == self.State.CREATING_WIRE:
            self.current.pos = Point(event.x, event.y)
            self.wire_end_pos = Point(self.current.origin.x + event.x,
                                      self.current.origin.y + event.y)

        elif self.state == self.State.MOVING_CANVAS:
            self.current.origin = Point(
                self.current.origin.x - diff.x * self.CANVAS_MOVE_SPEED,
                self.current.origin.y - diff.y * self.CANVAS_MOVE_SPEED)

        self.current.highlighted_terminal = None
        for node in reversed(self.nodes):
            res = node.get_intersections(self.current.origin.x + event.x,
                                         self.current.origin.y + event.y)
            if not res:
                continue

            if res.type == Node.TERMINAL:
                self.current.highlighted_terminal = res.value

    def _get_element_at(self, pos):
        for node in reversed(self.nodes):
            res = node.get_intersections(pos.x + self.current.origin.x,
                                         pos.y + self.current.origin.y)
            if res:
                return res
        return None

    def handle_mouse_press_event(self, widget, event):
        res = self._get_element_at(Point(event.x, event.y))
        self.current.element = res

        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 1:
            if res is not None and res.type == Node.BODY:
                self.moving_node = res.value
                self.moving_node_offset = Point(event.x - res.value.x,
                                                event.y - res.value.y)
                self.state = self.State.MOVING_NODE

            if res is not None and res.type == Node.TERMINAL:
                self.state = self.State.CREATING_WIRE
                self.wire_start = res.value
                self.wire_end_pos = res.value.get_coords()

            if res is None:
                self.state = self.State.MOVING_CANVAS
                self.current.pos = Point(event.x, event.y)

        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            if res is None:
                self.menus.blank_space.popup_at_pointer(event)
            elif res.type == Node.BODY:
                if res.value.menu is not None:
                    res.value.menu.popup_at_pointer(event)
            elif res.type == Node.TERMINAL:
                self.menus.terminal.popup_at_pointer(event)

    def handle_mouse_release_event(self, widget, event):
        if event.type == Gdk.EventType.BUTTON_RELEASE and event.button == 1:
            if self.state == self.State.CREATING_WIRE:
                res = self._get_element_at(Point(event.x, event.y))
                if res is not None and res.type == Node.TERMINAL:
                    if res.value != self.wire_start:
                        self.add_wire(self.wire_start, res.value)

        self.state = self.State.DEFAULT

    def handle_key_press_event(self, widget, event):
        KEY_r = 27
        KEY_t = 28
        KEY_a = 38
        KEY_d = 40
        KEY_f = 41
        KEY_v = 55
        KEY_F6 = 72
        KEY_F9 = 75

        if event.hardware_keycode == KEY_r:
            self.add_node_at(RegisterNode, *self.current.pos)

        if event.hardware_keycode == KEY_a:
            self.add_node_at(ArithmeticNode, *self.current.pos)

        if event.hardware_keycode == KEY_f or event.hardware_keycode == KEY_t:
            res = self._get_element_at(self.current.pos)
            if res is not None and res.type == Node.BODY:
                res.value.freeze(event.hardware_keycode == KEY_f)

        if event.hardware_keycode == KEY_d:
            res = self._get_element_at(self.current.pos)
            if res is not None and res.type == Node.BODY:
                self._delete_node(res.value)

        if event.hardware_keycode == KEY_v:
            res = self._get_element_at(self.current.pos)
            if res is not None and res.type == Node.BODY and \
               type(res.value) == RegisterNode:
                res.value.invoke_ask_value_dialog()

        if event.hardware_keycode == KEY_F9:
            self.save_state()

        if event.hardware_keycode == KEY_F6:
            self.restore_state()

    def save_state(self):
        text = ask_string(title='Save State', description='---', old_text='')
        if text is None:
            return

        def serialize_nodes():
            res = []
            for node in self.nodes:
                node_descr = {'type': type(node).__name__,
                              'value': node.value,
                              'frozen': node.frozen,
                              'operation': node.operation,
                              'x': node.x,
                              'y': node.y}
                res.append(node_descr)
            return res

        def serialize_terminal(t):
            return {'node': self.nodes.index(t.node),
                    'terminal_type': t.terminal_type,
                    'idx': t.idx}

        def serialize_wires():
            res = []
            for wire in self.wires:
                wire_descr = {'start': serialize_terminal(wire.start),
                              'end': serialize_terminal(wire.end)}
                res.append(wire_descr)
            return res

        state = {'nodes': serialize_nodes(),
                 'wires': serialize_wires()}

        with open('state.json', 'w') as f:
            f.write(json.dumps(state, indent=4))

        print('state saved, {} node{}, {} wire{}'.format(
              len(self.nodes), 's' if len(self.nodes) > 0 else '',
              len(self.wires), 's' if len(self.wires) > 0 else ''))

    def restore_state(self):
        self.current.origin = Point(0, 0)
        self.nodes = []
        self.wires = []

        with open('state.json') as f:
            state = json.loads(f.read())

        for node in state['nodes']:
            if not node['type'].endswith('Node'):
                continue

            node_class = globals()[node['type']]
            obj = self.add_node_at(node_class, node['x'], node['y'])
            obj.value = node['value']
            obj.frozen = node['frozen']
            obj.operation = node['operation']

        for wire in state['wires']:
            def get_terminal(s):
                return self.nodes[s['node']].get_terminal(s['terminal_type'],
                                                          s['idx'])
            self.add_wire(get_terminal(wire['start']),
                          get_terminal(wire['end']))

        print('state restored, {} node{}, {} wire{}'.format(
              len(self.nodes), 's' if len(self.nodes) > 0 else '',
              len(self.wires), 's' if len(self.wires) > 0 else ''))


if __name__ == '__main__':
    bpm = 130
    if len(sys.argv) >= 2:
        bpm = float(sys.argv[1])

    main_window = Showtime(bpm=bpm)
    Gtk.main()
