"""A plan's `TimePlotSeries` as a Plotly figure: one row per quantity, on one time axis
in hours since the plan starts (Design.md §29).

The time axis is accurate: an axis break is made of axis sections side by side, each
with its own range, never of dates. Plotly's JSON is written directly — it is small, and
building it through plotly's objects takes longer than everything else.
"""

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
#: Of the figure's height: the gap between two rows.
ROW_GAP = 0.06

FONT_SIZE = 11
TEXT_SIZE = 9
COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e', '#8c564b']
TEXT_FILL = 'rgba(128, 128, 128, 0.18)'
BAND_OPACITY = 0.3


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


def figure_for_plotting(
    series: TimePlotSeries, title: str = '', continues: bool = False
) -> dict:
    """The figure of `series`, until its `end`. Where the plan `continues` beyond what is
    drawn — nothing in it ends — the time axis closes with `…`."""
    end = drawing_end(series) if series.end is None else series.end
    rows = list(dict.fromkeys(piece.row for piece in series.pieces))
    sections, labels = axis_sections(end, series.breaks)
    x_domains = _domains([b - a for a, b in sections], SECTION_GAP, SECTION_MIN_WIDTH)
    y_domains = _domains([1] * len(rows), ROW_GAP, 0)[::-1]  # the first row on top
    bottom = _axis('y', max(len(rows) - 1, 0))
    drawing = _Drawing(sections)
    layout = {
        'title': {'text': title, 'font': {'size': FONT_SIZE + 2}},
        'font': {'size': FONT_SIZE},
        'height': 100 * len(rows) + 130,
        'showlegend': False,
        'margin': {'l': 90, 'r': 110, 't': 50, 'b': 80},
    }
    for k, ((a, b), domain) in enumerate(zip(sections, x_domains)):
        layout[_axis('xaxis', k)] = {
            'domain': domain,
            'range': [a / HOUR, b / HOUR],
            'anchor': bottom,
            'showgrid': False,
        }
    for i, (row, domain) in enumerate(zip(rows, y_domains)):
        drawing.frame(i)
        unit = drawing.row(i, [piece for piece in series.pieces if piece.row == row])
        layout[_axis('yaxis', i)] = {
            'domain': domain,
            'anchor': 'x',
            'title': {'text': f'{row} ({unit})' if unit else row},
            'showticklabels': bool(unit),
            'zeroline': False,
        }
        if not unit:
            layout[_axis('yaxis', i)]['range'] = [0, 1]
    drawing.notes += _break_notes(labels, x_domains)
    if continues and len(labels) < len(sections):  # a trailing break says it already
        drawing.notes.append(
            _note('<b>…</b>', x_domains[-1][1], 0, anchor='left', xshift=6)
        )
    drawing.notes.append(_note('time (h)', 0.5, 0, yshift=-45))
    layout['shapes'] = drawing.shapes
    layout['annotations'] = drawing.notes
    return {'data': drawing.data, 'layout': layout}


class _Drawing:
    """The figure's traces, shapes and notes, as the rows are drawn into its sections."""

    def __init__(self, sections: list[tuple[float, float]]):
        self.sections = sections
        self.data, self.shapes, self.notes = [], [], []
        self.color = COLORS[0]

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
        self.color = COLORS[i % len(COLORS)]
        for k, (a, b) in enumerate(self.sections):
            axes = _axis('x', k), _axis('y', i)
            for piece in pieces:
                span = max(piece.start, a), min(piece.end, b)
                if span[1] <= span[0]:
                    continue
                if piece.values is not None:
                    values, unit = _shown(piece.values)
                    self.line(axes, (piece.times / HOUR).tolist(), values, piece)
                elif piece.bounds is not None:
                    unit = self.band(axes, span, piece)
                else:
                    self.text_bar(axes, span, piece.text)
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
                'line': {'color': self.color, 'width': 1.5},
                'name': piece.label,
                'hovertemplate': f'{piece.label}<extra></extra>',
                **extra,
            }
        )

    def band(self, axes, span, piece) -> str:
        """The bounds as two sharp edges, the band between them translucent, and the
        text inside; returns the unit."""
        (lower, upper), unit = _shown(_stacked(piece.bounds))
        start, end = span[0] / HOUR, span[1] / HOUR
        # The fill as a closed polygon: `tonexty` finds the wrong trace across rows.
        fill = _translucent(self.color, BAND_OPACITY)
        polygon = [lower, lower, upper, upper, lower]
        self.line(
            axes,
            [start, end, end, start, start],
            polygon,
            piece,
            fill='toself',
            fillcolor=fill,
            line={'width': 0},
        )
        self.line(axes, [start, end], [lower, lower], piece)
        self.line(axes, [start, end], [upper, upper], piece)
        x, y = axes
        self.notes.append(
            {
                'text': piece.text,
                'xref': x,
                'yref': y,
                'x': (span[0] + span[1]) / 2 / HOUR,
                'y': (lower + upper) / 2,
                'showarrow': False,
                'font': {'size': TEXT_SIZE},
            }
        )
        return unit

    def text_bar(self, axes, span, text) -> None:
        """A grey bar with its text, where the protocol states no value."""
        x, y = axes[0], f'{axes[1]} domain'
        start, end = span
        self.shapes.append(
            {
                'type': 'rect',
                'xref': x,
                'yref': y,
                'x0': start / HOUR,
                'x1': end / HOUR,
                'y0': 0.2,
                'y1': 0.8,
                'fillcolor': TEXT_FILL,
                'line': {'width': 0},
            }
        )
        self.notes.append(
            {
                'text': text,
                'xref': x,
                'yref': y,
                'x': (start + end) / 2 / HOUR,
                'y': 0.5,
                'showarrow': False,
                'font': {'size': TEXT_SIZE},
            }
        )


def _break_notes(labels: list[str], x_domains: list[list[float]]) -> list[dict]:
    """`//` on the axis at each cut, with what it hides written under it."""
    notes = []
    for k, label in enumerate(labels):
        if k + 1 < len(x_domains):
            x, anchor = (x_domains[k][1] + x_domains[k + 1][0]) / 2, 'center'
        else:
            x, anchor = x_domains[-1][1], 'left'  # it never ends: after the axis
        notes.append(_note('<b>//</b>', x, 0, anchor=anchor))
        notes.append(_note(label, x, 0, anchor=anchor, yshift=-30, size=TEXT_SIZE))
    return notes


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
