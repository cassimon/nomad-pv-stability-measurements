"""Writes `simulated_data/`: one simulated run of every ISOS protocol.

Run it from anywhere with the plugin's Python:

    python -m nomad_pv_stability_measurements.example_uploads.simulate_runs

For each file in `isos/` it takes the first variant (the first alternative of every
option) and writes a folder named after the standard:

    ISOS-L-2/
      ISOS-L-2.run.yaml      who ran what, when, on which samples, and the steps
      01_jv_initial.csv      J–V sweep of the fresh device, reverse then forward
      02_ageing.csv          every monitored quantity in one table, one row per sample
      03_jv_final.csv        J–V sweep after the ageing

The ageing table has a `time` column and one column per quantity the protocol
monitors, the unit in the header. What is simulated follows what the protocol states:
held values with noise, the band a solar simulator is kept in, light-dark cycles,
temperature cycles, an ambient room and an outdoor day. What the protocol leaves open
is assumed and written into the run's `notes`.

Nothing here is measured. The output is fixed by a seed per standard, so running the
script again reproduces the same files.
"""

import csv
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import yaml

from nomad_pv_stability_measurements.parsers.options import expand
from nomad_pv_stability_measurements.parsers.parser import stem
from nomad_pv_stability_measurements.parsers.translate import translate
from nomad_pv_stability_measurements.schema_packages.base_instructions import (
    MonitorControlInstruction,
)
from nomad_pv_stability_measurements.schema_packages.general import RepeatingBlock
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol

HERE = Path(__file__).parent
PROTOCOLS = HERE / 'isos'
OUTPUT = HERE / 'simulated_data'

#: Where the protocols are in the example upload, which copies `isos/` beside the runs.
PROTOCOLS_IN_UPLOAD = 'isos'

RUN_LENGTH = 168.0  # h: one week
SAMPLE_EVERY = 10 / 60  # h
START = datetime(2026, 3, 2, 9, 0, tzinfo=timezone(timedelta(hours=1)))
#: Between a J–V sweep and the ageing, either way round.
CHANGEOVER = timedelta(minutes=10)
JV_LENGTH = timedelta(minutes=2)

#: A temperature cycle whose rate the protocol does not state is assumed to take this.
CYCLE_PERIOD = 6.0  # h
#: A stepped cycle (`cycle`) spends this of each half period moving between its ends.
STEP_TRANSITION = 1.0  # h

OPERATOR = 'A. Researcher'
SIMULATED = 'Simulated data: nothing was measured.'

#: Column name and unit of each quantity in the ageing table, in the order written.
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


def first_variant(path: Path) -> tuple[str, StabilityProtocol]:
    """The first variant of the protocol file `path`, by its entry name and loaded."""
    expansion = expand(yaml.safe_load(path.read_text(encoding='utf-8')))
    variant = expansion.variants[0]
    key = variant.key(stem(str(path))) if expansion.has_options else stem(str(path))
    data = translate(variant.document).archive['data']
    return key, StabilityProtocol.m_from_dict(data)


def quantity_of(instruction) -> str | None:
    """Which column of the ageing table an instruction is about, if any."""
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


def schedules(protocol) -> dict[str, list[tuple[float, object]]]:
    """Every quantity the protocol sets, as `(hours, instruction)` pieces repeated one
    after another; a single piece of `inf` hours for what holds throughout."""
    found = {}
    for instruction in protocol.instructions:
        if isinstance(instruction, RepeatingBlock):
            for sub in instruction.sub_instructions:
                duration = sub.duration
                hours = (
                    duration.value.to('hour').magnitude
                    if duration is not None and duration.kind == 'fixed'
                    else np.inf
                )
                found.setdefault(quantity_of(sub), []).append((hours, sub))
        elif isinstance(instruction, MonitorControlInstruction):
            found.setdefault(quantity_of(instruction), []).append((np.inf, instruction))
    found.pop(None, None)
    return found


def monitored(protocol) -> set[str]:
    return {
        quantity_of(each)
        for each in protocol.m_all_contents()
        if isinstance(each, MonitorControlInstruction) and each.monitor
    } - {None}


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


def active_piece(t: np.ndarray, pieces) -> list[tuple[np.ndarray, object]]:
    """For pieces repeated one after another, where each one is in force."""
    if len(pieces) == 1:
        return [(np.ones_like(t, dtype=bool), pieces[0][1])]
    period = sum(hours for hours, _ in pieces)
    phase = t % period
    masks, start = [], 0.0
    for hours, instruction in pieces:
        masks.append(((phase >= start) & (phase < start + hours), instruction))
        start += hours
    return masks


def triangle(t: np.ndarray, low: float, high: float) -> np.ndarray:
    phase = (t % CYCLE_PERIOD) / CYCLE_PERIOD
    return low + (high - low) * (1 - np.abs(2 * phase - 1))


def stepped(t: np.ndarray, low: float, high: float) -> np.ndarray:
    """Up, dwell, down, dwell: the ends stated, the path between them assumed."""
    half = CYCLE_PERIOD / 2
    phase = t % CYCLE_PERIOD
    rising = np.clip(phase / STEP_TRANSITION, 0, 1)
    falling = np.clip((phase - half) / STEP_TRANSITION, 0, 1)
    return low + (high - low) * (rising - falling)


def irradiance(instruction, clock: Clock) -> np.ndarray:
    t = clock.t
    kind = type(instruction).__name__
    if kind == 'HoldBetweenIrradiance':
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
    kind = type(instruction).__name__
    if kind == 'RampTemperature':
        low = instruction.start_point.to('degC').magnitude
        high = instruction.end_point.to('degC').magnitude
        clock.notes.add(
            f'The protocol states no rate for the temperature cycle: one cycle is '
            f'assumed to take {CYCLE_PERIOD:g} h.'
        )
        shape = stepped if instruction.end_of_ramp_behavior == 'cycle' else triangle
        return shape(clock.t, low, high) + clock.noise(0.3)
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
    if _outdoor(instruction):
        return np.clip(70 - 1.5 * (temp - 15) + clock.noise(1), 15, 100)
    drift = 3 * np.sin(2 * np.pi * clock.t / 70)
    return 40 - 5 * daily(clock.of_day) + drift + clock.noise(0.8)


def _outdoor(instruction) -> bool:
    protocol = instruction.m_root()
    return getattr(protocol, 'environment', None) == 'outdoor'


def conditions(protocol, clock: Clock) -> dict[str, np.ndarray]:
    """Irradiance, temperature and relative humidity over the run, whether monitored
    or not: the cell ages under all of them."""
    t = clock.t
    found = schedules(protocol)

    def over_time(quantity, simulate, default):
        values = np.full(t.size, default, dtype=float)
        for mask, instruction in active_piece(t, found.get(quantity, [])):
            values[mask] = simulate(instruction)[mask]
        return values

    light = over_time('irradiance', lambda each: irradiance(each, clock), 0.0)
    temp = over_time('temperature', lambda each: temperature(each, clock, light), 23.0)
    humidity = over_time(
        'relative_humidity', lambda each: relative_humidity(each, clock, temp), 40.0
    )
    return {'irradiance': light, 'temperature': temp, 'relative_humidity': humidity}


# --- Simulating the cell ---------------------------------------------------------------


def remaining(values: dict[str, np.ndarray]) -> np.ndarray:
    """The fraction of its efficiency the cell keeps over time: a burn-in, then a
    steady loss, faster when hotter, lit and humid."""
    kelvin = values['temperature'] + 273.15
    heat = np.exp(ACTIVATION / BOLTZMANN * (1 / 298.15 - 1 / kelvin))
    light = 0.2 + 0.8 * values['irradiance'] / 1000
    damp = 1 + values['relative_humidity'] / 100
    stress = np.cumsum(heat * light * damp * SAMPLE_EVERY)
    return np.clip(1 - 0.04 * (1 - np.exp(-stress / 20)) - 0.0003 * stress, 0, 1)


def at_mpp(values, kept, clock: Clock) -> dict[str, np.ndarray]:
    """What an MPP tracker reads; nothing in the dark."""
    light = values['irradiance']
    lit = light > 1
    suns = np.where(lit, light, 1000) / 1000
    heat = 1 - 0.002 * (values['temperature'] - 25)
    power = EFFICIENCY * kept * heat * light / 10  # W/m^2 → mW/cm^2
    voltage = 0.95 * kept**0.3 * (1 + 0.026 * np.log(suns)) * heat
    voltage = np.where(lit, voltage + clock.noise(0.002), 0)
    power = np.where(lit, power * (1 + clock.noise(0.005)), 0)
    current = np.divide(power, voltage, out=np.zeros_like(power), where=lit)
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
    found = schedules(protocol)
    names = []
    if protocol.environment == 'outdoor':
        names += ['outdoor test rack', 'pyranometer']
    elif 'irradiance' in quantities:
        names.append('solar simulator')
    held = [each for _, each in found.get('temperature', [])]
    if any(type(each).__name__ == 'RampTemperature' for each in held):
        names.append('thermal cycling chamber')
    elif any(each.control for each in held):
        humid = any(each.control for _, each in found.get('relative_humidity', []))
        names.append('climate chamber' if humid else 'oven')
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


def simulate(path: Path, index: int) -> str:
    """Write the run of the first variant of the protocol file `path`; returns the
    variant's entry name."""
    key, protocol = first_variant(path)
    designation = protocol.standard
    started = START + timedelta(days=7 * index)
    ageing_start = started + JV_LENGTH + CHANGEOVER
    clock = Clock(
        t=np.round(np.arange(0, RUN_LENGTH + SAMPLE_EVERY / 2, SAMPLE_EVERY), 6),
        hour=ageing_start.hour + ageing_start.minute / 60,
        rng=np.random.default_rng(zlib.crc32(designation.encode())),
    )
    values = conditions(protocol, clock)
    kept = remaining(values)
    quantities = monitored(protocol)

    columns = {'time': clock.t}
    columns.update({name: values[name] for name in values if name in quantities})
    if 'mpp' in quantities:
        columns.update(at_mpp(values, kept, clock))
    columns = {name: columns[name] for name in COLUMNS if name in columns}

    folder = OUTPUT / designation
    folder.mkdir(parents=True, exist_ok=True)
    final_start = ageing_start + timedelta(hours=RUN_LENGTH) + CHANGEOVER
    steps = [
        ('initial J–V', 'jv', '01_jv_initial.csv', started),
        ('ageing', 'time_series', '02_ageing.csv', ageing_start),
        ('final J–V', 'jv', '03_jv_final.csv', final_start),
    ]
    write_jv(folder / steps[0][2], 1.0)
    write_table(folder / steps[1][2], columns)
    write_jv(folder / steps[2][2], float(kept[-1]))

    run = {
        'run': {
            'name': f'{key}, cell A',
            'protocol': f'{PROTOCOLS_IN_UPLOAD}/{path.name}',
            'variant': key,
            'standard': designation,
            'operator': OPERATOR,
            'start': started.isoformat(),
            'end': (final_start + JV_LENGTH).isoformat(),
            'location': 'Berlin, rooftop test site'
            if protocol.environment == 'outdoor'
            else 'Berlin, lab 2.14',
            'samples': [{'name': 'cell A', 'lab_id': f'SIM-{designation}-A'}],
            'instruments': instruments(protocol, quantities),
            'notes': ' '.join([SIMULATED, *sorted(clock.notes)]),
        },
        'steps': [
            {'name': name, 'kind': kind, 'file': file, 'start': start.isoformat()}
            for name, kind, file, start in steps
        ],
    }
    (folder / f'{designation}.run.yaml').write_text(
        yaml.safe_dump(run, sort_keys=False, allow_unicode=True, width=88),
        encoding='utf-8',
    )
    return key


def main() -> None:
    for index, path in enumerate(sorted(PROTOCOLS.glob('*.stability.yaml'))):
        print(simulate(path, index))


if __name__ == '__main__':
    main()
