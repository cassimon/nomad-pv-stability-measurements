"""A simulated stability measurement, for an example upload: what a run of a plan
could have logged.

A `*.simulation.yaml` names the plan and says when the run started and how long it
lasted:

    simulation:
      protocol: light-dark-cycling.stability.yaml   # beside this file
      variant: null            # the entry key of one variant, for a file with options
      name: Cell A, light–dark cycling
      start: 2026-03-02T09:00:00Z
      duration: 72 h
      sample_every: 5 min      # wherever the plan does not say how often to log
      seed: 1

The plan lays the run out as steps (`StabilityProtocolMeasurementPlan.create_activity`);
this module only makes up the data: set values from the instructions, and measured
values from a fresh cell that degrades, plus noise.
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
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import (
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldBelowInstruction,
    HoldBetweenInstruction,
    HoldInstruction,
    RampInstruction,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

#: At most this many points per series and step: a plan may ask for 10 Hz over 500 h.
MAX_POINTS = 500

#: The period of a ramp that says neither its duration nor its rate: `cycle`, say.
UNSTATED_CYCLE = 4 * 3600.0

#: How far a measured value scatters around what it should be, in the series' unit.
NOISE = {
    'temperature': 0.3,
    'irradiance': 5.0,
    'voltage': 0.002,
    'current': 0.0002,
    'power': 0.0002,
    'relative_humidity': 0.005,
    'absolute_humidity': 1e-5,
    'oxygen_fraction': 1e-7,
    'pressure': 50.0,
}

#: Less light than this, as a fraction of 1000 W/m², is dark to the cell.
DARK = 1e-3

#: Less current than this, in A, is none: no resistance can be read from it.
NO_CURRENT = 1e-9

#: The quantities of the cell itself, which follow from its light, heat and load.
ELECTRICAL = ('voltage', 'current', 'power', 'resistance')

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
    seed: int

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
            seed=written.get('seed', 0),
        )


def _seconds(text) -> float:
    return parse_duration(str(text)).to('s').magnitude


@dataclass
class Cell:
    """A fresh 1 cm² perovskite cell, at 1000 W/m² and 25 °C, that loses a few percent
    in a burn-in and then decays exponentially."""

    power_at_mpp: float = 0.020  # W
    voltage_at_mpp: float = 0.95  # V
    open_circuit_voltage: float = 1.15  # V
    short_circuit_current: float = 0.023  # A
    thermal_voltage: float = 0.04  # V, times the ideality factor
    power_temperature_coefficient: float = -0.002  # per K
    burn_in: float = 0.05
    burn_in_time: float = 20 * 3600.0  # s
    lifetime: float = 3000 * 3600.0  # s

    def health(self, t):
        """How much of its fresh performance the cell still has, after `t` seconds."""
        burn_in = 1 - self.burn_in * (1 - np.exp(-t / self.burn_in_time))
        return burn_in * np.exp(-t / self.lifetime)

    def operating_point(self, t, irradiance, temperature, load, set_value=None):
        """Voltage, current and power, for a load that is `mpp`, `open_circuit`,
        `voltage` or `current` (held at `set_value`), under `irradiance` W/m²."""
        light = np.clip(irradiance / 1000, 0, None)
        health = self.health(t)
        lit = light > DARK
        heat = 1 + self.power_temperature_coefficient * (temperature - 298.15)
        current_sc = self.short_circuit_current * light * health
        voltage_oc = np.where(
            lit,
            (
                self.open_circuit_voltage
                + self.thermal_voltage * np.log(np.where(lit, light, 1))
            )
            * health**0.2,
            0.0,
        )
        if load == 'mpp':
            power = self.power_at_mpp * light * health * heat
            voltage = np.where(lit, self.voltage_at_mpp * health**0.2, 0.0)
            current = np.divide(power, voltage, out=np.zeros_like(power), where=lit)
        elif load == 'voltage':
            voltage = set_value
            current = current_sc * (
                1 - np.exp((voltage - voltage_oc) / self.thermal_voltage)
            )
            power = voltage * current
        elif load == 'current':
            current = set_value
            voltage = voltage_oc + self.thermal_voltage * np.log(
                np.clip(1 - current / np.where(lit, current_sc, 1), 1e-9, None)
            )
            power = voltage * current
        else:
            voltage, current = voltage_oc, np.zeros_like(t)
            power = np.zeros_like(t)
        return {'voltage': voltage, 'current': current, 'power': power}

    def reference_value(self, point: str) -> float | None:
        """A point on the fresh cell's characteristic, that an instruction names."""
        fresh_current_at_mpp = self.power_at_mpp / self.voltage_at_mpp
        return {
            'V_MPP': self.voltage_at_mpp,
            'near V_MPP': 0.97 * self.voltage_at_mpp,
            'V_oc': self.open_circuit_voltage,
            '-V_oc': -self.open_circuit_voltage,
            'J_SC': self.short_circuit_current,
            '-J_MPP': -fresh_current_at_mpp,
        }.get(point)


class Simulator:
    """Fills the time series of a measurement's steps with made-up data."""

    def __init__(self, measurement: StabilityMeasurement, simulation: Simulation):
        self.measurement = measurement
        self.simulation = simulation
        self.rng = np.random.default_rng(simulation.seed)
        self.cell = Cell()
        self.outdoor = measurement.plan.environment == 'outdoor'

    def run(self) -> None:
        for step in self.measurement.steps:
            self.fill(step)

    def fill(self, step: StabilityMeasurementStep) -> None:
        # The surroundings first: the cell's output depends on its light and heat.
        for quantity, series in step.series().items():
            if quantity in ELECTRICAL:
                continue
            t = self.times(step, series)
            set_value = self.set_value(series, t)
            regulated = series.controlled and set_value is not None
            expected = set_value if regulated else self.ambient(quantity, series, t)
            self.record(series, t, quantity, set_value, expected)
        self.fill_electrical(step)

    def record(self, series, t, quantity, set_value, expected) -> None:
        """Writes what was set, if it was regulated, and what was measured, if it was
        logged."""
        unit = series.m_def.all_quantities['value'].unit
        series.time = t * ureg.second
        if series.controlled and set_value is not None:
            series.set_value = set_value * unit
        if series.monitored:
            series.value = self.noisy(quantity, expected) * unit

    def fill_electrical(self, step: StabilityMeasurementStep) -> None:
        load, held = self.load(step)
        for quantity in ELECTRICAL:
            series = getattr(step, quantity)
            if series is None:
                continue
            t = self.times(step, series)
            point = self.cell.operating_point(
                t,
                self.at(step.irradiance, t, default=self.daylight(t)),
                self.at(step.temperature, t, default=298.15),
                load,
                None if held is None else self.set_value(held, t),
            )
            if quantity == 'resistance':
                expected = np.divide(
                    point['voltage'],
                    point['current'],
                    out=np.full_like(t, np.nan),
                    where=np.abs(point['current']) > NO_CURRENT,
                )
            else:
                expected = point[quantity]
            self.record(series, t, quantity, self.set_value(series, t), expected)

    def load(self, step: StabilityMeasurementStep):
        """What the electrical load is during `step`, and the series that holds it."""
        if step.power is not None:
            return 'mpp', None
        for quantity in ('voltage', 'current'):
            series = getattr(step, quantity)
            if series is None or not series.controlled:
                continue
            if isinstance(series.instruction, VOCTracking):
                return 'open_circuit', None
            return quantity, series
        return 'open_circuit', None

    def times(self, step: StabilityMeasurementStep, series) -> np.ndarray:
        """When the series is sampled, from the start of the measurement."""
        start = step.elapsed_at_start.to('s').magnitude
        length = step.duration.to('s').magnitude
        every = (
            self.simulation.sample_every
            if series.sample_every is None
            else series.sample_every.to('s').magnitude
        )
        every = max(every, length / MAX_POINTS)
        return np.arange(start, start + length, every)

    def set_value(self, series, t) -> np.ndarray | None:
        """What the instruction sets the quantity to at `t`, in the series' unit; `None`
        where it sets no value."""
        instruction = series.instruction
        unit = series.m_def.all_quantities['value'].unit
        since = t - series.instruction_start.to('s').magnitude
        if isinstance(instruction, RampInstruction):
            value = ramp(instruction, since)
        elif isinstance(instruction, HoldBetweenInstruction):
            if instruction.lower_bound is None or instruction.upper_bound is None:
                return None
            value = (instruction.lower_bound + instruction.upper_bound) / 2
        elif isinstance(instruction, HoldBelowInstruction):
            return None  # a bound, not a value to reach
        elif isinstance(instruction, HoldInstruction):
            value = instruction.set_point
            if value is None and instruction.reference_point is not None:
                reference = self.cell.reference_value(instruction.reference_point)
                value = None if reference is None else reference * ureg(str(unit))
        else:
            return None
        if value is None:
            return None
        return np.broadcast_to(value.to(unit).magnitude, t.shape).astype(float)

    def ambient(self, quantity: str, series, t) -> np.ndarray:
        """What an unregulated quantity does: a lab's air, or the weather outdoors;
        kept well inside a bound it is held below."""
        day = np.sin(2 * np.pi * (self.clock(t) - 9 * 3600) / 86400)
        ambient = {
            'temperature': 298.15 + (8 * day if self.outdoor else 0 * day),
            'irradiance': self.daylight(t),
            'relative_humidity': 0.45 - (0.15 if self.outdoor else 0.03) * day,
            'absolute_humidity': 0.012 - 0.002 * day,
            'oxygen_fraction': 0.2095 + 0 * day,
            'pressure': 101325.0 + 0 * day,
        }.get(quantity, np.full_like(t, np.nan))
        instruction = series.instruction
        if isinstance(instruction, HoldBelowInstruction) and not isinstance(
            instruction, HoldBetweenInstruction
        ):
            if instruction.upper_bound is not None:
                unit = series.m_def.all_quantities['value'].unit
                bound = instruction.upper_bound.to(unit).magnitude
                ambient = np.minimum(ambient, 0.5 * bound)
        return ambient

    def daylight(self, t) -> np.ndarray:
        """The sun outdoors, from 6 h to 18 h, peaking at 1000 W/m²; dark indoors."""
        if not self.outdoor:
            return np.zeros_like(t)
        return np.clip(
            1000 * np.sin(np.pi * (self.clock(t) - 6 * 3600) / 43200), 0, None
        )

    def clock(self, t) -> np.ndarray:
        """The time of day at `t`, in seconds since midnight."""
        start = self.measurement.datetime
        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
        return ((start - midnight).total_seconds() + t) % 86400

    def at(self, series, t, default) -> np.ndarray:
        """`series` at the times `t`: what it was set to, or else what was measured."""
        if series is None or series.time is None:
            return np.broadcast_to(default, t.shape)
        values = series.set_value if series.set_value is not None else series.value
        if values is None:
            return np.broadcast_to(default, t.shape)
        return np.interp(t, series.time.to('s').magnitude, values.to_base_units().m)

    def noisy(self, quantity: str, values) -> np.ndarray:
        scale = NOISE.get(quantity, 0.0)
        return values + self.rng.normal(0, scale, np.shape(values))


def ramp(instruction: RampInstruction, since: np.ndarray):
    """Where a ramp is, `since` seconds after it started, in its own unit."""
    start = instruction.start_point
    span = (instruction.end_point - start).to(start.units).magnitude
    length = None
    if instruction.ramp_rate is not None and span:
        rate = instruction.ramp_rate.to(start.units / ureg.second).magnitude
        length = abs(span / rate)
    elif instruction.duration is not None:
        length = instruction.duration.to('s').magnitude
    behavior = instruction.end_of_ramp_behavior
    if behavior == 'cycle':
        period = length or UNSTATED_CYCLE
        return start + span * (1 - np.cos(2 * np.pi * since / period)) / 2 * start.units
    phase = since / (length or UNSTATED_CYCLE)
    if behavior == 'sawtooth':
        phase = phase % 1
    elif behavior == 'triangle':
        phase = 1 - np.abs(phase % 2 - 1)
    return start + span * np.clip(phase, 0, 1) * start.units


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
    data = {**translation.archive['data'], 'm_def': PLAN_M_DEF}
    plan = StabilityProtocolMeasurementPlan.m_from_dict(data)
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
            description=f'Simulated with seed {simulation.seed}: no cell was measured.',
        )
        Simulator(measurement, simulation).run()
        archive.data = measurement
