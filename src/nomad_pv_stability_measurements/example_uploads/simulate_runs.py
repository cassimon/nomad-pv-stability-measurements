"""Writes simulated runs of the example protocols, as the institution SIM writes them.

Run it from anywhere with the plugin's Python:

    python -m nomad_pv_stability_measurements.example_uploads.simulate_runs

It simulates one run of each protocol file in `isos/`, written to `simulated_data/`,
and in `custom_protocols/`, written beside the protocols. Of a file with options it
takes the first variant, the first alternative of every option. The runs in
`protocols_in_run_files/` follow no protocol file: their run files describe the test
under `test conditions`, taken from `TEST_CONDITIONS`. Each run is a folder named after
the standard, or else after the protocol file or the test:

    ISOS-L-2/
      ISOS-L-2.run.yaml         who ran what, when, on which samples, and the steps
      01_jv_initial.csv         J–V sweep of the fresh device, reverse then forward
      02_stability_series.csv   every quantity logged, in one table, one row per sample
      03_jv_final.csv           J–V sweep after the ageing

A protocol whose routine is a sequence of phases, run once, gets one stability series
per phase, and a J–V sweep wherever it places a J–V scan; where it places none, before
the first phase, between two and after the last. J–V scans the protocol repeats are
taken inside the series, every `interval`, or every `SCAN_EVERY` where it leaves that
open. `file_reading/file_reading_SIM.py` reads the format.

The stability series has a `time` column and one column per quantity the protocol
monitors or controls, since a controller logs what it regulates, the unit in the
header. What is simulated follows the protocol's instruction tree: phases one after
another, conditions side by side, blocks repeated a number of times, for a time or
indefinitely, held values with noise, ramps, the band a solar simulator is kept in, an
ambient room and an outdoor day. MPP tracking reads the cell's output; a bias at a
voltage or a current reads what the cell answers, the points it names taken from the
initial J–V sweep; where the protocol neither tracks nor biases, a lit cell sits at
open circuit. What the protocol leaves open is assumed and written into the run's
`notes`.

Nothing here is measured. The output is fixed by a seed per run, so running the script
again reproduces the same files.
"""

import csv
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cache
from math import inf
from pathlib import Path

import numpy as np
import yaml
from nomad.datamodel import EntryArchive

from nomad_pv_stability_measurements.file_reading.file_reading_utils import (
    protocol_from_phases,
)
from nomad_pv_stability_measurements.parsers.options import expand
from nomad_pv_stability_measurements.parsers.parser import stem
from nomad_pv_stability_measurements.parsers.translate import translate
from nomad_pv_stability_measurements.schema_packages.base_instructions import (
    MonitorControlInstruction,
    RampInstruction,
)
from nomad_pv_stability_measurements.schema_packages.characterization_instructions import (
    JVScan,
)
from nomad_pv_stability_measurements.schema_packages.general import (
    FIXED,
    TYPICAL,
    InstructionBlock,
    seconds_of,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol

HERE = Path(__file__).parent
#: Each folder of protocol files, where their runs are written, and where the protocols
#: are in the example upload, from its root.
SOURCES = (
    (HERE / 'isos', HERE / 'simulated_data', 'isos/'),
    (HERE / 'custom_protocols', HERE / 'custom_protocols', ''),
)
#: Where the runs of `TEST_CONDITIONS` are written.
IN_RUN_FILES = HERE / 'protocols_in_run_files'
#: Tests described in the run file instead of a protocol file, by the run's folder, as
#: SIM writes them under `test conditions`: phases run one after another, `repeat`
#: times, and what each holds. The first quantity of a phase sets how long it lasts.
TEST_CONDITIONS = {
    'damp-heat-at-open-circuit': {
        'name': 'Damp heat at open circuit',
        'repeat': 1,
        'phases': [
            {
                'name': 'damp heat',
                'duration': '1000 h',
                'temperature': '85 °C',
                'relative_humidity': '85 %',
                'irradiance': 'dark',
                'electrical_load': 'open_circuit',
            }
        ],
    },
    'day-and-night-at-45C': {
        'name': 'Day and night at 45 °C',
        'repeat': 7,
        'phases': [
            {
                'name': 'day',
                'duration': '12 h',
                'irradiance': '1000 W/m^2',
                'temperature': '45 °C',
                'electrical_load': 'mpp',
            },
            {
                'name': 'night',
                'duration': '12 h',
                'irradiance': 'dark',
                'temperature': '45 °C',
                'electrical_load': 'open_circuit',
            },
        ],
    },
}

#: How long a run lasts where the protocol does not end sooner.
RUN_LENGTH = 168.0  # h: one week
SAMPLE_EVERY = 10 / 60  # h
START = datetime(2026, 3, 2, 9, 0, tzinfo=timezone(timedelta(hours=1)))
#: Between a J–V sweep and the ageing, either way round.
CHANGEOVER = timedelta(minutes=10)
JV_LENGTH = timedelta(minutes=2)

#: J–V scans the protocol repeats without saying how often are assumed this far apart.
SCAN_EVERY = 24.0  # h

#: A cycling ramp whose rate the protocol does not state is assumed to take this.
CYCLE_PERIOD = 6.0  # h
#: A stepped cycle (`cycle`) spends this of each half period moving between its ends.
STEP_TRANSITION = 1.0  # h

INSTITUTION = 'SIM'
OPERATOR = 'A. Researcher'
SIMULATED = 'Simulated data: nothing was measured.'

#: Column name and unit of each quantity in the stability series, in the order written.
COLUMNS = {
    'time': 'h',
    'temperature': '°C',
    'irradiance': 'W/m^2',
    'relative_humidity': '%',
    'voltage': 'V',
    'current_density': 'mA/cm^2',
    'power_density': 'mW/cm^2',
}
DECIMALS = {
    'time': 4,
    'temperature': 2,
    'irradiance': 1,
    'relative_humidity': 1,
    'voltage': 4,
    'current_density': 3,
    'power_density': 3,
}
#: The unit each condition is simulated in, and how much it scatters around its value.
CONDITIONS = {
    'irradiance': ('W/m^2', 2.0),
    'temperature': ('degC', 0.3),
    'relative_humidity': ('percent', 0.5),
}

# The simulated cell: efficiency, J–V shape and how fast it ages.
EFFICIENCY = 0.20
SUN = 1000.0  # W/m^2
JSC = 23.5  # mA/cm^2 at one sun
VOC = 1.12  # V at one sun
IDEALITY = 1.5
THERMAL_VOLTAGE = 0.0257  # V at 25 °C
SHUNT = 3000.0  # Ω cm^2
ACTIVATION = 0.3  # eV
BOLTZMANN = 8.617e-5  # eV/K


# --- Reading the protocol ---------------------------------------------------------


class _Quiet:
    """A logger for normalizing the example protocols, which are known to be sound."""

    def error(self, *args, **kwargs):
        pass

    warning = info = debug = error


@dataclass
class Source:
    """A protocol to simulate a run of, and how the run file tells of it."""

    protocol: StabilityProtocol
    key: str  # the protocol's entry name
    designation: str  # the run's folder, and its file's name
    refers: dict  # what the run file says of it under `run`
    describes: dict | None = None  # the test conditions, if the run file has them


def loaded(document: dict) -> StabilityProtocol:
    """The protocol of `document`, what a protocol file without options holds, loaded
    and normalized, so that every block knows its duration."""
    protocol = StabilityProtocol.m_from_dict(translate(document).archive['data'])
    for section in protocol.m_all_contents(depth_first=True, include_self=True):
        section.normalize(EntryArchive(), _Quiet())
    return protocol


def first_variant(path: Path, in_upload: str) -> Source:
    """The first variant of the protocol file `path`, which the upload holds at
    `in_upload`."""
    expansion = expand(yaml.safe_load(path.read_text(encoding='utf-8')))
    variant = expansion.variants[0]
    key = variant.key(stem(str(path))) if expansion.has_options else stem(str(path))
    protocol = loaded(variant.document)
    return Source(
        protocol=protocol,
        key=key,
        designation=protocol.standard or stem(str(path)),
        refers={'protocol': f'{in_upload}{path.name}', 'variant': key},
    )


def described(designation: str, conditions: dict) -> Source:
    """The test a run file describes under `test conditions`."""
    protocol = loaded(protocol_from_phases(**conditions))
    return Source(
        protocol=protocol,
        key=protocol.name,
        designation=designation,
        refers={},
        describes=conditions,
    )


#: The electrical loads the simulation knows, by class: the cell tracked at its
#: maximum power point, or biased at a voltage or a current.
LOADS = {
    'MPPTracking': 'mpp',
    'HoldVoltage': 'bias_voltage',
    'HoldCurrent': 'bias_current',
}


def quantity_of(instruction) -> str | None:
    """Which quantity an instruction is about, if one the simulation knows."""
    name = type(instruction).__name__
    if name in LOADS:
        return LOADS[name]
    for suffix, quantity in (
        ('Temperature', 'temperature'),
        ('Irradiance', 'irradiance'),
        ('RelativeHumidity', 'relative_humidity'),
    ):
        if name.endswith(suffix):
            return quantity
    return None


def hours(instruction) -> float:
    return instruction.seconds() / 3600


def segments(instruction, start: float, stop: float) -> list[tuple]:
    """When each single instruction in `instruction` is in force, as
    `(start, end, instruction)` in hours, up to `stop` where its container ends."""
    if not isinstance(instruction, InstructionBlock):
        return [(start, min(stop, start + hours(instruction)), instruction)]
    one = seconds_of(instruction.one_iteration()) / 3600
    end = min(stop, start + hours(instruction))
    found, time, count = [], start, 0
    while time < end and count < instruction.repetitions():
        found += run_together(
            instruction.sub_instructions,
            instruction.sub_instruction_execution_mode,
            time,
            min(end, time + one),
        )
        if one in (0, inf):
            break
        time, count = time + one, count + 1
    return found


def run_together(instructions, mode: str, start: float, stop: float) -> list[tuple]:
    """`instructions` one after another (`sequential`) or all from `start`."""
    found, time = [], start
    for each in instructions:
        if time >= stop:
            break
        found += segments(each, time, stop)
        if mode == 'sequential':
            time += hours(each)
    return found


def recorded(protocol) -> set[str]:
    """What the run logs: what the protocol monitors, and what it controls, since a
    controller logs what it regulates."""
    return {
        quantity_of(each)
        for each in protocol.m_all_contents()
        if isinstance(each, MonitorControlInstruction)
        and (each.monitor or each.control)
    } - {None}


@dataclass
class Step:
    """A step of the run: a stability series (`series`) or a J–V sweep (`jv`), from
    `start` to `end` in hours of the protocol. `placed`: where the protocol puts it;
    a J–V sweep the simulation adds takes none of the protocol's time."""

    kind: str
    name: str
    start: float
    end: float
    placed: bool = True


def planned_steps(protocol, length: float) -> list[Step]:
    """The steps of a routine that runs a sequence once, each with a length, J–V scans
    where it places them and every other part a stability series of its own; else one
    series over the whole run. A J–V sweep is added where the protocol places none:
    before the first series, between two, and after the last."""
    found = [Step('series', 'ageing', 0.0, length)]
    for block in protocol.instructions:
        if (
            isinstance(block, InstructionBlock)
            and block.repetitions() == 1
            and block.sub_instruction_execution_mode == 'sequential'
            and len(block.sub_instructions) > 1
            and all(hours(each) < inf for each in block.sub_instructions)
        ):
            found, time = [], 0.0
            for each in block.sub_instructions:
                kind = 'jv' if isinstance(each, JVScan) else 'series'
                name = each.name or each.describe()
                if time < length:
                    found.append(
                        Step(kind, name, time, min(length, time + hours(each)))
                    )
                time += hours(each)
            break
    steps = []
    for each in found:
        if each.kind == 'series' and (not steps or steps[-1].kind == 'series'):
            if steps:
                after = steps[-1]
                name, at = f'J–V after {after.name}', after.end
            else:
                name, at = 'initial J–V', 0.0
            steps.append(Step('jv', name, at, at, placed=False))
        steps.append(each)
    if steps[-1].kind == 'series':
        at = steps[-1].end
        steps.append(Step('jv', 'final J–V', at, at, placed=False))
    return steps


def periodic_scans(protocol, series: list[Step], length: float, clock) -> list[Step]:
    """The J–V scans the protocol repeats, every `interval` from where they start,
    inside a stability series and not at its ends, where the sweeps of `planned_steps`
    already are. An interval the protocol leaves open is assumed, and noted."""
    found = []
    for start, end, instruction in run_together(
        protocol.instructions, 'parallel', 0.0, length
    ):
        interval = getattr(instruction, 'interval', None)
        if not isinstance(instruction, JVScan) or interval is None:
            continue
        if interval.kind in (FIXED, TYPICAL) and interval.value is not None:
            every = interval.value.to('hour').magnitude
        else:
            every = SCAN_EVERY
            clock.notes.add(
                f'The protocol repeats its J–V scans without saying how often: they '
                f'are assumed {SCAN_EVERY:g} h apart.'
            )
        time = start + every
        while time < end - 1e-9:
            if any(each.start < time < each.end for each in series):
                found.append(Step('jv', f'J–V at {time:g} h', time, time))
            time += every
    return found


def controlled(protocol, start: float, end: float, length: float) -> list[str]:
    """The columns the protocol controls between `start` and `end` hours, by the name
    of the quantity each fills, in the order of `COLUMNS`."""
    found = {
        column.replace(' ', '_').replace('current', 'current_density')
        for begins, ends, instruction in run_together(
            protocol.instructions, 'parallel', 0.0, length
        )
        if begins < end
        and ends > start
        and isinstance(instruction, MonitorControlInstruction)
        and instruction.control
        for column in instruction.controlled_quantities()
    }
    return [name for name in COLUMNS if name in found]


# --- Simulating the conditions -------------------------------------------------------


@dataclass
class Clock:
    """The sampling times of a run, and what the simulation draws and assumes."""

    t: np.ndarray  # h since the ageing started
    hour: float  # o'clock when the ageing started
    rng: np.random.Generator
    notes: set = field(default_factory=set)

    @property
    def of_day(self) -> np.ndarray:
        return (self.hour + self.t) % 24

    @property
    def day(self) -> np.ndarray:
        return ((self.hour + self.t) // 24).astype(int)

    def noise(self, spread: float) -> np.ndarray:
        return self.rng.normal(0, spread, self.t.size)


def daily(clock: np.ndarray, peak: float = 15.0) -> np.ndarray:
    """1 at `peak` o'clock, -1 twelve hours later."""
    return np.cos(2 * np.pi * (clock - peak) / 24)


def stepped(u: np.ndarray, low: float, high: float, period: float) -> np.ndarray:
    """Up, dwell, down, dwell: the ends stated, the path between them assumed."""
    phase = u % period
    rising = np.clip(phase / STEP_TRANSITION, 0, 1)
    falling = np.clip((phase - period / 2) / STEP_TRANSITION, 0, 1)
    return low + (high - low) * (rising - falling)


def ramp(instruction, quantity: str, clock: Clock, since: np.ndarray) -> np.ndarray:
    """A ramp of any quantity, `since` hours after it started: by its rate, else
    over its own duration; one that cycles with neither, over an assumed period."""
    unit, spread = CONDITIONS[quantity]
    low = instruction.start_point.to(unit).magnitude
    high = instruction.end_point.to(unit).magnitude
    behavior = instruction.end_of_ramp_behavior or 'hold'
    if instruction.ramp_rate is not None:
        span = abs(instruction.end_point - instruction.start_point)
        length = (span / instruction.ramp_rate).to('hour').magnitude
    elif behavior == 'hold' and hours(instruction) < inf:
        length = hours(instruction)
    else:
        length = CYCLE_PERIOD / 2
        clock.notes.add(
            f'The protocol states no rate for the {quantity.replace("_", " ")} '
            f'cycle: one cycle is assumed to take {CYCLE_PERIOD:g} h.'
        )
    if behavior == 'hold':
        shape = np.clip(since / length, 0, 1)
    elif behavior == 'sawtooth':
        shape = (since % length) / length
    elif behavior == 'triangle':
        shape = 1 - np.abs(2 * ((since % (2 * length)) / (2 * length)) - 1)
    else:
        return stepped(since, low, high, 2 * length) + clock.noise(spread)
    return low + (high - low) * shape + clock.noise(spread)


def irradiance(instruction, clock: Clock) -> np.ndarray:
    t = clock.t
    if type(instruction).__name__ == 'HoldBetweenIrradiance':
        low = instruction.lower_bound.to('W/m^2').magnitude
        high = instruction.upper_bound.to('W/m^2').magnitude
        drift = 0.4 * (high - low) / 2 * np.sin(2 * np.pi * t / 50)
        return np.clip((low + high) / 2 + drift + clock.noise(3), low, high)
    if instruction.value is not None:
        value = instruction.value.to('W/m^2').magnitude
        return value + (clock.noise(2) if value else 0 * t)
    # Not controlled and no value: the sun.
    clock.notes.add(
        'The sun is a clear-sky day, dimmed by a cloud factor drawn per day.'
    )
    sun = np.clip(np.sin(np.pi * (clock.of_day - 6) / 12), 0, None) ** 1.3
    clouds = clock.rng.uniform(0.55, 1.0, int(clock.day.max()) + 1)[clock.day]
    return 1000 * sun * clouds * (1 + clock.noise(0.03))


def temperature(instruction, clock: Clock, light: np.ndarray) -> np.ndarray:
    if instruction.value is None:
        # Outdoors: the day, and the sun heating the cell.
        return 8 + 6 * daily(clock.of_day) + 0.025 * light + clock.noise(0.3)
    value = instruction.value.to('degC').magnitude
    if instruction.control:
        return value + clock.noise(0.3)
    # An ambient room, warmed a little by a lamp.
    return value + daily(clock.of_day) + 0.003 * light + clock.noise(0.2)


def relative_humidity(instruction, clock: Clock, temp: np.ndarray) -> np.ndarray:
    if getattr(instruction, 'upper_bound', None) is not None:
        # Kept below a bound: the room's, dried where it would rise above it.
        bound = instruction.upper_bound.to('percent').magnitude
        return np.minimum(ambient_humidity(clock), bound - 2 + clock.noise(0.5))
    if instruction.value is not None:
        value = instruction.value.to('percent').magnitude
        return value + clock.noise(0.5)
    if instruction.m_root().environment == 'outdoor':
        return np.clip(70 - 1.5 * (temp - 15) + clock.noise(1), 15, 100)
    return ambient_humidity(clock)


def ambient_humidity(clock: Clock) -> np.ndarray:
    drift = 3 * np.sin(2 * np.pi * clock.t / 70)
    return 40 - 5 * daily(clock.of_day) + drift + clock.noise(0.8)


def bias(instruction, clock: Clock) -> float:
    """The voltage (V) or current density (mA/cm²) a bias holds: its value, or the
    point of the fresh device's J–V curve it names, taken from the initial scan."""
    point = instruction.reference_point
    if point is not None:
        clock.notes.add(
            'The bias points are taken from the reverse scan of the initial J–V sweep.'
        )
        return fresh_points()[point]
    if instruction.value is None:
        return np.nan
    if type(instruction).__name__ == 'HoldCurrent':
        raise ValueError('a current bias in A needs the cell area, which SIM has not.')
    return instruction.value.to('V').magnitude


def conditions(protocol, clock: Clock, length: float) -> dict[str, np.ndarray]:
    """Irradiance, temperature and relative humidity over the run, whether monitored
    or not, since the cell ages under all of them; `mpp`, where it is tracked; and
    `bias_voltage` or `bias_current`, where the cell is biased, NaN where not.
    Where instructions overlap, the one written later holds."""
    t = clock.t
    found = run_together(protocol.instructions, 'parallel', 0.0, length)

    def over_time(quantity, held, default):
        values = np.array(default, dtype=float)
        for start, end, instruction in found:
            if quantity_of(instruction) != quantity:
                continue
            mask = (t >= start) & ((t < end) | (end >= length))
            if isinstance(instruction, RampInstruction):
                simulated = ramp(instruction, quantity, clock, t - start)
            else:
                simulated = held(instruction)
            values[mask] = simulated[mask]
        return values

    light = over_time('irradiance', lambda each: irradiance(each, clock), 0 * t)
    temp = over_time(
        'temperature',
        lambda each: temperature(each, clock, light),
        23 + daily(clock.of_day) + clock.noise(0.2),
    )
    humidity = over_time(
        'relative_humidity',
        lambda each: relative_humidity(each, clock, temp),
        ambient_humidity(clock),
    )
    tracked = over_time('mpp', lambda each: np.ones_like(t), 0 * t) > 0
    biased = {
        quantity: over_time(
            quantity, lambda each: np.full(t.shape, bias(each, clock)), np.nan * t
        )
        for quantity in ('bias_voltage', 'bias_current')
    }
    return {
        'irradiance': light,
        'temperature': temp,
        'relative_humidity': humidity,
        'mpp': tracked,
        **biased,
    }


# --- Simulating the cell ---------------------------------------------------------------


def remaining(values: dict[str, np.ndarray]) -> np.ndarray:
    """The fraction of its efficiency the cell keeps over time: a burn-in, then a
    steady loss, faster when hotter, lit and humid."""
    kelvin = values['temperature'] + 273.15
    heat = np.exp(ACTIVATION / BOLTZMANN * (1 / 298.15 - 1 / kelvin))
    light = 0.2 + 0.8 * np.clip(values['irradiance'], 0, None) / 1000
    damp = 1 + values['relative_humidity'] / 100
    stress = np.cumsum(heat * light * damp * SAMPLE_EVERY)
    return np.clip(1 - 0.04 * (1 - np.exp(-stress / 20)) - 0.0003 * stress, 0, 1)


def cell_current(voltage, light, kept):
    """mA/cm²: what the cell gives at `voltage` (V) under `light` (W/m²), aged to
    `kept`: the J–V curve of `jv_sweep`, lit or dark."""
    jsc = JSC * kept**0.4
    voc = VOC + IDEALITY * THERMAL_VOLTAGE * np.log(kept**0.6)
    dark = jsc / (np.exp(voc / (IDEALITY * THERMAL_VOLTAGE)) - 1)
    diode = dark * (np.exp(voltage / (IDEALITY * THERMAL_VOLTAGE)) - 1)
    return jsc * np.clip(light, 0, None) / SUN - diode - 1000 * voltage / SHUNT


def cell_voltage(current, light, kept):
    """V: where the cell gives `current` (mA/cm²), by bisection, since the current
    falls as the voltage rises."""
    low, high = np.full(np.shape(light), -3.0), np.full(np.shape(light), 1.5)
    for _ in range(50):
        middle = (low + high) / 2
        above = cell_current(middle, light, kept) > current
        low, high = np.where(above, middle, low), np.where(above, high, middle)
    return (low + high) / 2


def electrical(values, kept, clock: Clock) -> dict[str, np.ndarray]:
    """What the load reads: the bias where the cell is biased, the maximum power point
    where it is tracked, open circuit where it is neither, and nothing in the dark
    unbiased. The power is what the cell gives, negative where the bias drives it."""
    light = values['irradiance']
    lit = light > 1
    tracked = lit & values['mpp']
    suns = np.where(lit, light, 1000) / 1000
    heat = 1 - 0.002 * (values['temperature'] - 25)
    at_mpp = 0.95 * kept**0.3 * (1 + 0.026 * np.log(suns)) * heat
    open_circuit = (VOC + IDEALITY * THERMAL_VOLTAGE * np.log(kept**0.6 * suns)) * heat
    voltage = np.where(tracked, at_mpp, open_circuit) + clock.noise(0.002)
    voltage = np.where(lit, voltage, 0)
    power = EFFICIENCY * kept * heat * light / 10  # W/m^2 → mW/cm^2
    power = np.where(tracked, power * (1 + clock.noise(0.005)), 0)
    current = np.divide(power, voltage, out=np.zeros_like(power), where=tracked)
    at_voltage = ~np.isnan(values['bias_voltage'])
    at_current = ~np.isnan(values['bias_current'])
    if at_voltage.any() or at_current.any():
        held = np.where(at_voltage, values['bias_voltage'], 0.0)
        voltage = np.where(at_voltage, held, voltage)
        current = np.where(at_voltage, cell_current(held, light, kept), current)
        held = np.where(at_current, values['bias_current'], 0.0)
        voltage = np.where(at_current, cell_voltage(held, light, kept), voltage)
        current = np.where(at_current, held, current)
        biased = at_voltage | at_current
        current = current + np.where(biased, clock.noise(0.002), 0)
        power = np.where(biased, voltage * current, power)
    return {'voltage': voltage, 'current_density': current, 'power_density': power}


def jv_sweep(kept: float) -> list[tuple[float, float, str]]:
    """A J–V sweep at one sun and 25 °C, reverse then forward, the forward slightly
    lower as a perovskite's hysteresis has it."""
    rows = []
    for direction, loss in (('reverse', 0.0), ('forward', 0.01)):
        jsc = JSC * kept**0.4 * (1 - loss)
        voc = VOC + IDEALITY * THERMAL_VOLTAGE * np.log(kept**0.6) - loss
        dark = jsc / (np.exp(voc / (IDEALITY * THERMAL_VOLTAGE)) - 1)
        voltages = np.round(np.arange(-0.1, 1.1501, 0.01), 3)
        if direction == 'reverse':
            voltages = voltages[::-1]
        for voltage in voltages:
            diode = dark * (np.exp(voltage / (IDEALITY * THERMAL_VOLTAGE)) - 1)
            rows.append((voltage, jsc - diode - 1000 * voltage / SHUNT, direction))
    return rows


@cache
def fresh_points() -> dict[str, float]:
    """The points of the fresh device's J–V curve a bias names, from the reverse scan
    of the initial sweep: voltages in V, current densities in mA/cm²."""
    scan = [row for row in jv_sweep(1.0) if row[2] == 'reverse']
    voltage = np.round([row[0] for row in scan], 3)
    current = np.round([row[1] for row in scan], 4)
    _, voc, jsc, _, _, vmpp, jmpp, _, _ = figures_of_merit(voltage, current)
    return {
        'V_MPP': vmpp,
        'near V_MPP': vmpp,
        'V_oc': voc,
        '-V_oc': -voc,
        'J_SC': jsc,
        '-J_MPP': -jmpp,
    }


# --- Writing a run -----------------------------------------------------------------


def instruments(protocol, quantities: set[str]) -> list[dict]:
    kinds = [
        (quantity_of(each), each)
        for each in protocol.m_all_contents()
        if isinstance(each, MonitorControlInstruction)
    ]
    names = []
    if protocol.environment == 'outdoor':
        names += ['outdoor test rack', 'pyranometer']
    elif 'irradiance' in quantities:
        names.append('solar simulator')
    if any(kind == 'relative_humidity' and each.control for kind, each in kinds):
        names.append('climate chamber')
    elif any(
        kind == 'temperature' and isinstance(each, RampInstruction)
        for kind, each in kinds
    ):
        names.append('thermal cycling chamber')
    elif any(kind == 'temperature' and each.control for kind, each in kinds):
        names.append('oven')
    if 'mpp' in quantities:
        names.append('MPP tracker')
    if quantities & {'bias_voltage', 'bias_current'}:
        names.append('source meter')
    names += ['temperature and humidity logger', 'J–V station']
    return [{'name': name} for name in names]


def write_table(path: Path, columns: dict[str, np.ndarray]) -> None:
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(f'{name} ({COLUMNS[name]})' for name in columns)
        formatted = [
            [f'{value:.{DECIMALS[name]}f}' for value in values]
            for name, values in columns.items()
        ]
        writer.writerows(zip(*formatted))


#: What the J–V station reports of each scan, by column, and how it writes each.
FIGURES_OF_MERIT = {
    'direction': '{}',
    'irradiance (W/m^2)': '{:.0f}',
    'open_circuit_voltage (V)': '{:.4f}',
    'short_circuit_current_density (mA/cm^2)': '{:.3f}',
    'fill_factor (%)': '{:.2f}',
    'efficiency (%)': '{:.3f}',
    'potential_at_maximum_power_point (V)': '{:.3f}',
    'current_density_at_maximum_power_point (mA/cm^2)': '{:.3f}',
    'series_resistance (ohm*cm^2)': '{:.3f}',
    'shunt_resistance (ohm*cm^2)': '{:.0f}',
}


def figures_of_merit(voltage: np.ndarray, current: np.ndarray) -> tuple:
    """What a J–V station works out of one scan (V, mA/cm², at one sun): the values of
    `FIGURES_OF_MERIT` after the direction, in order."""
    order = np.argsort(voltage)
    voltage, current = voltage[order], current[order]
    voc = np.interp(0.0, -current, voltage)  # the current falls as the voltage rises
    jsc = np.interp(0.0, voltage, current)
    best = np.argmax(voltage * current)
    vmpp, jmpp = voltage[best], current[best]
    fill_factor = vmpp * jmpp / (voc * jsc)
    efficiency = vmpp * jmpp / (SUN / 10)  # mW/cm² over the light's mW/cm²

    def slope_at(index: int) -> float:  # Ω cm²: V over mA/cm², times 1000
        return (
            -1000
            * (voltage[index + 1] - voltage[index - 1])
            / (current[index + 1] - current[index - 1])
        )

    series = slope_at(int(np.searchsorted(voltage, voc)))
    shunt = slope_at(int(np.searchsorted(voltage, 0.0)))
    return (
        SUN,
        voc,
        jsc,
        100 * fill_factor,
        100 * efficiency,
        vmpp,
        jmpp,
        series,
        shunt,
    )


def write_jv(path: Path, kept: float) -> None:
    """The station's figures of merit, one row per scan, an empty line, the curve."""
    sweep = jv_sweep(kept)
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(FIGURES_OF_MERIT)
        for direction in dict.fromkeys(row[2] for row in sweep):
            # Worked out of the curve as the file holds it.
            scan = [row for row in sweep if row[2] == direction]
            voltage = np.round([row[0] for row in scan], 3)
            current = np.round([row[1] for row in scan], 4)
            values = (direction, *figures_of_merit(voltage, current))
            writer.writerow(
                style.format(value)
                for style, value in zip(FIGURES_OF_MERIT.values(), values)
            )
        writer.writerow([])
        writer.writerow(['voltage (V)', 'current_density (mA/cm^2)', 'direction'])
        for voltage, current, direction in sweep:
            writer.writerow([f'{voltage:.3f}', f'{current:.4f}', direction])


def slug(text: str) -> str:
    return re.sub(r'\W+', '_', text.lower()).strip('_')


@dataclass
class Recording:
    """What a run recorded: the stability series' `columns` over the `clock`, the
    fraction of its efficiency the cell `kept`, from `started` for `length` hours."""

    clock: Clock
    columns: dict[str, np.ndarray]
    kept: np.ndarray
    started: datetime
    length: float


def ageing_offset(planned: list[Step]) -> timedelta:
    """Where the protocol places no first sweep, the ageing starts after one."""
    return timedelta(0) if planned[0].placed else JV_LENGTH + CHANGEOVER


def write_steps(
    folder: Path, protocol, planned: list[Step], recording: Recording
) -> list[tuple]:
    """Write the files of the `planned` steps and of the scans the protocol repeats
    inside them; returns each step as `(name, kind, file, start, controlled)`."""
    clock, columns, kept = recording.clock, recording.columns, recording.kept
    length, begins = recording.length, recording.started + ageing_offset(planned)
    number = iter(range(1, 1000))

    def kept_at(time: float) -> float:
        return 1.0 if time <= 0 else float(np.interp(time, clock.t, kept))

    def jv_file(position: int, step: Step) -> str:
        if position == 0:
            name = 'jv_initial'
        elif position == len(planned) - 1:
            name = 'jv_final'
        else:
            name = slug(step.name).replace('j_v', 'jv')
        return f'{next(number):02d}_{name}.csv'

    series = [each for each in planned if each.kind == 'series']
    periodic = periodic_scans(protocol, series, length, clock)
    # Shifted by the J–V sweeps the protocol does not place, each taking its own time
    # and a changeover either side.
    delay = timedelta(0)
    steps = []
    for position, step in enumerate(planned):
        if step.kind == 'jv':
            at = begins + delay + timedelta(hours=step.start)
            if not step.placed and not position:
                at = recording.started
            elif not step.placed:
                at += CHANGEOVER
                delay += CHANGEOVER + JV_LENGTH + CHANGEOVER
            file = jv_file(position, step)
            write_jv(folder / file, kept_at(step.start))
            steps.append((step.name, 'jv', file, at, []))
            continue
        last = step is series[-1]
        rows = (clock.t >= step.start) & ((clock.t < step.end) | last)
        table = {column: values[rows] for column, values in columns.items()}
        table['time'] = table['time'] - step.start
        suffix = '' if len(series) == 1 else f'_{slug(step.name)}'
        file = f'{next(number):02d}_stability_series{suffix}.csv'
        write_table(folder / file, table)
        held = controlled(protocol, step.start, step.end, length)
        steps.append(
            (
                step.name,
                'stability_series',
                file,
                begins + delay + timedelta(hours=step.start),
                [each for each in held if each in table],
            )
        )
        for scan in periodic:
            if step.start < scan.start < step.end:
                file = f'{next(number):02d}_{slug(scan.name).replace("j_v", "jv")}.csv'
                write_jv(folder / file, kept_at(scan.start))
                at = begins + delay + timedelta(hours=scan.start)
                steps.append((scan.name, 'jv', file, at, []))

    return steps


def simulate(source: Source, index: int, output: Path) -> str:
    """Write the run of `source` into `output`; returns the protocol's entry name."""
    key, protocol, designation = source.key, source.protocol, source.designation
    length = min(RUN_LENGTH, hours(protocol))
    started = START + timedelta(days=7 * index)
    planned = planned_steps(protocol, length)
    ageing_start = started + ageing_offset(planned)
    clock = Clock(
        t=np.round(np.arange(0, length + SAMPLE_EVERY / 2, SAMPLE_EVERY), 6),
        hour=ageing_start.hour + ageing_start.minute / 60,
        rng=np.random.default_rng(zlib.crc32(designation.encode())),
    )
    values = conditions(protocol, clock, length)
    kept = remaining(values)
    quantities = recorded(protocol)

    columns = {'time': clock.t}
    columns.update({name: values[name] for name in CONDITIONS if name in quantities})
    if quantities & set(LOADS.values()):
        columns.update(electrical(values, kept, clock))
    columns = {name: columns[name] for name in COLUMNS if name in columns}

    folder = output / designation
    folder.mkdir(parents=True, exist_ok=True)
    recording = Recording(clock, columns, kept, started, length)
    steps = write_steps(folder, protocol, planned, recording)

    run = {
        'institution': INSTITUTION,
        'name': f'{key if protocol.standard else protocol.name or key}, cell A',
        **source.refers,
        'standard': protocol.standard,
        'operator': OPERATOR,
        'start': started.isoformat(),
        'end': (max(step[3] for step in steps) + JV_LENGTH).isoformat(),
        'location': 'Berlin, rooftop test site'
        if protocol.environment == 'outdoor'
        else 'Berlin, lab 2.14',
        'samples': [{'name': 'cell A'}],
        'instruments': instruments(protocol, quantities),
        'notes': ' '.join([SIMULATED, *sorted(clock.notes)]),
    }
    document = {
        'run': {name: value for name, value in run.items() if value is not None},
        **({'test conditions': source.describes} if source.describes else {}),
        'steps': [
            {
                'name': name,
                'kind': kind,
                'file': file,
                'start': start.isoformat(),
                **({'controlled': held} if held else {}),
            }
            for name, kind, file, start, held in sorted(steps, key=lambda s: s[3])
        ],
    }
    (folder / f'{designation}.run.yaml').write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=88),
        encoding='utf-8',
    )
    return key


def main() -> None:
    runs = [
        (first_variant(path, in_upload), output)
        for protocols, output, in_upload in SOURCES
        for path in sorted(protocols.glob('*.stability.yaml'))
    ]
    runs += [
        (described(designation, conditions), IN_RUN_FILES)
        for designation, conditions in TEST_CONDITIONS.items()
    ]
    for index, (source, output) in enumerate(runs):
        print(simulate(source, index, output))


if __name__ == '__main__':
    main()
