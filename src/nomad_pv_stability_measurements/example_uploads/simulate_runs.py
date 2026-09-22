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
      02_stability_series.csv   every monitored quantity in one table, one row per sample
      03_jv_final.csv           J–V sweep after the ageing

A protocol whose routine is a sequence of phases, run once, gets one stability series
per phase and a J–V sweep between them. `file_reading/file_reading_SIM.py` reads the format.

The stability series has a `time` column and one column per quantity the protocol
monitors, the unit in the header. What is simulated follows the protocol's instruction
tree: phases one after another, conditions side by side, blocks repeated a number of
times, for a time or indefinitely, held values with noise, ramps, the band a solar
simulator is kept in, an ambient room and an outdoor day. MPP tracking reads the cell's
output; where the protocol does not track, a lit cell sits at open circuit. What the
protocol leaves open is assumed and written into the run's `notes`.

Nothing here is measured. The output is fixed by a seed per run, so running the script
again reproduces the same files.
"""

import csv
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
from nomad_pv_stability_measurements.schema_packages.general import (
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


def quantity_of(instruction) -> str | None:
    """Which quantity an instruction is about, if one the simulation knows."""
    name = type(instruction).__name__
    if name == 'MPPTracking':
        return 'mpp'
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


def monitored(protocol) -> set[str]:
    return {
        quantity_of(each)
        for each in protocol.m_all_contents()
        if isinstance(each, MonitorControlInstruction) and each.monitor
    } - {None}


def phases(protocol, length: float) -> list[tuple[str, float, float]]:
    """The phases the run is recorded in, as `(name, start, end)` in hours: those of a
    routine that runs a sequence once, each with a length; else the whole run."""
    for block in protocol.instructions:
        if not (
            isinstance(block, InstructionBlock)
            and block.repetitions() == 1
            and block.sub_instruction_execution_mode == 'sequential'
            and len(block.sub_instructions) > 1
            and all(hours(each) < inf for each in block.sub_instructions)
        ):
            continue
        found, time = [], 0.0
        for each in block.sub_instructions:
            found.append((each.name or each.describe(), time, time + hours(each)))
            time += hours(each)
        return found
    return [('ageing', 0.0, length)]


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
    if instruction.set_point is not None:
        value = instruction.set_point.to('W/m^2').magnitude
        return value + (clock.noise(2) if value else 0 * t)
    # Not controlled and no value: the sun.
    clock.notes.add(
        'The sun is a clear-sky day, dimmed by a cloud factor drawn per day.'
    )
    sun = np.clip(np.sin(np.pi * (clock.of_day - 6) / 12), 0, None) ** 1.3
    clouds = clock.rng.uniform(0.55, 1.0, int(clock.day.max()) + 1)[clock.day]
    return 1000 * sun * clouds * (1 + clock.noise(0.03))


def temperature(instruction, clock: Clock, light: np.ndarray) -> np.ndarray:
    if instruction.set_point is None:
        # Outdoors: the day, and the sun heating the cell.
        return 8 + 6 * daily(clock.of_day) + 0.025 * light + clock.noise(0.3)
    value = instruction.set_point.to('degC').magnitude
    if instruction.control:
        return value + clock.noise(0.3)
    # An ambient room, warmed a little by a lamp.
    return value + daily(clock.of_day) + 0.003 * light + clock.noise(0.2)


def relative_humidity(instruction, clock: Clock, temp: np.ndarray) -> np.ndarray:
    if instruction.set_point is not None:
        value = instruction.set_point.to('percent').magnitude
        return value + clock.noise(0.5)
    if instruction.m_root().environment == 'outdoor':
        return np.clip(70 - 1.5 * (temp - 15) + clock.noise(1), 15, 100)
    return ambient_humidity(clock)


def ambient_humidity(clock: Clock) -> np.ndarray:
    drift = 3 * np.sin(2 * np.pi * clock.t / 70)
    return 40 - 5 * daily(clock.of_day) + drift + clock.noise(0.8)


def conditions(protocol, clock: Clock, length: float) -> dict[str, np.ndarray]:
    """Irradiance, temperature and relative humidity over the run, whether monitored
    or not, since the cell ages under all of them; and `mpp`, where it is tracked.
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
    return {
        'irradiance': light,
        'temperature': temp,
        'relative_humidity': humidity,
        'mpp': tracked,
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


def electrical(values, kept, clock: Clock) -> dict[str, np.ndarray]:
    """What the load reads: the maximum power point where it is tracked, open circuit
    where it is not, and nothing in the dark."""
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


def write_jv(path: Path, kept: float) -> None:
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['voltage (V)', 'current_density (mA/cm^2)', 'direction'])
        for voltage, current, direction in jv_sweep(kept):
            writer.writerow([f'{voltage:.3f}', f'{current:.4f}', direction])


def slug(text: str) -> str:
    return re.sub(r'\W+', '_', text.lower()).strip('_')


def simulate(source: Source, index: int, output: Path) -> str:
    """Write the run of `source` into `output`; returns the protocol's entry name."""
    key, protocol, designation = source.key, source.protocol, source.designation
    length = min(RUN_LENGTH, hours(protocol))
    started = START + timedelta(days=7 * index)
    ageing_start = started + JV_LENGTH + CHANGEOVER
    clock = Clock(
        t=np.round(np.arange(0, length + SAMPLE_EVERY / 2, SAMPLE_EVERY), 6),
        hour=ageing_start.hour + ageing_start.minute / 60,
        rng=np.random.default_rng(zlib.crc32(designation.encode())),
    )
    values = conditions(protocol, clock, length)
    kept = remaining(values)
    quantities = monitored(protocol)

    columns = {'time': clock.t}
    columns.update({name: values[name] for name in CONDITIONS if name in quantities})
    if 'mpp' in quantities:
        columns.update(electrical(values, kept, clock))
    columns = {name: columns[name] for name in COLUMNS if name in columns}

    folder = output / designation
    folder.mkdir(parents=True, exist_ok=True)
    recorded = phases(protocol, length)
    number = iter(range(1, 2 * len(recorded) + 2))
    steps = [('initial J–V', 'jv', f'{next(number):02d}_jv_initial.csv', started)]
    write_jv(folder / steps[0][2], 1.0)
    begins = ageing_start
    for position, (name, start, end) in enumerate(recorded):
        last = position == len(recorded) - 1
        rows = (clock.t >= start) & ((clock.t < end) | last)
        series = {column: values[rows] for column, values in columns.items()}
        series['time'] = series['time'] - start
        suffix = '' if len(recorded) == 1 else f'_{slug(name)}'
        file = f'{next(number):02d}_stability_series{suffix}.csv'
        write_table(folder / file, series)
        steps.append((name, 'stability_series', file, begins))
        after = begins + timedelta(hours=end - start) + CHANGEOVER
        jv_name, jv_file = (
            ('final J–V', 'jv_final')
            if last
            else (f'J–V after {name}', f'jv_after{suffix}')
        )
        jv_file = f'{next(number):02d}_{jv_file}.csv'
        write_jv(folder / jv_file, float(kept[rows][-1]))
        steps.append((jv_name, 'jv', jv_file, after))
        begins = after + JV_LENGTH + CHANGEOVER

    run = {
        'institution': INSTITUTION,
        'name': f'{key if protocol.standard else protocol.name or key}, cell A',
        **source.refers,
        'standard': protocol.standard,
        'operator': OPERATOR,
        'start': started.isoformat(),
        'end': (steps[-1][3] + JV_LENGTH).isoformat(),
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
            {'name': name, 'kind': kind, 'file': file, 'start': start.isoformat()}
            for name, kind, file, start in steps
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
