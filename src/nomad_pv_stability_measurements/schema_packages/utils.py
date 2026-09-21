import re
from dataclasses import dataclass, field
from math import inf

import numpy as np
from nomad.units import ureg


def shown(quantity) -> str:
    """A quantity the way a person reads it: a temperature in °C, a fraction in %, a
    time in the largest of h, min and s that counts it whole."""
    if quantity.check('[temperature]'):
        quantity = quantity.to('degC')
    elif quantity.check('[time]'):
        seconds = quantity.to('s').magnitude
        for unit, size in (('h', 3600), ('min', 60)):
            if seconds >= size and float(seconds / size).is_integer():
                return f'{seconds / size:.4g} {unit}'
        return f'{seconds:.4g} s'
    elif quantity.dimensionless:
        quantity = quantity.to('percent')
    return f'{quantity.magnitude:.4g} {quantity.units:~P}'


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
    #: It never finishes: drawn up to where the drawing stops.
    endless: bool = False


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


def combined_duration(durations, mode: str):
    """How long instructions with these `durations` last together: one after another
    (`sequential`) or all at once (`parallel`). `None` if any of them never finishes."""
    if any(duration is None for duration in durations):
        return None
    seconds = [duration.to('s').magnitude for duration in durations]
    if not seconds:
        return 0 * ureg.second
    return (max(seconds) if mode == 'parallel' else sum(seconds)) * ureg.second


def seconds_or_inf(duration) -> float:
    """A duration in seconds; `inf` for one that never ends."""
    return inf if duration is None else duration.to('s').magnitude


def instructions_for_plotting(instructions, mode: str, start: float, stop: float):
    """`instructions` drawn one after another (`sequential`) or all from `start`."""
    series = TimePlotSeries()
    time = start
    for each in instructions:
        series.extend(each.time_series_for_plotting(time, stop))
        if mode == 'sequential':
            time += seconds_or_inf(each.duration)
    return series


def drawing_end(series: TimePlotSeries) -> float:
    """Where a drawing of `series` ends: after the last thing that starts, finishes or
    breaks off; at least an hour, so a plan of settings alone still shows."""
    times = [piece.start for piece in series.pieces]
    times += [piece.end for piece in series.pieces if piece.end < inf]
    times += [cut.start for cut in series.breaks]
    times += [cut.end for cut in series.breaks if cut.end < inf]
    return max(times, default=0) or 3600.0
