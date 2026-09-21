"""A stability protocol run as a measurement: one flat list of steps, each with the time
series of every quantity the protocol controls or monitors — like a vapor deposition in
nomad-material-processing, whose steps carry their temperatures and pressures.

The plan says *what* runs *when*; the measurement it creates is the skeleton a data
source fills: an instrument's log, or `parsers/simulation_parser.py`.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from itertools import pairwise
from math import inf

import numpy as np
from nomad.datamodel.data import ArchiveSection
from nomad.datamodel.metainfo.basesections.v2 import ActivityStep
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Quantity, SchemaPackage, Section, SubSection
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    CountingRepeatingBlock,
    Instruction,
    RepeatingBlock,
    TimedRepeatingBlock,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.protocol import (
    StabilityActivity,
    StabilityProtocol,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    MonitorControlInstruction,
)

m_package = SchemaPackage()

#: More steps than this is a plan cycling far faster than it runs long: refused, not
#: written out.
MAX_STEPS = 10_000

#: A measurement with more steps than this gets no figure per step, only its overview:
#: a thousand small figures cost more to make and store than they show.
MAX_STEPS_WITH_FIGURES = 100


class TimeSeries(ArchiveSection):
    """One quantity over one step: what was measured and what it was set to.

    `time` counts from the start of the measurement, not of the step, so the series of
    all steps join into one. Each subclass is one quantity, in its own unit.
    """

    m_def = Section(a_plot=dict(x='time', y=['value', 'set_value']))

    instruction = Quantity(
        type=Instruction,
        description='The instruction in force for this quantity during the step.',
    )
    instruction_start = Quantity(
        type=np.float64,
        unit='s',
        description='When that instruction started, from the start of the measurement; '
        'it may be before this step, for a setting that holds throughout. A ramp is '
        'measured from here.',
    )
    controlled = Quantity(
        type=bool,
        description='Whether the quantity was regulated: then `set_value` is filled.',
    )
    monitored = Quantity(
        type=bool,
        description='Whether the quantity was logged: then `value` is filled.',
    )
    sample_every = Quantity(
        type=np.float64,
        unit='s',
        description='How often it was to be logged, from the innermost instruction '
        'that says (Design.md D4b).',
    )
    time = Quantity(
        type=np.float64,
        shape=['*'],
        unit='s',
        description='When each value was taken, from the start of the measurement.',
    )
    value = Quantity(type=np.float64, shape=['*'], description='What was measured.')
    set_value = Quantity(
        type=np.float64, shape=['*'], description='What the controller was set to.'
    )


def _values(unit: str):
    """`value` and `set_value` of one quantity, in `unit`."""
    return (
        Quantity(
            type=np.float64,
            shape=['*'],
            unit=unit,
            description='What was measured, at each `time`.',
        ),
        Quantity(
            type=np.float64,
            shape=['*'],
            unit=unit,
            description='What the controller was set to, at each `time`.',
        ),
    )


class TemperatureSeries(TimeSeries):
    """The sample's temperature."""

    value, set_value = _values('K')


class IrradianceSeries(TimeSeries):
    """The light on the sample."""

    value, set_value = _values('W/m^2')


class VoltageSeries(TimeSeries):
    """The voltage at the cell's terminals; at open circuit, the cell's V_oc."""

    value, set_value = _values('V')


class CurrentSeries(TimeSeries):
    """The current through the cell."""

    value, set_value = _values('A')


class ResistanceSeries(TimeSeries):
    """The load across the cell's terminals."""

    value, set_value = _values('ohm')


class PowerSeries(TimeSeries):
    """The power the cell delivers at its maximum power point, as the tracker finds it."""

    value, set_value = _values('W')


class RelativeHumiditySeries(TimeSeries):
    """The relative humidity around the sample, as a fraction."""

    value, set_value = _values('dimensionless')


class AbsoluteHumiditySeries(TimeSeries):
    """The water in the atmosphere around the sample, as a volume ratio."""

    value, set_value = _values('dimensionless')


class OxygenFractionSeries(TimeSeries):
    """The oxygen in the atmosphere around the sample, as a volume ratio."""

    value, set_value = _values('dimensionless')


class PressureSeries(TimeSeries):
    """The total pressure of the atmosphere around the sample."""

    value, set_value = _values('Pa')


class BendRadiusSeries(TimeSeries):
    """How far the device is bent."""

    value, set_value = _values('m')


class StrainSeries(TimeSeries):
    """How far the device is stretched, as a fraction."""

    value, set_value = _values('dimensionless')


#: Each quantity a step can carry, as its sub-section's name, with its series.
SERIES = {
    'temperature': TemperatureSeries,
    'irradiance': IrradianceSeries,
    'voltage': VoltageSeries,
    'current': CurrentSeries,
    'resistance': ResistanceSeries,
    'power': PowerSeries,
    'relative_humidity': RelativeHumiditySeries,
    'absolute_humidity': AbsoluteHumiditySeries,
    'oxygen_fraction': OxygenFractionSeries,
    'pressure': PressureSeries,
    'bend_radius': BendRadiusSeries,
    'strain': StrainSeries,
}


def measured_quantity(instruction) -> str | None:
    """Which series an instruction's quantity goes to: `HoldTemperature` and
    `RampTemperature` to `temperature`; the MPP tracker to `power`, open circuit to
    `voltage`. `None` for an instruction that names no quantity."""
    if isinstance(instruction, MPPTracking):
        return 'power'
    if isinstance(instruction, VOCTracking):
        return 'voltage'
    if not isinstance(instruction, MonitorControlInstruction) or not instruction.kind:
        return None
    name = type(instruction).__name__.removeprefix(instruction.kind)
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


def time_series_figure(title: str, series_by_quantity: dict, steps=()) -> dict:
    """One row per quantity, shared time axis in hours: what was measured as a line,
    what it was set to dashed. The series of one quantity are joined across
    steps. With `steps`, a last row shows which step runs when, by its index.

    Plotly's JSON written directly: a measurement has a figure per step, and building
    each through plotly's objects takes longer than the rest of normalizing.
    """
    rows = [
        _quantity_row(quantity, series)
        for quantity, series in series_by_quantity.items()
    ]
    if steps:
        rows.append(_step_row(steps))
    gap = 0.04
    height = (1 - gap * (len(rows) - 1)) / len(rows)
    data = []
    layout = {
        'title': {'text': title},
        'height': max(300, 220 * len(rows)),
        'xaxis': {'title': {'text': 'time [h]'}, 'anchor': f'y{len(rows)}'},
    }
    for row, (traces, axis_layout) in enumerate(rows, start=1):
        axis = '' if row == 1 else str(row)
        data += [{**trace, 'xaxis': 'x', 'yaxis': f'y{axis}'} for trace in traces]
        top = 1 - (row - 1) * (height + gap)
        layout[f'yaxis{axis}'] = {
            **axis_layout,
            'domain': [max(0.0, top - height), top],
            'anchor': 'x',
        }
    return {'data': data, 'layout': layout}


def _quantity_row(quantity: str, series: list) -> tuple[list, dict]:
    """The traces of one quantity, and its axis."""
    traces, unit = [], None
    for field, dash in (('value', 'solid'), ('set_value', 'dash')):
        x, y, until = [], [], None
        for each in series:
            values = getattr(each, field)
            if values is None or each.time is None:
                continue
            values, unit = _shown(values)
            step = each.m_parent
            start = step.elapsed_at_start.to('hour').magnitude
            if until is not None and start > until + 1e-9:
                x, y = [*x, None], [*y, None]  # no data in between: a gap
            until = start + step.duration.to('hour').magnitude
            x += list(each.time.to('hour').magnitude)
            y += values
        if x:
            traces.append(
                {
                    'type': 'scatter',
                    'mode': 'lines',
                    'x': x,
                    'y': y,
                    # A set value holds until the next: a staircase.
                    'line': {
                        'dash': dash,
                        'width': 1.5,
                        'shape': 'hv' if field == 'set_value' else 'linear',
                    },
                    'name': f'{quantity.replace("_", " ")} ({field.replace("_", " ")})',
                }
            )
    label = quantity.replace('_', ' ')
    return traces, {'title': {'text': f'{label} [{unit}]' if unit else label}}


def _step_row(steps) -> tuple[list, dict]:
    """Which step runs when: its index in `steps`, from its start to its end, and its
    name on hover."""
    x, y, names = [], [], []
    for index, step in enumerate(steps):
        x.append(step.elapsed_at_start.to('hour').magnitude)
        y.append(index)
        names.append(step.name)
    last = steps[-1]
    x.append((last.elapsed_at_start + last.duration).to('hour').magnitude)
    y.append(len(steps) - 1)
    names.append(last.name)
    trace = {
        'type': 'scatter',
        'mode': 'lines',
        'x': x,
        'y': y,
        'line': {'shape': 'hv', 'width': 1.5, 'color': 'grey'},
        'text': names,
        'hovertemplate': 'step %{y}: %{text}<extra></extra>',
        'name': 'step',
    }
    return [trace], {'title': {'text': 'step'}, 'rangemode': 'tozero'}


def _shown(values) -> tuple[list, str]:
    """Values as a person reads them: a temperature in °C, a fraction in %."""
    if values.check('[temperature]'):
        values = values.to('degC')
    elif values.dimensionless:
        values = values.to('percent')
    return list(values.magnitude), f'{values.units:~P}'


class StabilityMeasurementStep(PlotSection, ActivityStep):
    """A span of the measurement in which nothing the plan says changes: the same
    instructions are in force from its start to its end.

    One sub-section per quantity controlled or monitored during it.
    """

    elapsed_at_start = Quantity(
        type=np.float64,
        unit='s',
        description='How long the measurement had run when this step started.',
    )
    duration = Quantity(type=np.float64, unit='s', description='How long it lasted.')
    instructions = Quantity(
        type=str,
        shape=['*'],
        description='The instructions in force during this step, by label: the '
        'innermost one for each quantity, which shadows the settings (Design.md D4b).',
    )

    temperature = SubSection(section_def=TemperatureSeries)
    irradiance = SubSection(section_def=IrradianceSeries)
    voltage = SubSection(section_def=VoltageSeries)
    current = SubSection(section_def=CurrentSeries)
    resistance = SubSection(section_def=ResistanceSeries)
    power = SubSection(section_def=PowerSeries)
    relative_humidity = SubSection(section_def=RelativeHumiditySeries)
    absolute_humidity = SubSection(section_def=AbsoluteHumiditySeries)
    oxygen_fraction = SubSection(section_def=OxygenFractionSeries)
    pressure = SubSection(section_def=PressureSeries)
    bend_radius = SubSection(section_def=BendRadiusSeries)
    strain = SubSection(section_def=StrainSeries)

    def series(self) -> dict[str, TimeSeries]:
        """The quantities this step carries, by name."""
        return {
            quantity: getattr(self, quantity)
            for quantity in SERIES
            if getattr(self, quantity) is not None
        }

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if len(getattr(self.m_parent, 'steps', ())) > MAX_STEPS_WITH_FIGURES:
            self.figures = []
            return
        # A quantity without data, planned but not recorded, is left out of the plot.
        series = {
            name: [each]
            for name, each in self.series().items()
            if each.time is not None
        }
        if series:
            self.figures = [
                PlotlyFigure(
                    label='Time series',
                    index=0,
                    figure=time_series_figure(self.name, series),
                )
            ]


@dataclass
class Run:
    """One instruction without sub-instructions, running from `start` to `end`, in
    seconds from the start of the measurement."""

    instruction: Instruction
    start: float
    end: float
    depth: int
    order: int = 0

    def in_force(self, at: float) -> bool:
        return self.start <= at < self.end


class StabilityProtocolMeasurementPlan(StabilityProtocol):
    """A stability protocol that is run as a `StabilityMeasurement`: its instructions
    laid out on the measurement's time line, as one flat list of steps.
    """

    def create_activity(self, **fields) -> 'StabilityMeasurement':
        """The measurement running this plan, from what the caller says happened.

        The plan is normalized first, so the durations it derives are known. Where the
        caller says nothing, the plan fills in as `StabilityProtocol` does — `method`
        and `location` — and lays out the steps: from `datetime` until `datetime_end`,
        or until the plan's own `duration` if it is shorter. A plan that never ends
        needs the caller's `datetime_end`.

        A copy of the plan is kept in the measurement, as it was run: `protocol` points
        to it, and so does each series, to the instruction it follows.
        """
        activity = StabilityMeasurement(**fields)
        activity.method = activity.method or self.standard
        activity.location = activity.location or self.location
        activity.plan = self.m_copy(deep=True)
        activity.protocol = activity.plan
        if not activity.steps:
            activity.steps = activity.plan.steps_from(
                activity.datetime, self.run_length(activity)
            )
        return activity

    def run_length(self, activity) -> float:
        """How long the measurement runs, in seconds: until the caller's
        `datetime_end`, or the plan's `duration`, whichever comes first."""
        lengths = []
        if activity.datetime is not None and activity.datetime_end is not None:
            lengths.append((activity.datetime_end - activity.datetime).total_seconds())
        if self.duration is not None:
            lengths.append(self.duration.to('s').magnitude)
        if not lengths:
            raise ValueError(
                f'{self.name or "The plan"} never ends on its own: give the activity '
                f'a `datetime` and a `datetime_end`, when the measurement ran.'
            )
        return min(lengths)

    def steps_from(self, start, length: float) -> list[StabilityMeasurementStep]:
        """The flat steps of a measurement that starts at `start` and runs `length`
        seconds: a new step wherever an instruction starts or ends."""
        runs = self.runs(length)
        times = sorted({0.0, length} | {r.start for r in runs} | {r.end for r in runs})
        spans = [(a, b) for a, b in pairwise(times) if b > a and b <= length]
        if len(spans) > MAX_STEPS:
            raise ValueError(
                f'{self.name or "The plan"} would make {len(spans)} steps in '
                f'{length / 3600:g} h, more than {MAX_STEPS}.'
            )
        return [self.step(runs, a, b, start) for a, b in spans]

    def runs(self, length: float) -> list[Run]:
        """Every instruction without sub-instructions, where it runs in the first
        `length` seconds."""
        _, runs = _run_together(
            self.instructions, self.instruction_execution_mode, 0.0, length, 0
        )
        for order, run in enumerate(runs):
            run.order = order  # as written: settings first, the routine after
        return runs

    def step(self, runs: list[Run], a: float, b: float, start):
        """The step from `a` to `b`: for each quantity, the innermost instruction in
        force (then the latest started, then the last written) is the one it follows
        (D4b); whether it is logged, and how often, comes from the innermost instruction
        that says."""
        in_force = sorted(
            (r for r in runs if r.in_force(a)),
            key=lambda r: (r.depth, r.start, r.order),
        )
        followed: dict = {}
        for run in in_force:
            # An instruction that names no quantity shadows nothing.
            followed[measured_quantity(run.instruction) or run.order] = run
        followed_runs = sorted(followed.values(), key=lambda r: r.order)
        begins = [r for r in followed_runs if r.start == a] or followed_runs
        step = StabilityMeasurementStep(
            name=', '.join(_label(r.instruction) for r in begins),
            start_time=None if start is None else start + timedelta(seconds=a),
            elapsed_at_start=a * ureg.second,
            duration=(b - a) * ureg.second,
            instructions=[_label(r.instruction) for r in followed_runs],
        )
        for quantity, run in followed.items():
            if quantity not in SERIES:
                continue
            same = [r for r in in_force if measured_quantity(r.instruction) == quantity]
            monitored = _innermost(same, 'monitor') or False
            controlled = bool(run.instruction.control)
            if monitored or controlled:
                setattr(
                    step,
                    quantity,
                    SERIES[quantity](
                        instruction=run.instruction,
                        instruction_start=run.start * ureg.second,
                        controlled=controlled,
                        monitored=monitored,
                        sample_every=_innermost(same, 'sample_every'),
                    ),
                )
        return step


def _innermost(runs: list[Run], field: str):
    """`field` of the innermost of `runs` that writes it; `runs` go outermost first."""
    for run in reversed(runs):
        value = getattr(run.instruction, field)
        if value is not None:
            return value
    return None


def _label(instruction) -> str:
    return instruction.label or instruction.name or type(instruction).__name__


def _run_together(instructions, mode, start, limit, depth) -> tuple[float, list[Run]]:
    """Lays out `instructions`, run one after another or all at once from `start` and
    cut at `limit`. Returns when they end — `inf` if they never do, or not before
    `limit` — and their runs, as written."""
    runs: list[Run] = []
    if mode == 'parallel':
        ends = [start]
        for each in instructions:
            end, each_runs = _run(each, start, limit, depth)
            ends.append(end)
            runs += each_runs
        return max(ends), runs
    time = start
    for each in instructions:
        if time >= limit:
            return inf, runs
        time, each_runs = _run(each, time, limit, depth)
        runs += each_runs
    return time, runs


def _run(instruction, start, limit, depth) -> tuple[float, list[Run]]:
    """Lays out one instruction from `start`, cut at `limit`: when it ends, and its
    runs."""
    if not instruction.sub_instructions:
        end = inf if instruction.duration is None else start + _seconds(instruction)
        if start >= limit:
            return end, []
        return end, [Run(instruction, start, min(end, limit), depth)]
    own_end = inf
    if isinstance(instruction, TimedRepeatingBlock) and instruction.repeat_duration:
        own_end = start + instruction.repeat_duration.to('s').magnitude
    stop = min(limit, own_end)
    repetitions = _repetitions(instruction)
    runs: list[Run] = []
    time, done = start, 0
    while done < repetitions and time < stop:
        end, iteration_runs = _run_together(
            instruction.sub_instructions,
            instruction.sub_instruction_execution_mode,
            time,
            stop,
            depth + 1,
        )
        runs += iteration_runs
        done += 1
        if end <= time:  # takes no time: repeating it would never get anywhere
            return time, runs
        time = end
    if isinstance(instruction, TimedRepeatingBlock) and own_end < inf:
        return own_end, runs
    return (time if done >= repetitions else inf), runs


def _repetitions(block) -> float:
    if isinstance(block, CountingRepeatingBlock):
        return inf if block.repeat_n is None else block.repeat_n
    if isinstance(block, RepeatingBlock):
        return inf
    return 1


def _seconds(instruction) -> float:
    return instruction.duration.to('s').magnitude


class StabilityMeasurement(PlotSection, StabilityActivity):
    """A PV stability test as measured: the plan it ran, and one flat list of steps
    with the time series of everything controlled or monitored.
    """

    plan = SubSection(
        section_def=StabilityProtocolMeasurementPlan,
        description='The plan as it was run: a copy, so the measurement stands on its '
        'own when the plan is edited later.',
    )
    steps = SubSection(
        section_def=StabilityMeasurementStep,
        repeats=True,
        description='The spans in which the same instructions are in force, in order.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        series_by_quantity: dict = {}
        for step in self.steps:
            for quantity, each in step.series().items():
                if each.time is None:
                    continue  # planned, but not recorded
                series_by_quantity.setdefault(quantity, []).append(each)
        if series_by_quantity:
            self.figures = [
                PlotlyFigure(
                    label='Time series',
                    index=0,
                    open=True,
                    figure=time_series_figure(
                        self.name or 'Stability measurement',
                        series_by_quantity,
                        steps=self.steps,
                    ),
                )
            ]


m_package.__init_metainfo__()
