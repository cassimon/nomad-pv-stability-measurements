"""The figures of a stability run, as Plotly JSON: a J–V sweep as its curves, and what
was recorded over time, of one series or of the whole run.

Values are shown in the units solar-cell data is read in: current density in mA/cm²,
power density in mW/cm², temperature in °C, humidity in %, time in hours. What was
recorded takes the colour of its role, as in a protocol's timeline: controlled, or only
monitored.
"""

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
    pieces: list[tuple[str, list[float], dict, list[str]]],
    title: str,
    marks: list[tuple[float, str]] = (),
    scans: dict[str, dict[str, tuple[list[float], object]]] | None = None,
) -> dict:
    """Quantities over time, one row each, all on one time axis in hours.

    `pieces` are `(name, hours, recorded, controlled)`, one per stretch recorded
    together; each is drawn apart, so that nothing is drawn across the time between
    two, a quantity in `controlled` in the colour of the controlled, any other in that
    of the monitored. `marks` are
    `(hours, text)`: moments marked by a dashed line through every row. `scans` are
    what J–V scans reported, by row and then by direction, `(hours, values)`: in the
    row `efficiency`, above the others, as dots joined by lines, one line per
    direction; in a row of `ROWS`, as dots beside what the series recorded there."""
    scans = scans or {}
    rows = [
        name
        for name in ROWS
        if name in scans or any(name in each[2] for each in pieces)
    ]
    roles = set()
    if 'efficiency' in scans:
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
                    'x': hours,
                    'y': efficiency.to(unit).magnitude.tolist(),
                    'line': {'color': DIRECTION_COLORS[direction]},
                    'marker': {'size': 8, 'color': DIRECTION_COLORS[direction]},
                    **axes,
                }
                for direction, (hours, efficiency) in scans['efficiency'].items()
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
                        'x': hours,
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
                    'x': hours,
                    'y': values.to(unit).magnitude.tolist(),
                    'marker': {'size': 8, 'color': DIRECTION_COLORS[direction]},
                    **axes,
                }
                for direction, (hours, values) in scans.get(row, {}).items()
            ]
        top = 1 - index * (height + ROW_GAP)
        last = index == len(rows) - 1
        layout[f'xaxis{suffix}'] = {
            **_axis('time (h)' if last else ''),
            'anchor': f'y{suffix}',
            'showticklabels': last,
            **({'matches': 'x'} if index else {}),
        }
        layout[f'yaxis{suffix}'] = {
            **_axis(f'{label}<br>({written})'),
            'anchor': f'x{suffix}',
            'domain': [top - height, top],
        }
    layout['shapes'] = [
        {
            'type': 'line',
            'xref': 'x',
            'yref': 'paper',
            'x0': at,
            'x1': at,
            'y0': 0,
            'y1': 1,
            'line': {'color': AXIS_COLOR, 'width': 1, 'dash': 'dash'},
        }
        for at, _ in marks
    ]
    keys = {role: ROLE_COLORS[role] for role in ROLE_COLORS if role in roles}
    keys.update(
        {
            direction: DIRECTION_COLORS[direction]
            for by_direction in scans.values()
            for direction in by_direction
        }
    )
    layout['annotations'] = [_legend(keys)] + [
        {
            'text': text,
            'xref': 'x',
            'yref': 'paper',
            'x': at,
            'y': 1,
            'yanchor': 'bottom',
            'showarrow': False,
            'font': {'size': FONT_SIZE - 3, 'color': AXIS_COLOR},
        }
        for at, text in marks
    ]
    return {'data': traces, 'layout': layout}


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
