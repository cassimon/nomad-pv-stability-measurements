"""Every row of ISOS Table 1, one protocol per option, as shipped (Design.md §16, §18).

Each file is compared with an expected archive **as a whole**: the loaded, normalized
protocol's `m_to_dict()` must equal it exactly, so a field written wrongly fails and so
does a field written that should not be there (§18.4). The expectations are built here
from the table in SI units, independently of how the files were written.

The files are read from the package, not from `tests/data/`: they are shipped
documentation, and a second copy would be a second thing to keep in step. Each lies in a
folder named after its `standard` (§18.1).
"""

import itertools
from pathlib import Path

import pytest
import yaml
from nomad.datamodel import EntryArchive, EntryMetadata

from nomad_pv_stability_measurements import example_uploads
from nomad_pv_stability_measurements.parsers.translate import m_def, translate
from nomad_pv_stability_measurements.parsers.units import (
    volume_ratio_of_relative_humidity,
)
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldCurrent,
    HoldIrradiance,
    HoldTemperature,
    HoldVoltage,
    HoldWaterVaporFraction,
)
from nomad_pv_stability_measurements.schema_packages.mpp_steps import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
from nomad_pv_stability_measurements.schema_packages.ramp_steps import RampTemperature
from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedSubroutineStep,
)

EXAMPLES = Path(example_uploads.__file__).parent / 'isos'
SHIPPED = sorted(
    path.relative_to(EXAMPLES).as_posix() for path in EXAMPLES.rglob('*.stability.yaml')
)
#: "Very short" (§18.3): one or two sentences of what the standard says.
NOTES_AT_MOST = 120
#: What only a design decision would mention, and so no `notes` may (§18.3).
SCHEMA_WORDS = ('`', 'schema', 'set_point', 'hold:', 'file')
ZERO_CELSIUS = 273.15


def step(cls, **fields) -> dict:
    return {'m_def': m_def(cls), **fields}


def kelvin(celsius: float):
    return pytest.approx(celsius + ZERO_CELSIUS)


# The table's cells, as the steps they are.

DARK = step(HoldIrradiance, control=True, set_point=0.0)
SOLAR_SIMULATOR = step(HoldIrradiance, control=True)
SUNLIGHT = step(HoldIrradiance, control=False)
#: "Ambient (23 ± 4 °C)" — a figure and a tolerance (§17.2).
ROOM_TEMPERATURE = step(
    HoldTemperature,
    control=True,
    set_point=kelvin(23),
    set_point_tolerance=pytest.approx(4),
)
#: Bare "Ambient" — not regulated, and nothing more.
AMBIENT_TEMPERATURE = step(HoldTemperature, control=False)
AMBIENT_HUMIDITY = step(HoldWaterVaporFraction, control=False)
HUMIDITY_MONITORED = step(HoldWaterVaporFraction, monitor=True)
HUMIDITY_MONITORED_UNCONTROLLED = step(
    HoldWaterVaporFraction, monitor=True, control=False
)
OPEN_CIRCUIT = step(VOCTracking, control=True)
LOADS = {'MPP': step(MPPTracking, control=True), 'OC': OPEN_CIRCUIT}
TEMPERATURES = {'65degC': ('65 °C', 65), '85degC': ('85 °C', 85)}
#: Every bias is measured on the device, so none has a set point (§18.2). E_g/q is no
#: option: the text recommends voltages *below* it (§18.6).
BIASES = {
    'Vmpp': ('V_MPP', HoldVoltage),
    'Voc': ('V_oc', HoldVoltage),
    'Jsc': ('J_SC', HoldCurrent),
    'minus-Voc': ('−V_oc', HoldVoltage),
    'minus-Jmpp': ('−J_MPP', HoldCurrent),
}


def held(celsius: float) -> dict:
    return step(HoldTemperature, control=True, set_point=kelvin(celsius))


def humidity(percent: float, celsius: float) -> dict:
    ratio = volume_ratio_of_relative_humidity(percent / 100, celsius + ZERO_CELSIUS)
    return step(HoldWaterVaporFraction, control=True, set_point=pytest.approx(ratio))


def bias(cls) -> dict:
    return step(cls, control=True)


def cycle(start, end) -> dict:
    """The routine of a solar-thermal cycle: linear ramps between two temperatures."""
    ramp = step(
        RampTemperature,
        control=True,
        start_point=start,
        end_point=end,
        end_of_ramp_behavior='triangle',
    )
    return step(PlannedSubroutineStep, steps=[ramp])


EXPECTED = {}


def protocol(standard, options, steps, environment='indoor'):
    """The archive one file must load to. `options` are (file-name token, label)."""
    variant = ', '.join(label for _, label in options)
    stem = '_'.join([standard, *(token for token, _ in options)])
    archive = {
        'm_def': m_def(StabilityProtocol),
        'name': f'{standard} ({variant})' if variant else standard,
        'standard': standard,
        'environment': environment,
        'steps': steps,
    }
    if variant:
        archive['standard_variant'] = variant
    path = f'{standard}/{stem}.stability.yaml'
    assert path not in EXPECTED
    EXPECTED[path] = archive


# ISOS-D — dark storage.
protocol('ISOS-D-1', [], [DARK, ROOM_TEMPERATURE, AMBIENT_HUMIDITY, OPEN_CIRCUIT])
for token, (label, celsius) in TEMPERATURES.items():
    option = [(token, label)]
    protocol('ISOS-D-2', option, [DARK, held(celsius), AMBIENT_HUMIDITY, OPEN_CIRCUIT])
    protocol(
        'ISOS-D-3',
        option,
        [DARK, held(celsius), humidity(85, celsius), OPEN_CIRCUIT],
    )

# ISOS-V — the five biases span all three rows (the merged cells G8:G10).
for b_token, (b_label, cls) in BIASES.items():
    load = bias(cls)
    protocol(
        'ISOS-V-1',
        [(b_token, b_label)],
        [DARK, ROOM_TEMPERATURE, AMBIENT_HUMIDITY, load],
    )
    for token, (label, celsius) in TEMPERATURES.items():
        options = [(token, label), (b_token, b_label)]
        protocol('ISOS-V-2', options, [DARK, held(celsius), AMBIENT_HUMIDITY, load])
        protocol(
            'ISOS-V-3', options, [DARK, held(celsius), humidity(85, celsius), load]
        )

# ISOS-L — light soaking.
for l_token, load in LOADS.items():
    protocol(
        'ISOS-L-1',
        [(l_token, l_token)],
        [SOLAR_SIMULATOR, ROOM_TEMPERATURE, AMBIENT_HUMIDITY, load],
    )
for (token, (label, celsius)), (l_token, load) in itertools.product(
    TEMPERATURES.items(), LOADS.items()
):
    protocol(
        'ISOS-L-2',
        [(token, label), (l_token, l_token)],
        [SOLAR_SIMULATOR, held(celsius), AMBIENT_HUMIDITY, load],
    )
for token, (label, celsius) in TEMPERATURES.items():
    protocol(
        'ISOS-L-3',
        [(token, label)],
        [SOLAR_SIMULATOR, held(celsius), humidity(50, celsius), LOADS['MPP']],
    )

# ISOS-O — outdoors, where nothing but the load is regulated. No site is stated.
OUTDOOR = [SUNLIGHT, AMBIENT_TEMPERATURE, AMBIENT_HUMIDITY]
for l_token, load in LOADS.items():
    for standard in ('ISOS-O-1', 'ISOS-O-2'):
        protocol(standard, [(l_token, l_token)], [*OUTDOOR, load], 'outdoor')
protocol('ISOS-O-3', [], [*OUTDOOR, LOADS['MPP']], 'outdoor')

# ISOS-LT — the one cycle the table says is linear. Only the temperature varies, so it
# alone is the routine (§16.2, Rule 2).
for l_token, load in LOADS.items():
    protocol(
        'ISOS-LT-1',
        [('linear', 'linear ramping'), (l_token, l_token)],
        [
            SOLAR_SIMULATOR,
            HUMIDITY_MONITORED_UNCONTROLLED,
            load,
            cycle(kelvin(23), kelvin(65)),
        ],
    )
    protocol(
        'ISOS-LT-2',
        [(l_token, l_token)],
        [SOLAR_SIMULATOR, HUMIDITY_MONITORED, load, cycle(kelvin(5), kelvin(65))],
    )
# Level 3, where MPP tracking is mandatory: the table's "MPP or OC" is no option (§18.6).
protocol(
    'ISOS-LT-3',
    [],
    [SOLAR_SIMULATOR, HUMIDITY_MONITORED, LOADS['MPP'], cycle(kelvin(-25), kelvin(65))],
)


def read(name: str) -> dict:
    with open(EXAMPLES / name) as file:
        return yaml.safe_load(file)


@pytest.fixture
def protocol_file(normalized, log):
    """One shipped file, translated, loaded and normalized — asserted clean on the way
    through, because a typo in an example upload is a bug in the documentation."""

    def run(name: str) -> StabilityProtocol:
        translation = translate(read(name))
        assert [(p.path, p.message) for p in translation.problems] == []
        loaded = StabilityProtocol.m_from_dict(translation.archive['data'])
        for each in loaded.steps:
            normalized(each)
        metadata = EntryMetadata(entry_name=name)
        loaded.normalize(EntryArchive(metadata=metadata, data=loaded), log)
        assert (log.errors, log.warnings) == ([], [])
        return loaded

    return run


def test_every_file_has_an_expectation_and_every_expectation_a_file():
    assert SHIPPED == sorted(EXPECTED)


@pytest.mark.parametrize('path', sorted(EXPECTED))
def test_a_shipped_protocol_is_exactly_its_row_of_the_table(path, protocol_file):
    archive = protocol_file(path).m_to_dict()
    notes = archive.pop('notes')

    assert archive == EXPECTED[path]
    # Short, and only what the standard says — never how it was transcribed (§18.3).
    assert 0 < len(notes) <= NOTES_AT_MOST
    assert not any(word in notes for word in SCHEMA_WORDS)


@pytest.mark.parametrize('name', SHIPPED)
def test_a_shipped_protocol_round_trips(name):
    # The bare format is a subset of the authored one, so translating it again is a
    # no-op — which is what NOMAD does every time it writes an entry back (§13.1a).
    bare = translate(read(name)).archive
    again = translate(bare)

    assert (again.archive, again.problems) == (bare, [])
