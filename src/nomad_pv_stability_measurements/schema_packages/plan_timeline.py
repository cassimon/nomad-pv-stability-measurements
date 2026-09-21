"""A plan's `TimePlotSeries` as a Plotly figure: one row per quantity, on one time axis
in hours since the plan starts (Design.md §29).

The time axis is accurate: an axis break is made of axis sections side by side, each
with its own range, never of dates. Plotly's JSON is written directly — it is small, and
building it through plotly's objects takes longer than everything else.
"""

from nomad_pv_stability_measurements.schema_packages.utils import (
    AxisBreak,
    TimePlotSeries,
)

HOUR = 3600.0

#: Of the figure's width: the least an axis section takes, and the gap between two.
SECTION_MIN_WIDTH = 0.12
SECTION_GAP = 0.03
#: Of the figure's height: the gap between two rows.
ROW_GAP = 0.06

COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e', '#8c564b']
TEXT_FILL = 'rgba(128, 128, 128, 0.18)'


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


def figure_for_plotting(series: TimePlotSeries, end: float, title: str = '') -> dict:
    """The figure of `series`, drawn until `end` (seconds since the plan starts)."""
    rows = list(dict.fromkeys(piece.row for piece in series.pieces))
    sections, labels = axis_sections(end, series.breaks)
    x_domains = _domains([b - a for a, b in sections], SECTION_GAP, SECTION_MIN_WIDTH)
    y_domains = _domains([1] * len(rows), ROW_GAP, 0)[::-1]  # the first row on top
    bottom = _axis('y', max(len(rows) - 1, 0))
    drawing = _Drawing(sections)
    layout = {
        'title': {'text': title},
        'height': 110 * len(rows) + 140,
        'showlegend': False,
        'margin': {'l': 90, 'r': 130, 't': 50, 'b': 90},
    }
    for k, ((a, b), domain) in enumerate(zip(sections, x_domains)):
        layout[_axis('xaxis', k)] = {
            'domain': domain,
            'range': [a / HOUR, b / HOUR],
            'anchor': bottom,
            'showgrid': False,
        }
    for i, (row, domain) in enumerate(zip(rows, y_domains)):
        pieces = [piece for piece in series.pieces if piece.row == row]
        drawing.frame(i)
        unit = drawing.row(i, pieces)
        layout[_axis('yaxis', i)] = {
            'domain': domain,
            'anchor': 'x',
            'title': {'text': f'{row} ({unit})' if unit else row},
            'showticklabels': bool(unit),
            'zeroline': False,
        }
        if not unit:
            layout[_axis('yaxis', i)]['range'] = [0, 1]
        if any(piece.endless and piece.end >= end for piece in pieces):
            drawing.notes.append(
                _note('→ until the end', x_domains[-1][1], _mid(domain), 'left')
            )
    drawing.notes += _break_notes(labels, x_domains)
    drawing.notes.append(_note('time (h)', 0.5, 0, 'center', yshift=-60))
    layout['shapes'] = drawing.shapes
    layout['annotations'] = drawing.notes
    return {'data': drawing.data, 'layout': layout}


class _Drawing:
    """The figure's traces, shapes and notes, as the rows are drawn into its sections."""

    def __init__(self, sections: list[tuple[float, float]]):
        self.sections = sections
        self.data, self.shapes, self.notes = [], [], []

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
        color = COLORS[i % len(COLORS)]
        for k, (a, b) in enumerate(self.sections):
            for piece in pieces:
                start, end = max(piece.start, a), min(piece.end, b)
                if end <= start:
                    continue
                if piece.values is not None:
                    values, unit = _shown(piece.values)
                    self.data.append(
                        {
                            'type': 'scatter',
                            'mode': 'lines',
                            'x': (piece.times / HOUR).tolist(),
                            'y': values,
                            'xaxis': _axis('x', k),
                            'yaxis': _axis('y', i),
                            'line': {'color': color},
                            'name': piece.label,
                            'hovertemplate': f'{piece.label}<extra></extra>',
                        }
                    )
                    continue
                x, y = _axis('x', k), f'{_axis("y", i)} domain'
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
                        'text': piece.text,
                        'xref': x,
                        'yref': y,
                        'x': (start + end) / 2 / HOUR,
                        'y': 0.5,
                        'showarrow': False,
                    }
                )
        return unit


def _break_notes(labels: list[str], x_domains: list[list[float]]) -> list[dict]:
    """`//` on the axis at each cut, with what it hides written under it."""
    notes = []
    for k, label in enumerate(labels):
        if k + 1 < len(x_domains):
            x, anchor = (x_domains[k][1] + x_domains[k + 1][0]) / 2, 'center'
        else:
            x, anchor = x_domains[-1][1], 'left'  # it never ends: after the axis
        notes.append(_note('<b>//</b>', x, 0, anchor))
        notes.append(_note(label, x, 0, anchor, yshift=-38))
    return notes


def _note(text: str, x: float, y: float, anchor: str, yshift: int = 0) -> dict:
    return {
        'text': text,
        'xref': 'paper',
        'yref': 'paper',
        'x': x,
        'y': y,
        'xanchor': anchor,
        'yshift': yshift,
        'showarrow': False,
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
    return values.magnitude.tolist(), f'{values.units:~P}'


def _axis(name: str, index: int) -> str:
    """Plotly's name of the `index`-th axis: `x`, `x2`, … or `xaxis`, `xaxis2`, …"""
    return name if index == 0 else f'{name}{index + 1}'


def _mid(domain: list[float]) -> float:
    return (domain[0] + domain[1]) / 2
