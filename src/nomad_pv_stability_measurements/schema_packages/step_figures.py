"""The figures of a stability run, as Plotly JSON: a J–V sweep as its curves, and what
was recorded over time, of one series or of the whole run.

Values are shown in the units solar-cell data is read in: current density in mA/cm²,
power density in mW/cm², temperature in °C, humidity in %; time in hours, or, where the
start is known, as dates and times, with the hours since the start on hover. What was
recorded takes the colour of its role, as in a protocol's timeline: controlled, or only
monitored. A run too short to be seen in a long history is drawn as a `RunSummary`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from nomad_pv_stability_measurements.schema_packages.plan_timeline import (
    AXIS_COLOR,
    FONT_SIZE,
    GRID_COLOR,
    ROLE_COLORS,
    ROW_BACKGROUND,
)

#: One colour per sweep direction, of middle lightness, for a light and a dark page;
#: apart from the colours of the roles, so that neither reads as one.
DIRECTION_COLORS = {'reverse': '#e0822b', 'forward': '#c2549d'}
#: What a series records, as rows top to bottom: the electrical output first, the
#: power leading as what a stability test follows, then the conditions. Each with its
#: label, the unit it is shown in, and that unit as written.
ROWS = {
    'power_density': ('power density', 'mW/cm^2', 'mW/cm²'),
    'current_density': ('current density', 'mA/cm^2', 'mA/cm²'),
    'voltage': ('voltage', 'V', 'V'),
    'irradiance': ('irradiance', 'W/m^2', 'W/m²'),
    'temperature': ('temperature', 'degC', '°C'),
    'relative_humidity': ('relative humidity', 'percent', '%'),
}
ELECTRICAL_ROWS = ('power_density', 'current_density', 'voltage')
#: The row of the J–V scans' efficiencies, above every other.
EFFICIENCY_ROW = ('PCE', 'percent', '%')

#: px: the height of one row over time, and of everything around the rows.
ROW_HEIGHT = 160
FRAME_HEIGHT = 150
#: Of the figure's height: the gap between two rows.
ROW_GAP = 0.06
JV_HEIGHT = 500
#: Of the axis's width, about, that one character of a run's label takes: a guess for
#: an axis about 1000 px wide, which tells labels that would overlap.
LABEL_CHARACTER_SHARE = 0.007
#: px: how far each further line of labels stands above the one below it.
LABEL_LINE_HEIGHT = 16
#: How many lines of labels there are at most, before labels overlap after all.
LABEL_LINES = 3


@dataclass
class RunSummary:
    """A run drawn as one point per row, where it is too short to be seen, or several
    runs too close together to be told apart: in hours since the start, from `begin`
    to `end`, with its `label` and the `names` of its runs. `values` are what its
    series recorded, by `(row, role)`; `scans` what its J–V scans reported, by row
    and then by direction. Each is `(mean, least, greatest, count)`, the first three
    quantities."""

    begin: float
    end: float
    label: str
    values: dict
    scans: dict
    names: list[str] = field(default_factory=list)

    @property
    def at(self) -> float:
        """Where the run's point stands: its middle."""
        return (self.begin + self.end) / 2


@dataclass
class OverTime:
    """What a figure over time draws, every time in hours since its start.

    `pieces` are `(name, hours, recorded, controlled)`, one per stretch recorded
    together; each is drawn apart, so that nothing is drawn across the time between
    two, a quantity in `controlled` in the colour of the controlled, any other in that
    of the monitored. `marks` are `(hours, text)`: moments marked by a dashed line
    through every row. `scans` are what J–V scans reported, by row and then by
    direction, `(hours, values)`: in the row `efficiency`, above the others, as dots
    joined by lines, one line per direction; in a row of `ROWS`, as dots beside what
    the series recorded there. `summaries` are runs drawn as one point per row each,
    with a bar from the least to the greatest value, a dashed line through every row,
    and their label above."""

    pieces: list[tuple[str, list[float], dict, list[str]]] = field(default_factory=list)
    marks: list[tuple[float, str]] = field(default_factory=list)
    scans: dict[str, dict[str, tuple[list[float], object]]] = field(
        default_factory=dict
    )
    summaries: list[RunSummary] = field(default_factory=list)


def jv_figure_for_plotting(voltage, current_density, direction, title: str) -> dict:
    """The J–V curves of one sweep, one per direction, in the order they were swept.
    A sweep that names no direction is drawn as one curve."""
    volts = voltage.to('V').magnitude
    milliamps = current_density.to('mA/cm^2').magnitude
    directions = list(direction) if direction is not None else [None] * len(volts)
    traces = []
    for each in dict.fromkeys(directions):
        chosen = np.array([name == each for name in directions])
        trace = {
            'type': 'scatter',
            'mode': 'lines+markers',
            'x': volts[chosen].tolist(),
            'y': milliamps[chosen].tolist(),
            'marker': {'size': 4},
        }
        if each is not None:
            trace.update(
                name=each,
                line={'color': DIRECTION_COLORS[each]},
                marker={'size': 4, 'color': DIRECTION_COLORS[each]},
            )
        traces.append(trace)
    return {
        'data': traces,
        'layout': {
            **_frame(title),
            'height': JV_HEIGHT,
            'showlegend': any(each is not None for each in directions),
            'xaxis': _axis('voltage (V)'),
            'yaxis': _axis('current density (mA/cm²)'),
        },
    }


def over_time_figure_for_plotting(
    drawn: OverTime, title: str, start: datetime | None = None
) -> dict:
    """What is `drawn` over time, one row per quantity, all on one time axis: in
    hours, or, given the `start` the hours count from, as dates and times.

    On dates, every time is shown in the time zone `start` is given in, at its offset
    there, so that the axis never jumps where the clocks change; the axis names the
    offset. Hovering a point also gives the hours since `start`."""
    pieces, marks, scans = drawn.pieces, drawn.marks, drawn.scans
    summaries = drawn.summaries
    on = _TimeAxis(start)
    summarized = {row for each in summaries for row, _ in each.values}
    summarized |= {row for each in summaries for row in each.scans}
    rows = [
        name
        for name in ROWS
        if name in scans
        or name in summarized
        or any(name in each[2] for each in pieces)
    ]
    roles = set()
    if 'efficiency' in scans or 'efficiency' in summarized:
        rows.insert(0, 'efficiency')
    height = (1 - ROW_GAP * (len(rows) - 1)) / len(rows)
    traces = []
    layout = {
        **_frame(title),
        'height': ROW_HEIGHT * len(rows) + FRAME_HEIGHT,
        'showlegend': False,
    }
    for index, row in enumerate(rows):
        suffix = '' if index == 0 else str(index + 1)
        axes = {'xaxis': f'x{suffix}', 'yaxis': f'y{suffix}'}
        if row == 'efficiency':
            label, unit, written = EFFICIENCY_ROW
            traces += [
                {
                    'type': 'scatter',
                    'mode': 'lines+markers',
                    'name': direction,
                    **on.x(hours),
                    'y': efficiency.to(unit).magnitude.tolist(),
                    'line': {'color': DIRECTION_COLORS[direction]},
                    'marker': {'size': 8, 'color': DIRECTION_COLORS[direction]},
                    **axes,
                }
                for direction, (hours, efficiency) in scans.get(
                    'efficiency', {}
                ).items()
            ]
        else:
            label, unit, written = ROWS[row]
            for name, hours, recorded, controlled in pieces:
                if row not in recorded:
                    continue
                role = 'controlled' if row in controlled else 'monitored'
                roles.add(role)
                traces.append(
                    {
                        'type': 'scatter',
                        'mode': 'lines',
                        'name': ' · '.join(filter(None, (name, label, role))),
                        **on.x(hours),
                        'y': recorded[row].to(unit).magnitude.tolist(),
                        'line': {'color': ROLE_COLORS[role]},
                        **axes,
                    }
                )
            traces += [
                {
                    'type': 'scatter',
                    'mode': 'markers',
                    'name': f'{direction} scan · {label}',
                    **on.x(hours),
                    'y': values.to(unit).magnitude.tolist(),
                    'marker': {'size': 8, 'color': DIRECTION_COLORS[direction]},
                    **axes,
                }
                for direction, (hours, values) in scans.get(row, {}).items()
            ]
        for summary in summaries:
            points = [
                (f'{label} · {role}', ROLE_COLORS[role], statistics)
                for (each, role), statistics in summary.values.items()
                if each == row
            ]
            roles |= {role for each, role in summary.values if each == row}
            points += [
                (f'{direction} scan · {label}', DIRECTION_COLORS[direction], statistics)
                for direction, statistics in summary.scans.get(row, {}).items()
            ]
            traces += [
                _summary_trace(summary, point, (unit, written), on, axes)
                for point in points
            ]
        top = 1 - index * (height + ROW_GAP)
        last = index == len(rows) - 1
        layout[f'xaxis{suffix}'] = {
            **_axis(on.title if last else ''),
            **on.axis,
            'anchor': f'y{suffix}',
            'showticklabels': last,
            **({'matches': 'x'} if index else {}),
        }
        layout[f'yaxis{suffix}'] = {
            **_axis(f'{label}<br>({written})'),
            'anchor': f'x{suffix}',
            'domain': [max(top - height, 0.0), top],
        }
    layout['shapes'] = [
        {
            'type': 'line',
            'xref': 'x',
            'yref': 'paper',
            'x0': on.at(at),
            'x1': on.at(at),
            'y0': 0,
            'y1': 1,
            'line': {'color': AXIS_COLOR, 'width': 1, 'dash': 'dash'},
        }
        for at in [at for at, _ in marks] + [each.at for each in summaries]
    ]
    keys = {role: ROLE_COLORS[role] for role in ROLE_COLORS if role in roles}
    keys.update(
        {
            direction: DIRECTION_COLORS[direction]
            for by_direction in [
                *scans.values(),
                *(each for summary in summaries for each in summary.scans.values()),
            ]
            for direction in by_direction
        }
    )
    layout['annotations'] = [_legend(keys)] + [
        {
            'text': text,
            'xref': 'x',
            'yref': 'paper',
            'x': on.at(at),
            'y': 1,
            'yanchor': 'bottom',
            'showarrow': False,
            'font': {'size': FONT_SIZE - 3, 'color': AXIS_COLOR},
        }
        for at, text in marks
    ]
    labels, lines = _run_labels(summaries, pieces, marks, on)
    layout['annotations'] += labels
    raised = (lines - 1) * LABEL_LINE_HEIGHT
    layout['margin']['t'] += raised
    layout['annotations'][0]['yshift'] += raised
    return {'data': traces, 'layout': layout}


def _summary_trace(summary, point, units, on, axes) -> dict:
    """One `point` of `summary`, `(name, colour, statistics)`: the mean, with a bar
    from the least to the greatest, and on hover the run, its times and the values it
    stands for."""
    name, color, statistics = point
    unit, written = units
    mean, least, greatest = (each.to(unit).magnitude for each in statistics[:3])
    count = statistics[3]
    runs = ''.join(f'<br>  {each}' for each in summary.names if len(summary.names) > 1)
    hover = (
        f'{summary.label}{runs}'
        f'<br>{on.written(summary.begin)} to {on.written(summary.end)}'
        f'<br>{name}: mean {mean:.4g} {written}, from {least:.4g} to {greatest:.4g}, '
        f'of {count} value{"s" if count > 1 else ""}'
    )
    return {
        'type': 'scatter',
        'mode': 'markers',
        'name': f'{summary.label} · {name}',
        'x': [on.at(summary.at)],
        'y': [mean],
        'error_y': {
            'type': 'data',
            'symmetric': False,
            'array': [greatest - mean],
            'arrayminus': [mean - least],
            'color': color,
            'thickness': 1.5,
            'width': 5,
        },
        'marker': {'size': 9, 'color': color},
        'hovertext': [hover],
        'hovertemplate': '%{hovertext}<extra></extra>',
        **axes,
    }


def _run_labels(summaries, pieces, marks, on) -> tuple[list[dict], int]:
    """The label of each summarized run above the rows, and how many lines of labels
    there are: a label that would overlap the one before it on a line goes a line
    higher, up to `LABEL_LINES`."""
    times = [each.at for each in summaries] + [at for at, _ in marks]
    times += [time for piece in pieces for time in (piece[1][0], piece[1][-1])]
    extent = (max(times) - min(times)) if times else 0
    ends = []  # where the last label on each line ends, in hours
    labels = []
    for summary in sorted(summaries, key=lambda each: each.at):
        half = len(summary.label) * LABEL_CHARACTER_SHARE * extent / 2
        free = [line for line, end in enumerate(ends) if end < summary.at - half]
        if free:
            line = free[0]
        elif len(ends) < LABEL_LINES:
            line = len(ends)
            ends.append(0)
        else:
            line = min(range(len(ends)), key=lambda each: ends[each])
        ends[line] = summary.at + half
        labels.append(
            {
                'text': summary.label,
                'xref': 'x',
                'yref': 'paper',
                'x': on.at(summary.at),
                'y': 1,
                'yanchor': 'bottom',
                'yshift': 4 + line * LABEL_LINE_HEIGHT,
                'showarrow': False,
                'font': {'size': FONT_SIZE - 3, 'color': AXIS_COLOR},
            }
        )
    return labels, max(len(ends), 1)


class _TimeAxis:
    """How times in hours since `start` are placed on the time axis: as they are
    where `start` is `None`, else as dates and times."""

    def __init__(self, start: datetime | None):
        self.start, self.zone = None, ''
        self.title, self.axis = 'time (h)', {}
        if start is None:
            return
        offset = start.utcoffset()
        if offset is None:
            self.start, self.zone = start, ''
        else:
            self.start = start.astimezone(timezone(offset)).replace(tzinfo=None)
            self.zone = f' (UTC{_offset(offset)})'
        self.title, self.axis = f'date and time{self.zone}', {'type': 'date'}

    def written(self, hours: float) -> str:
        """One moment as a reader is told it: a date and time, with its offset, or
        hours since the start."""
        if self.start is None:
            return f'{hours:.4g} h'
        moment = self.start + timedelta(hours=hours)
        return f'{moment:%Y-%m-%d %H:%M:%S}{self.zone}'

    def at(self, hours: float):
        """One moment on the axis."""
        if self.start is None:
            return hours
        return (self.start + timedelta(hours=hours)).isoformat(timespec='milliseconds')

    def x(self, hours: list[float]) -> dict:
        """The `x` of a trace, and, on dates, the hours since the start on hover."""
        if self.start is None:
            return {'x': hours}
        milliseconds = np.rint(np.asarray(hours, dtype=float) * 3.6e6)
        moments = np.datetime64(self.start, 'ms') + milliseconds.astype(
            'timedelta64[ms]'
        )
        return {
            'x': np.datetime_as_string(moments, unit='ms').tolist(),
            'customdata': np.round(np.asarray(hours, dtype=float), 4).tolist(),
            'hovertemplate': '%{x|%Y-%m-%d %H:%M:%S}, %{customdata:.2f} h since the '
            'start<br>%{y}<extra>%{fullData.name}</extra>',
        }


def _offset(offset: timedelta) -> str:
    """An offset from UTC as written after `UTC`: `+01:00`, `-05:30`, or nothing."""
    minutes = round(offset.total_seconds() / 60)
    if minutes == 0:
        return ''
    sign = '+' if minutes > 0 else '-'
    return f'{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}'


def _legend(keys: dict[str, str]) -> dict:
    """What the colours mean, above the rows on the right, as in a protocol's
    timeline: a square for a role, a dot for a scan direction."""
    marks = {**dict.fromkeys(ROLE_COLORS, '■'), **dict.fromkeys(DIRECTION_COLORS, '●')}
    return {
        'text': '   '.join(
            f'<span style="color:{color}">{marks[key]}</span> {key}'
            for key, color in keys.items()
        ),
        'xref': 'paper',
        'yref': 'paper',
        'x': 1,
        'y': 1,
        'xanchor': 'right',
        'yanchor': 'bottom',
        'yshift': 22,
        'showarrow': False,
    }


def _frame(title: str) -> dict:
    """What every figure of a step shares: its title, its font, and a background the
    page shows through, light or dark."""
    return {
        'title': {
            'text': f'<b>{title}</b>' if title else '',
            'font': {'size': FONT_SIZE + 2},
        },
        'font': {'size': FONT_SIZE},
        'margin': {'l': 90, 'r': 30, 't': 70, 'b': 70},
        'paper_bgcolor': 'rgba(0, 0, 0, 0)',
        'plot_bgcolor': ROW_BACKGROUND,
    }


def _axis(title: str) -> dict:
    """An axis with its title, a grid and a line at zero."""
    return {
        'title': {'text': title},
        'gridcolor': GRID_COLOR,
        'zeroline': True,
        'zerolinecolor': AXIS_COLOR,
        'linecolor': AXIS_COLOR,
    }
