"""A simulated stability measurement, for an example upload: what a run of a plan
would have set.

A `*.simulation.yaml` names the plan and says when the run started and how long it
lasted:

    simulation:
      protocol: light-dark-cycling.stability.yaml   # beside this file
      variant: null            # the entry key of one variant, for a file with options
      name: Cell A, light–dark cycling
      start: 2026-03-02T09:00:00Z
      duration: 72 h
      sample_every: 5 min      # wherever the plan does not say how often to log

The plan lays the run out as steps (`StabilityProtocolMeasurementPlan.create_activity`);
this module only fills in what can be known without a model of the device or of its
surroundings: the set values of what is controlled. Nothing is measured, so a
quantity that is only monitored stays empty, and so does a controlled one whose value
the plan does not state — a tracker's, a point on the device's characteristic, a
bound, or a cycle by an unstated path.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import yaml
from nomad.datamodel import EntryArchive
from nomad.parsing.parser import MatchingParser
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.options import expand
from nomad_pv_stability_measurements.parsers.parser import stem
from nomad_pv_stability_measurements.parsers.translate import translate
from nomad_pv_stability_measurements.parsers.units import parse_duration
from nomad_pv_stability_measurements.schema_packages.measurement_plan import (
    StabilityMeasurement,
    StabilityMeasurementStep,
    StabilityProtocolMeasurementPlan,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldInstruction,
    RampInstruction,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

#: At most this many points per series and step: a plan may ask for 10 Hz over 500 h.
MAX_POINTS = 500

PLAN_M_DEF = (
    'nomad_pv_stability_measurements.schema_packages.measurement_plan.'
    'StabilityProtocolMeasurementPlan'
)


@dataclass
class Simulation:
    """What a `*.simulation.yaml` says."""

    protocol: Path
    variant: str | None
    name: str
    start: datetime
    duration: float
    sample_every: float

    @classmethod
    def read(cls, mainfile: str) -> 'Simulation':
        with open(mainfile, encoding='utf-8') as file:
            written = yaml.safe_load(file)['simulation']
        start = written['start']
        return cls(
            protocol=Path(mainfile).parent / written['protocol'],
            variant=written.get('variant'),
            name=written.get('name') or Path(mainfile).name.split('.')[0],
            start=start
            if isinstance(start, datetime)
            else datetime.fromisoformat(start),
            duration=_seconds(written['duration']),
            sample_every=_seconds(written.get('sample_every', '5 min')),
        )


def _seconds(text) -> float:
    return parse_duration(str(text)).to('s').magnitude


def simulate(measurement: StabilityMeasurement, sample_every: float) -> None:
    """Fills in the set value of every controlled quantity whose value the plan
    states, sampled every `sample_every` seconds where the plan does not say."""
    for step in measurement.steps:
        for series in step.series().values():
            if not series.controlled:
                continue
            t = times(step, series, sample_every)
            since = t - series.instruction_start.to('s').magnitude
            value = set_value(series.instruction, since)
            if value is None:
                continue
            series.time = t * ureg.second
            series.set_value = value


def times(step: StabilityMeasurementStep, series, sample_every: float) -> np.ndarray:
    """When the series is sampled, from the start of the measurement."""
    start = step.elapsed_at_start.to('s').magnitude
    length = step.duration.to('s').magnitude
    if series.sample_every is not None:
        sample_every = series.sample_every.to('s').magnitude
    return np.arange(start, start + length, max(sample_every, length / MAX_POINTS))


def set_value(instruction, since: np.ndarray):
    """What `instruction` sets its quantity to, `since` seconds after it started;
    `None` where the plan does not state it."""
    if isinstance(instruction, RampInstruction):
        return ramp(instruction, since)
    if isinstance(instruction, HoldInstruction) and instruction.set_point is not None:
        return np.full(since.shape, instruction.set_point.magnitude) * (
            instruction.set_point.units
        )
    return None


def ramp(instruction: RampInstruction, since: np.ndarray):
    """Where a ramp is, `since` seconds after it started, in its own unit; `None` for
    one whose path or pace the plan does not state."""
    start, end = instruction.start_point, instruction.end_point
    if start is None or end is None or instruction.end_of_ramp_behavior == 'cycle':
        return None
    span = (end - start).to(start.units).magnitude
    if instruction.ramp_rate is not None and span:
        rate = instruction.ramp_rate.to(start.units / ureg.second).magnitude
        length = abs(span / rate)
    elif instruction.duration is not None:
        length = instruction.duration.to('s').magnitude
    else:
        return None
    phase = since / length
    if instruction.end_of_ramp_behavior == 'sawtooth':
        phase = phase % 1
    elif instruction.end_of_ramp_behavior == 'triangle':
        phase = 1 - np.abs(phase % 2 - 1)
    return (start.magnitude + span * np.clip(phase, 0, 1)) * start.units


def load_plan(
    simulation: Simulation, logger
) -> StabilityProtocolMeasurementPlan | None:
    """The plan the simulation runs, from its `.stability.yaml`, normalized."""
    with open(simulation.protocol, encoding='utf-8') as file:
        document = yaml.safe_load(file)
    expansion = expand(document)
    variants = {
        variant.key(stem(str(simulation.protocol))): variant
        for variant in expansion.variants
    }
    if expansion.has_options:
        variant = variants.get(simulation.variant)
        if variant is None:
            logger.error(
                f'{simulation.protocol.name} has options: name one as `variant`, one '
                f'of {sorted(variants)}.'
            )
            return None
    else:
        variant = expansion.variants[0]
    translation = translate(variant.document)
    for problem in translation.problems:
        logger.error(problem.message, path=problem.path)
    return measurement_plan(translation.archive['data'], logger)


def measurement_plan(protocol: dict, logger) -> StabilityProtocolMeasurementPlan:
    """A protocol, as written in an archive, loaded as a plan to measure, normalized so
    the durations it derives are known."""
    plan = StabilityProtocolMeasurementPlan.m_from_dict(
        {**protocol, 'm_def': PLAN_M_DEF}
    )
    scratch = EntryArchive()
    for section in plan.m_all_contents(depth_first=True, include_self=True):
        section.normalize(scratch, logger)
    return plan


class StabilitySimulationParser(MatchingParser):
    """A `*.simulation.yaml`, run as a simulated `StabilityMeasurement` of its plan."""

    def parse(
        self,
        mainfile: str,
        archive: 'EntryArchive',
        logger: 'BoundLogger',
        child_archives: dict[str, 'EntryArchive'] = None,
    ) -> None:
        simulation = Simulation.read(mainfile)
        plan = load_plan(simulation, logger)
        if plan is None:
            return
        measurement = plan.create_activity(
            name=simulation.name,
            datetime=simulation.start,
            datetime_end=simulation.start + timedelta(seconds=simulation.duration),
            description='Simulated: only the set values the plan states. Nothing was '
            'measured.',
        )
        simulate(measurement, simulation.sample_every)
        archive.data = measurement
