"""A plan's `TimePlotSeries` as a Plotly figure: one row per quantity, on one time axis
in hours since the plan starts (Design.md §29).

The time axis is accurate: an axis break is made of axis sections side by side, each
with its own range, never of dates. Plotly's JSON is written directly — it is small, and
building it through plotly's objects takes longer than everything else.
"""

import re
from dataclasses import replace
from math import inf

import numpy as np

from nomad_pv_stability_measurements.schema_packages.utils import (
    AxisBreak,
    TimePlotSeries,
    drawing_end,
)

HOUR = 3600.0

#: Of the figure's width: the least an axis section takes, and the gap between two.
SECTION_MIN_WIDTH = 0.12
SECTION_GAP = 0.03
#: Of the rows' height: the gap between two rows.
ROW_GAP = 0.06
#: Of the figure's height: what separates the time axis from the lowest row.
AXIS_GAP = 0.05
#: Of the last section: how far the axis, and what never ends, go on past the drawing
#: of a plan that never ends, up to the `⋯`.
OVERHANG = 0.05

#: px: the height of one row, and of everything around the rows together.
ROW_HEIGHT = 150
FRAME_HEIGHT = 180
#: px: the left margin, where the row labels stand, one above the other.
LABEL_MARGIN = 125
#: px: about how wide the rows are drawn — NOMAD fits the figure to the page.
PLOT_WIDTH = 650

FONT_SIZE = 15
AXIS_FONT_SIZE = 17
#: The text inside the rows: as large as fits, never smaller than readable.
TEXT_SIZES = (11, 18)
#: How wide a character is, of the font size.
CHARACTER_WIDTH = 0.55

#: One colour per role, whatever the quantity (`role_for_plotting`). Of middle
#: lightness, so they read on a light and on a dark page alike.
ROLE_COLORS = {
    'controlled': '#3b8fe0',
    'specified': '#a77ee0',
    'monitored': '#35b06a',
    'unspecified': '#9a9a9a',
}
BAR_OPACITY = 0.25
BAND_OPACITY = 0.3
TOLERANCE_OPACITY = 0.2
#: What the drawing assumes and the protocol does not state.
ASSUMPTION_COLOR = '#e5534b'
#: The time axis and its marks: a grey that stands out on a light and a dark page.
AXIS_COLOR = '#8c8c8c'
#: The rows' background and grid: grey, translucent, over whichever page is behind.
ROW_BACKGROUND = 'rgba(128, 128, 128, 0.1)'
GRID_COLOR = 'rgba(128, 128, 128, 0.3)'
#: Of a row's values: the room above and below them, so a line at the edge is whole.
VALUE_MARGIN = 0.06

#: The rows, top to bottom: the light first, the electrical load last; any other
#: quantity in between, in the order the plan names it.
TOP_ROWS = (
    'irradiance',
    'temperature',
    'relative humidity',
    'absolute humidity',
    'oxygen fraction',
)
BOTTOM_ROWS = ('electrical load', 'voltage', 'current', 'resistance')


def axis_sections(end: float, breaks: list[AxisBreak]):
    """The stretches of `[0, end]` the axis shows, with what the breaks hide cut out,
    and the label of each cut, in order. A cut past `end` — a block that never ends —
    closes the axis, so there is one label more than there are gaps."""
    sections, labels = [], []
    start = 0.0
    for cut in sorted(breaks, key=lambda cut: cut.start):
        if cut.start < start:
            continue  # inside a stretch already hidden, as a nested block's break
        sections.append((start, min(cut.start, end)))
        labels.append(cut.label)
        start = cut.end
        if start >= end:
            return sections, labels
    sections.append((start, end))
    return sections, labels


def fitting_size(text: str, width: float) -> int | None:
    """The largest text size, up to `TEXT_SIZES`' largest, at which `text` fits in
    `width` px; `None` where not even the smallest does — it is left out."""
    size = int(width / (CHARACTER_WIDTH * len(re.sub(r'<[^>]+>', '', text))))
    return None if size < TEXT_SIZES[0] else min(size, TEXT_SIZES[1])


def text_size(pieces, sections, x_domains) -> int:
    """One size for the text inside a row: as large as its narrowest text still fits in
    its bar — large where the value is constant, smaller with many repetitions. Text
    too long for its bar at any size is left out, and does not shrink the rest."""
    sizes = [TEXT_SIZES[1]]
    for piece in pieces:
        if not piece.text:
            continue
        for (a, b), (left, right) in zip(sections, x_domains):
            shown = min(piece.end, b) - max(piece.start, a)
            if shown > 0:
                size = fitting_size(
                    piece.text, shown / (b - a) * (right - left) * PLOT_WIDTH
                )
                sizes += [size] if size is not None else []
    return min(sizes)


def figure_for_plotting(
    series: TimePlotSeries, title: str = '', continues: bool = False
) -> dict:
    """The figure of `series`, until its `end`. Where the plan `continues` beyond what is
    drawn — nothing in it ends — the time axis, and what never ends, go on a little
    further, up to `⋯`."""
    end = drawing_end(series) if series.end is None else series.end
    rows = sorted(dict.fromkeys(piece.row for piece in series.pieces), key=_row_order)
    sections, labels = axis_sections(end, series.breaks)
    pieces = series.pieces
    # A block that never ends closes the axis: the `⋯` says it goes on, no label.
    endless_break = len(labels) == len(sections) and any(
        cut.end == inf for cut in series.breaks
    )
    goes_on = continues and (len(labels) < len(sections) or endless_break)
    if goes_on and endless_break:
        labels.pop()
    if goes_on:
        a, b = sections[-1]
        sections[-1] = (a, b + OVERHANG * (b - a))
        pieces = [_going_on(piece, end, sections[-1][1]) for piece in pieces]
    x_domains = _domains([b - a for a, b in sections], SECTION_GAP, SECTION_MIN_WIDTH)
    y_domains = [
        [AXIS_GAP + (1 - AXIS_GAP) * low, AXIS_GAP + (1 - AXIS_GAP) * high]
        for low, high in _domains([1] * len(rows), ROW_GAP, 0)[::-1]  # first on top
    ]
    drawing = _Drawing(sections, x_domains)
    layout = {
        'title': {
            'text': f'<b>{_subscripts(title)}</b>' if title else '',
            'font': {'size': FONT_SIZE + 2},
        },
        'font': {'size': FONT_SIZE},
        'height': ROW_HEIGHT * len(rows) + FRAME_HEIGHT,
        'showlegend': False,
        'margin': {'l': LABEL_MARGIN, 'r': 95, 't': 80, 'b': 95},
        # The page shows through, light or dark; the text takes the page's colour.
        'paper_bgcolor': 'rgba(0, 0, 0, 0)',
        'plot_bgcolor': ROW_BACKGROUND,
    }
    for k, ((a, b), domain) in enumerate(zip(sections, x_domains)):
        layout[_axis('xaxis', k)] = {
            'domain': domain,
            'range': [a / HOUR, b / HOUR],
            # Below the rows, on its own: a thick line with ticks.
            'anchor': 'free',
            'position': 0,
            'showline': True,
            'linecolor': AXIS_COLOR,
            'linewidth': 3,
            'ticks': 'outside',
            'tickcolor': AXIS_COLOR,
            'tickwidth': 2,
            'ticklen': 8,
            'tickfont': {'size': AXIS_FONT_SIZE},
            # Few ticks in a narrow section, and never turned on their side.
            'nticks': max(2, round(12 * (domain[1] - domain[0]))),
            'tickangle': 0,
            'showgrid': False,
            'zeroline': False,
        }
    for i, (row, domain) in enumerate(zip(rows, y_domains)):
        drawing.frame(i)
        unit = drawing.row(i, [piece for piece in pieces if piece.row == row])
        layout[_axis('yaxis', i)] = {
            'domain': domain,
            'anchor': 'x',
            'showticklabels': bool(unit),
            'gridcolor': GRID_COLOR,
            'zeroline': False,
        }
        layout[_axis('yaxis', i)]['range'] = drawing.value_range() if unit else [0, 1]
        drawing.notes.append(_row_label(row, unit, domain))
    drawing.notes += _break_notes(labels, x_domains)
    if goes_on:
        drawing.notes.append(_on_axis('<b>⋯</b>', x_domains[-1][1], 'left', xshift=4))
    drawing.notes.append(_note('time (h)', 0.5, 0, yshift=-55, size=AXIS_FONT_SIZE))
    drawing.notes.append(_legend())
    layout['shapes'] = drawing.shapes
    layout['annotations'] = drawing.notes
    return {'data': drawing.data, 'layout': layout}


class _Drawing:
    """The figure's traces, shapes and notes, as the rows are drawn into its sections."""

    def __init__(self, sections: list[tuple[float, float]], x_domains):
        self.sections, self.x_domains = sections, x_domains
        self.size = TEXT_SIZES[1]
        self.data, self.shapes, self.notes = [], [], []
        self.color = ROLE_COLORS['unspecified']
        #: px per second in the section being drawn.
        self.px_per_second = 1.0
        #: The least and the greatest value drawn in the current row, in the unit it is
        #: shown in.
        self.lowest = self.highest = 0.0

    def frame(self, i: int) -> None:
        """An invisible trace in each section of the `i`-th row: Plotly draws only the
        axes some trace is on, and a row of text alone has none."""
        for k, (a, b) in enumerate(self.sections):
            self.data.append(
                {
                    'type': 'scatter',
                    'mode': 'lines',
                    'x': [a / HOUR, b / HOUR],
                    'y': [None, None],
                    'xaxis': _axis('x', k),
                    'yaxis': _axis('y', i),
                    'hoverinfo': 'skip',
                }
            )

    def row(self, i: int, pieces) -> str:
        """Draws the `i`-th row's pieces into every section they reach; returns the
        row's unit, empty where it only has text."""
        unit = ''
        self.lowest = self.highest = 0.0
        noted = set()
        self.size = text_size(pieces, self.sections, self.x_domains)
        for k, (a, b) in enumerate(self.sections):
            axes = _axis('x', k), _axis('y', i)
            left, right = self.x_domains[k]
            self.px_per_second = (right - left) * PLOT_WIDTH / (b - a)
            for piece in pieces:
                span = max(piece.start, a), min(piece.end, b)
                if span[1] <= span[0]:
                    continue
                self.color = ROLE_COLORS.get(piece.role, ROLE_COLORS['unspecified'])
                if piece.values is not None:
                    if piece.bounds is not None:
                        self.band(axes, span, piece, edges=False)
                    values, unit = _shown(piece.values)
                    self.lowest = min([self.lowest, *values])
                    self.highest = max([self.highest, *values])
                    times = (piece.times / HOUR).tolist()
                    if piece.assumption:
                        # Dashed: a plausible drawing, not what the protocol states.
                        width = {'color': self.color, 'width': 2.5, 'dash': 'dash'}
                        self.line(axes, times, values, piece, line=width)
                    else:
                        self.line(axes, times, values, piece)
                elif piece.bounds is not None:
                    unit = self.band(axes, span, piece, edges=True)
                else:
                    self.text_bar(axes, span, piece.text)
                # Once per piece, where it is first drawn.
                notes = [note for note in (piece.assumption, piece.typical) if note]
                if notes and id(piece) not in noted:
                    noted.add(id(piece))
                    self.assumption(axes, span, '; '.join(notes))
        return unit

    def line(self, axes, times, values, piece, **extra) -> None:
        x, y = axes
        self.data.append(
            {
                'type': 'scatter',
                'mode': 'lines',
                'x': times,
                'y': values,
                'xaxis': x,
                'yaxis': y,
                'line': {'color': self.color, 'width': 2.5},
                'name': _subscripts(piece.label),
                'hovertemplate': f'{_subscripts(piece.label)}<extra></extra>',
                **extra,
            }
        )

    def band(self, axes, span, piece, edges: bool) -> str:
        """The area between the bounds, translucent: with two sharp edges and the text
        inside where the bounds are what is kept (`HoldBetween`), plain around a value
        where they are its tolerance. Returns the unit."""
        (lower, upper), unit = _shown(_stacked(piece.bounds))
        self.lowest = min(self.lowest, lower)
        self.highest = max(self.highest, upper)
        start, end = span[0] / HOUR, span[1] / HOUR
        # The fill as a closed polygon: `tonexty` finds the wrong trace across rows.
        opacity = BAND_OPACITY if edges else TOLERANCE_OPACITY
        self.line(
            axes,
            [start, end, end, start, start],
            [lower, lower, upper, upper, lower],
            piece,
            fill='toself',
            fillcolor=_translucent(self.color, opacity),
            line={'width': 0},
        )
        if not edges:
            return unit
        self.line(axes, [start, end], [lower, lower], piece)
        self.line(axes, [start, end], [upper, upper], piece)
        if self.fits(piece.text, span):
            text = self.text(piece.text, axes[0], axes[1], (start + end) / 2)
            text['y'] = (lower + upper) / 2
            self.notes.append(text)
        return unit

    def value_range(self) -> list[float]:
        """The row's axis: 0 and every value drawn, with a little room around, so a
        line at 0 is as thick as any other."""
        low, high = min(self.lowest, 0.0), max(self.highest, 0.0)
        span = (high - low) or 1.0  # darkness alone: 0 at the foot of the row
        return [low - VALUE_MARGIN * span, low + (1 + VALUE_MARGIN) * span]

    def assumption(self, axes, span, text: str) -> None:
        """In red, just above the row: what is drawn but not stated, or not fixed."""
        start, end = span[0] / HOUR, span[1] / HOUR
        note = self.text(text, axes[0], f'{axes[1]} domain', (start + end) / 2)
        note.update(y=1, yanchor='bottom', font={'size': TEXT_SIZES[0] + 1})
        note['font']['color'] = ASSUMPTION_COLOR
        self.notes.append(note)

    def text_bar(self, axes, span, text) -> None:
        """A bar in its role's colour, with its text, where the protocol states no
        value."""
        x, y = axes[0], f'{axes[1]} domain'
        start, end = span[0] / HOUR, span[1] / HOUR
        self.shapes.append(
            {
                'type': 'rect',
                'xref': x,
                'yref': y,
                'x0': start,
                'x1': end,
                'y0': 0.2,
                'y1': 0.8,
                'fillcolor': _translucent(self.color, BAR_OPACITY),
                'line': {'width': 0},
            }
        )
        if self.fits(text, span):
            self.notes.append(self.text(text, x, y, (start + end) / 2))

    def fits(self, text: str, span) -> bool:
        """Whether `text` fits in its bar at some size; if not, only the colour says
        what it is, and the block's own figure has the room."""
        width = (span[1] - span[0]) * self.px_per_second
        return fitting_size(text, width) is not None

    def text(self, text: str, x: str, y: str, at: float) -> dict:
        """Text inside a row, at `at` hours, halfway up."""
        return {
            'text': _subscripts(text),
            'xref': x,
            'yref': y,
            'x': at,
            'y': 0.5,
            'showarrow': False,
            'font': {'size': self.size},
        }


def _row_order(row: str) -> int:
    """Where `row` stands, top to bottom (`TOP_ROWS`, `BOTTOM_ROWS`)."""
    if row in TOP_ROWS:
        return TOP_ROWS.index(row)
    if row in BOTTOM_ROWS:
        return len(TOP_ROWS) + 1 + BOTTOM_ROWS.index(row)
    return len(TOP_ROWS)


def _subscripts(text: str) -> str:
    """`V_MPP` as V<sub>MPP</sub>: Plotly's own markup, shown by every NOMAD GUI —
    LaTeX needs MathJax on the page, and a whole text of it."""
    return re.sub(r'\b([A-Za-z])_(\w+)', r'\1<sub>\2</sub>', text)


def _row_label(row: str, unit: str, domain: list[float]) -> dict:
    """The row's name, and its unit below, at one place left of every row: aligned
    whether or not the row has ticks."""
    text = f'{row}<br>({unit})' if unit else row
    middle = (domain[0] + domain[1]) / 2
    label = _note(text, 0, middle, anchor='left', xshift=-LABEL_MARGIN + 5)
    # Fixed, not `auto`: Plotly moves a label in the lower third of the figure.
    label.update(textangle=-90, yanchor='middle')
    return label


def _legend() -> dict:
    """What the colours mean, above the rows on the right."""
    keys = [
        f'<span style="color:{color}">■</span> {role}'
        for role, color in ROLE_COLORS.items()
    ]
    return _note('   '.join(keys), 1, 1, anchor='right', yshift=35)


def _break_notes(labels: list[str], x_domains: list[list[float]]) -> list[dict]:
    """`//` on the axis at each cut, with what it hides written under it."""
    notes = []
    for k, label in enumerate(labels):
        if k + 1 < len(x_domains):
            x, anchor = (x_domains[k][1] + x_domains[k + 1][0]) / 2, 'center'
        else:
            x, anchor = x_domains[-1][1], 'left'  # it never ends: after the axis
        notes.append(_on_axis('<b>//</b>', x, anchor))
        # Above the axis, below the lowest row: the tick labels are underneath.
        above = _note(label, x, 0, anchor=anchor, yshift=10, size=TEXT_SIZES[0] + 1)
        above['yanchor'] = 'bottom'
        notes.append(above)
    return notes


def _on_axis(text: str, x: float, anchor: str, xshift: int = 0) -> dict:
    """A mark centred on the time axis's line, as `//` and `⋯`."""
    mark = _note(text, x, 0, anchor=anchor, xshift=xshift, size=AXIS_FONT_SIZE)
    mark['yanchor'] = 'middle'
    mark['font']['color'] = AXIS_COLOR
    return mark


def _going_on(piece, end: float, to: float):
    """`piece`, carried on from `end` to `to` where it never ends: its value held, or
    its cycle repeated."""
    if not (piece.endless and piece.end >= end):
        return piece
    if piece.times is None:
        return replace(piece, end=to)
    times, values = piece.times, piece.values.magnitude
    if piece.cycle:
        # The corners of the cycles to come, read off the first one.
        later = np.concatenate([times + k * piece.cycle for k in range(1, 4)])
        more = np.append(later[(later > times[-1]) & (later < to)], to)
        phase = piece.start + (more - piece.start) % piece.cycle
        values = np.append(values, np.interp(phase, times, values))
    else:
        more = np.array([to])
        values = np.append(values, values[-1])
    return replace(
        piece,
        end=to,
        times=np.append(times, more),
        values=values * piece.values.units,
    )


def _note(text: str, x: float, y: float, **style) -> dict:
    """Text placed on the figure as a whole; `style` takes `anchor`, `xshift`,
    `yshift` and `size`."""
    return {
        'text': text,
        'xref': 'paper',
        'yref': 'paper',
        'x': x,
        'y': y,
        'xanchor': style.get('anchor', 'center'),
        'xshift': style.get('xshift', 0),
        'yshift': style.get('yshift', 0),
        'showarrow': False,
        'font': {'size': style.get('size', FONT_SIZE)},
    }


def _domains(lengths: list[float], gap: float, least: float) -> list[list[float]]:
    """Side by side in `[0, 1]`, `gap` apart, each in proportion to its length but at
    least `least` of the whole."""
    room = 1 - gap * (len(lengths) - 1)
    total = sum(lengths) or 1
    widths = [max(length / total, least) for length in lengths]
    scale = room / sum(widths)
    domains, start = [], 0.0
    for width in widths:
        domains.append([start, min(start + width * scale, 1.0)])
        start += width * scale + gap
    return domains


def _shown(values) -> tuple[list[float], str]:
    """Values the way a person reads them: a temperature in °C, a fraction in %."""
    if values.check('[temperature]'):
        values = values.to('degC')
    elif values.dimensionless:
        values = values.to('percent')
    return np.asarray(values.magnitude).tolist(), f'{values.units:~P}'


def _stacked(bounds):
    """`(lower, upper)` as one array, in the upper bound's unit."""
    lower, upper = bounds
    return np.array([lower.to(upper.units).magnitude, upper.magnitude]) * upper.units


def _translucent(color: str, opacity: float) -> str:
    """`#1f77b4` as `rgba(31, 119, 180, opacity)`."""
    red, green, blue = (int(color[n : n + 2], 16) for n in (1, 3, 5))
    return f'rgba({red}, {green}, {blue}, {opacity})'


def _axis(name: str, index: int) -> str:
    """Plotly's name of the `index`-th axis: `x`, `x2`, … or `xaxis`, `xaxis2`, …"""
    return name if index == 0 else f'{name}{index + 1}'
