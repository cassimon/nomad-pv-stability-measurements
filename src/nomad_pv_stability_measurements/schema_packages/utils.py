import re
from dataclasses import dataclass, field
from math import inf

import numpy as np

#: A repeating block draws this many iterations at most; the rest is an axis break.
#: Something that repeats by itself, and nothing stops, is drawn this many cycles.
ITERATIONS_FOR_PLOTTING = 3


def shown(quantity, exact: bool = True) -> str:
    """A quantity the way a person reads it: a temperature in °C, a fraction in %, a
    time in the largest of h, min and s that counts it whole in a few digits, else in
    the largest it reaches, rounded. A time that is not `exact` is only ever rounded:
    `12.02 h`, not `721 min`."""
    if quantity.check('[temperature]'):
        quantity = quantity.to('degC')
    elif quantity.check('[time]'):
        seconds = quantity.to('s').magnitude
        units = (('h', 3600), ('min', 60), ('s', 1))
        for unit, size in units:
            count = seconds / size
            if exact and 1 <= count < 10**4 and float(count).is_integer():
                return f'{count:.4g} {unit}'
        unit, size = next((each for each in units if seconds >= each[1]), units[-1])
        return f'{seconds / size:.4g} {unit}'
    elif quantity.dimensionless:
        quantity = quantity.to('percent')
    # pint writes an hour `hr`; the SI symbol is `h`.
    unit = re.sub(r'\bhr\b', 'h', f'{quantity.units:~P}')
    return f'{quantity.magnitude:.4g} {unit}'


def words(class_name: str) -> str:
    """`HoldRelativeHumidity` as `Hold relative humidity`; acronyms stay: `MPP tracking`."""
    parts = re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+', class_name)
    text = ' '.join(part if part.isupper() else part.lower() for part in parts)
    return text[:1].upper() + text[1:]


@dataclass
class PlotPiece:
    """One instruction drawn on its row, from `start` to `end`, in seconds since the
    plan starts: a line through `times` and `values`, or else `text`."""

    row: str
    label: str
    start: float
    end: float
    times: np.ndarray | None = None
    values: object = None
    text: str | None = None
    #: `(lower, upper)` of a band the value is kept in, in the quantity's unit.
    bounds: tuple | None = None
    #: `controlled`, `monitored` or `unspecified`: what colour it is drawn in.
    role: str = 'unspecified'
    #: It never finishes: drawn up to where the drawing stops.
    endless: bool = False
    #: s: one cycle of what it repeats by itself, as a ramp up and down: a drawing
    #: that nothing else stops shows a few.
    cycle: float | None = None
    #: What the drawing assumes and the protocol does not state, written in red.
    assumption: str | None = None
    #: What it typically lasts, where the protocol fixes no length, written in red.
    typical: str | None = None


@dataclass
class AxisBreak:
    """Where the time axis is cut, from `start` to `end` (`inf`: it never ends), and
    what happens there, written under the cut: `n=300 repetitions`."""

    start: float
    end: float
    label: str


@dataclass
class TimePlotSeries:
    """What a plan, or part of it, draws: plain data, no Plotly."""

    pieces: list[PlotPiece] = field(default_factory=list)
    breaks: list[AxisBreak] = field(default_factory=list)
    #: Where the drawing ends, in seconds; set by whoever draws it as a whole.
    end: float | None = None

    def extend(self, other: 'TimePlotSeries') -> None:
        self.pieces += other.pieces
        self.breaks += other.breaks


def instructions_for_plotting(instructions, mode: str, start: float, stop: float):
    """`instructions` drawn one after another (`sequential`) or all from `start`."""
    series = TimePlotSeries()
    time = start
    for each in instructions:
        series.extend(each.time_series_for_plotting(time, stop))
        if mode == 'sequential':
            time += each.seconds()
    return series


def drawing_end(series: TimePlotSeries) -> float:
    """Where a drawing of `series` ends: after the last thing that starts, finishes or
    breaks off, or has drawn a few of its own cycles; at least an hour, so a plan of
    settings alone still shows."""
    times = [piece.start for piece in series.pieces]
    times += [piece.end for piece in series.pieces if piece.end < inf]
    times += [cut.start for cut in series.breaks]
    times += [cut.end for cut in series.breaks if cut.end < inf]
    times += [
        piece.start + ITERATIONS_FOR_PLOTTING * piece.cycle
        for piece in series.pieces
        if piece.cycle
    ]
    return max(times, default=0) or 3600.0
