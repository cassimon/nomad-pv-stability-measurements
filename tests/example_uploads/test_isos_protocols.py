"""Every ISOS protocol the plugin ships, one variant per option (Design.md §16, §18, §20–§22,
§24).

Each variant is compared with an expected archive **as a whole**: the loaded, normalized
protocol's `m_to_dict()` must equal it exactly, so a field written wrongly fails and so
does a field written that should not be there (§18.4). The expectations are built here
from Khenkin et al. 2020 in SI units, independently of how the files were written.

The files are read from the package, not from `tests/data/`: they are shipped
documentation, and a second copy would be a second thing to keep in step. Each file is
named after its `standard`, and each variant after its file and its choices (§24).
"""

import itertools
import time
from pathlib import Path

import pytest
from nomad.datamodel import EntryArchive, EntryMetadata

from nomad_pv_stability_measurements import example_uploads
from nomad_pv_stability_measurements.parsers.options import expand
from nomad_pv_stability_measurements.parsers.parser import read, stem
from nomad_pv_stability_measurements.parsers.translate import m_def, translate
from nomad_pv_stability_measurements.schema_packages.general import (
    IndefiniteRepeatingBlock,
)
from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldCurrent,
    HoldIrradiance,
    HoldRelativeHumidity,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
from nomad_pv_stability_measurements.schema_packages.ramp_instructions import (
    RampTemperature,
)

EXAMPLES = Path(example_uploads.__file__).parent / 'isos'
#: "Very short" (§18.3): one or two sentences of what the standard says.
NOTES_AT_MOST = 120
#: What only a design decision would mention, and so no `notes` may (§18.3).
SCHEMA_WORDS = ('`', 'schema', 'set_point', 'hold:', 'file')
ZERO_CELSIUS = 273.15
HOUR = 3600
MINUTE = 60
#: s: every shipped variant's timeline together, about 0.5 s today. The simulation this
#: replaces took minutes (Design.md §29); ten times today's cost still catches that.
TIMELINES_WITHIN = 5.0


def instruction(cls, **fields) -> dict:
    return {'m_def': m_def(cls), **fields}


def kelvin(celsius: float):
    return pytest.approx(celsius + ZERO_CELSIUS)


# The table's cells, as the instructions they are — read with the paper's text (§18.7, §20).

DARK = instruction(HoldIrradiance, control=True, set_point=0.0)
#: What is measured is monitored, controlled or not: "even if a parameter is not controlled
#: … it is still important to monitor and report the parameters listed in Table 3" (p.43).
#: Light: "the exact irradiance … should be reported" (p.43), checked "with a reference
#: cell" (p.44). Darkness, open circuit and a fixed bias are conditions to report, not
#: readings (Table 3).
SOLAR_SIMULATOR = instruction(HoldIrradiance, control=True, monitor=True)
#: "Ideally, light sources with an irradiance of 800–1000 W m–² … should be applied"
#: (p.43). A recommendation is a variant of its own (§21.1): every solar simulator comes
#: without it and with it, the latter's option last. A range, never a target (§22).
LIGHTS = {
    None: SOLAR_SIMULATOR,
    ('800-1000Wm2', 'recommended 800–1000 W/m²'): instruction(
        HoldBetweenIrradiance,
        control=True,
        monitor=True,
        lower_bound=pytest.approx(800),
        upper_bound=pytest.approx(1000),
    ),
}
#: Table 3 has an outdoor test report the sunlight irradiance, so it is monitored.
SUNLIGHT = instruction(HoldIrradiance, control=False, monitor=True)
#: "Ambient (23 ± 4 °C)": "monitored but not explicitly controlled (room temperature in
#: the laboratory is assumed to be 23±4 °C)" (p.36) — the figure, not regulated.
ROOM_TEMPERATURE = instruction(
    HoldTemperature,
    control=False,
    monitor=True,
    set_point=kelvin(23),
    set_point_tolerance=pytest.approx(4),
)
#: Bare "Ambient": "even if a parameter is not controlled … it is still important to
#: monitor and report" it (p.43). Humidity is stated as RH throughout (§20.6).
AMBIENT_TEMPERATURE = instruction(HoldTemperature, control=False, monitor=True)
AMBIENT_HUMIDITY = instruction(HoldRelativeHumidity, control=False, monitor=True)
#: Monitored, and controlled only above 40 °C: the condition stays in `notes` (§20.8).
HUMIDITY_MONITORED = instruction(HoldRelativeHumidity, monitor=True)
OPEN_CIRCUIT = instruction(VOCTracking, control=True)
#: MPP tracking "holds the device at its normal operating voltage and measures the output"
#: (p.43).
MPP = ('MPP', instruction(MPPTracking, control=True, monitor=True))
#: Levels 1 and 2 under light: "options of exposure under open-circuit condition or using a
#: fixed voltage bias near the MPP (instead of active MPP tracking)" (p.37).
LOWER_LEVEL_LOADS = {
    'MPP': MPP,
    'OC': ('OC', OPEN_CIRCUIT),
    'Vfixed': (
        'fixed voltage near MPP',
        instruction(HoldVoltage, control=True, reference_point='near V_MPP'),
    ),
}
TEMPERATURES = {'65degC': ('65 °C', 65), '85degC': ('85 °C', 85)}
#: Every bias is taken from the device, and says which point in `reference_point`
#: (§20.3). E_g/q is no option: the text recommends voltages *below* it (§18.6).
BIASES = {
    'Vmpp': ('V_MPP', HoldVoltage, 'V_MPP'),
    'Voc': ('V_oc', HoldVoltage, 'V_oc'),
    'Jsc': ('J_SC', HoldCurrent, 'J_SC'),
    'minus-Voc': ('−V_oc', HoldVoltage, '-V_oc'),
    'minus-Jmpp': ('−J_MPP', HoldCurrent, '-J_MPP'),
}
#: "cycle periods of 2, 8, or 24 h and duty cycles (light:dark) of 1:1 or 1:2" (p.39):
#: (period, duty) → light and dark, in seconds. "8 h light and 16 h dark" is the text's.
LIGHT_CYCLES = {
    ('2h', '2 h', '1-1', '1:1'): (1 * HOUR, 1 * HOUR),
    ('2h', '2 h', '1-2', '1:2'): (40 * MINUTE, 80 * MINUTE),
    ('8h', '8 h', '1-1', '1:1'): (4 * HOUR, 4 * HOUR),
    ('8h', '8 h', '1-2', '1:2'): (160 * MINUTE, 320 * MINUTE),
    ('24h', '24 h', '1-1', '1:1'): (12 * HOUR, 12 * HOUR),
    ('24h', '24 h', '1-2', '1:2'): (8 * HOUR, 16 * HOUR),
}


def held(celsius: float) -> dict:
    """A held temperature, measured: Table 3 asks for the "temperature sensor type"."""
    return instruction(
        HoldTemperature, control=True, monitor=True, set_point=kelvin(celsius)
    )


def humidity(percent: float) -> dict:
    """A relative humidity, stored as the fraction itself — no temperature (§20.6)."""
    return instruction(
        HoldRelativeHumidity,
        control=True,
        monitor=True,
        set_point=pytest.approx(percent / 100),
    )


def bias(cls, point: str) -> dict:
    return instruction(cls, control=True, reference_point=point)


def ramping(start, end) -> dict:
    """A routine of linear ramps between two temperatures, up and down (§15.14)."""
    ramp = instruction(
        RampTemperature,
        control=True,
        monitor=True,
        start_point=start,
        end_point=end,
        end_of_ramp_behavior='triangle',
    )
    return instruction(IndefiniteRepeatingBlock, sub_instructions=[ramp])


def cycling(start, end) -> dict:
    """A routine cycling between two temperatures by a path not stated: a ramp that
    cycles (§21.2)."""
    cycle = instruction(
        RampTemperature,
        control=True,
        monitor=True,
        start_point=start,
        end_point=end,
        end_of_ramp_behavior='cycle',
    )
    return instruction(IndefiniteRepeatingBlock, sub_instructions=[cycle])


def light_dark(light: float, dark: float, lit: dict) -> dict:
    """A routine of light and dark, repeated indefinitely: until the protocol is stopped
    (§20.1, §23)."""
    return instruction(
        IndefiniteRepeatingBlock,
        sub_instructions=[
            {**lit, 'duration': pytest.approx(light)},
            {**DARK, 'duration': pytest.approx(dark)},
        ],
    )


EXPECTED = {}


def protocol(standard, options, instructions, environment='indoor'):
    """The archive one variant must load to. `options` are (token, label) in the order the
    file writes them, or `None` for the alternative that adds nothing to its name."""
    options = [option for option in options if option]
    variant = ', '.join(label for _, label in options)
    archive = {
        'm_def': m_def(StabilityProtocol),
        'name': f'{standard} ({variant})' if variant else standard,
        'standard': standard,
        # The last digit of the designation, derived when the file writes none (§20.7).
        'standard_level': int(standard.rsplit('-', 1)[1].rstrip('I')),
        'environment': environment,
        'instructions': instructions,
    }
    if variant:
        archive['standard_variant'] = variant
    # A variant is known by its name (§24).
    assert archive['name'] not in EXPECTED
    EXPECTED[archive['name']] = archive


# ISOS-D — dark storage.
protocol('ISOS-D-1', [], [DARK, ROOM_TEMPERATURE, AMBIENT_HUMIDITY, OPEN_CIRCUIT])
for token, (label, celsius) in TEMPERATURES.items():
    option = [(token, label)]
    protocol('ISOS-D-2', option, [DARK, held(celsius), AMBIENT_HUMIDITY, OPEN_CIRCUIT])
    # "humidity (set at 85% RH) when devices are kept at … (65 or 85 °C)" (p.37).
    protocol('ISOS-D-3', option, [DARK, held(celsius), humidity(85), OPEN_CIRCUIT])

# ISOS-V — the biases span all three rows (the merged cells G8:G10).
for b_token, (b_label, cls, point) in BIASES.items():
    load = bias(cls, point)
    protocol(
        'ISOS-V-1',
        [(b_token, b_label)],
        [DARK, ROOM_TEMPERATURE, AMBIENT_HUMIDITY, load],
    )
    for token, (label, celsius) in TEMPERATURES.items():
        options = [(token, label), (b_token, b_label)]
        protocol('ISOS-V-2', options, [DARK, held(celsius), AMBIENT_HUMIDITY, load])
        protocol('ISOS-V-3', options, [DARK, held(celsius), humidity(85), load])

# ISOS-L — light soaking.
for light, simulator in LIGHTS.items():
    for l_token, (l_label, load) in LOWER_LEVEL_LOADS.items():
        protocol(
            'ISOS-L-1',
            [light, (l_token, l_label)],
            [simulator, ROOM_TEMPERATURE, AMBIENT_HUMIDITY, load],
        )
    for (token, (label, celsius)), (l_token, (l_label, load)) in itertools.product(
        TEMPERATURES.items(), LOWER_LEVEL_LOADS.items()
    ):
        protocol(
            'ISOS-L-2',
            [light, (token, label), (l_token, l_label)],
            [simulator, held(celsius), AMBIENT_HUMIDITY, load],
        )
    for token, (label, celsius) in TEMPERATURES.items():
        protocol(
            'ISOS-L-3',
            [light, (token, label)],
            [simulator, held(celsius), humidity(50), MPP[1]],
        )

# ISOS-O — outdoors, where nothing but the load is regulated, and the weather is monitored.
# No site is stated: it is reported, not prescribed (Table 3).
OUTDOOR = [SUNLIGHT, AMBIENT_TEMPERATURE, AMBIENT_HUMIDITY]
for l_token, (l_label, load) in LOWER_LEVEL_LOADS.items():
    for standard in ('ISOS-O-1', 'ISOS-O-2'):
        protocol(standard, [(l_token, l_label)], [*OUTDOOR, load], 'outdoor')
# Level 3: "ISOS-O-3 requires both in situ MPP tracking under natural sunlight …" (p.37).
protocol('ISOS-O-3', [], [*OUTDOOR, MPP[1]], 'outdoor')

# ISOS-T — thermal cycling in the dark, the path left to ref. 11 (§21.2).
for token, (label, celsius) in TEMPERATURES.items():
    for standard in ('ISOS-T-1', 'ISOS-T-2'):
        protocol(
            standard,
            [(token, label)],
            [
                DARK,
                AMBIENT_HUMIDITY,
                OPEN_CIRCUIT,
                cycling(kelvin(23), kelvin(celsius)),
            ],
        )
# "< 55%", controlled only above 40 °C (footnote b): monitored, the condition in `notes`.
protocol(
    'ISOS-T-3',
    [],
    [DARK, HUMIDITY_MONITORED, OPEN_CIRCUIT, cycling(kelvin(-40), kelvin(85))],
)

# ISOS-LC — the light is what varies, so it alone is the routine (§16.2, Rule 2). LC-3's
# humidity is an open question and not written (OPEN_QUESTIONS.md).
for light, simulator in LIGHTS.items():
    for (p_token, p_label, d_token, d_label), (on, off) in LIGHT_CYCLES.items():
        cycle_options = [(p_token, p_label), (d_token, d_label)]
        routine = light_dark(on, off, simulator)
        for l_token, (l_label, load) in LOWER_LEVEL_LOADS.items():
            protocol(
                'ISOS-LC-1',
                [(l_token, l_label), *cycle_options, light],
                [ROOM_TEMPERATURE, AMBIENT_HUMIDITY, load, routine],
            )
            for token, (label, celsius) in TEMPERATURES.items():
                protocol(
                    'ISOS-LC-2',
                    [(token, label), (l_token, l_label), *cycle_options, light],
                    [held(celsius), AMBIENT_HUMIDITY, load, routine],
                )

# ISOS-LT — only the temperature varies, so it alone is the routine (§16.2, Rule 2).
for light, simulator in LIGHTS.items():
    for l_token, (l_label, load) in LOWER_LEVEL_LOADS.items():
        # "Linear or step ramping": linear is a triangle, a step's path is not stated.
        for s_token, s_label, routine in (
            ('linear', 'linear ramping', ramping(kelvin(23), kelvin(65))),
            ('step', 'step ramping', cycling(kelvin(23), kelvin(65))),
        ):
            protocol(
                'ISOS-LT-1',
                [light, (l_token, l_label), (s_token, s_label)],
                [simulator, AMBIENT_HUMIDITY, load, routine],
            )
        protocol(
            'ISOS-LT-2',
            [light, (l_token, l_label)],
            [simulator, HUMIDITY_MONITORED, load, ramping(kelvin(5), kelvin(65))],
        )
    # Level 3, where MPP tracking is mandatory: the table's "MPP or OC" is no option.
    protocol(
        'ISOS-LT-3',
        [light],
        [simulator, HUMIDITY_MONITORED, MPP[1], ramping(kelvin(-25), kelvin(65))],
    )


def shipped() -> dict:
    """Every variant of every shipped file, by its key."""
    variants = {}
    for path in sorted(EXAMPLES.glob('*.stability.yaml')):
        expansion = expand(read(path))
        assert [(p.path, p.message) for p in expansion.problems] == []
        for variant in expansion.variants:
            variants[variant.key(stem(path))] = variant.document
    return variants


SHIPPED = shipped()


@pytest.fixture
def protocol_file(normalized, log):
    """One shipped variant, translated, loaded and normalized — asserted clean on the way
    through, because a typo in an example upload is a bug in the documentation."""

    def run(key: str) -> StabilityProtocol:
        translation = translate(SHIPPED[key])
        assert [(p.path, p.message) for p in translation.problems] == []
        loaded = StabilityProtocol.m_from_dict(translation.archive['data'])
        for each in loaded.instructions:
            normalized(each)
        metadata = EntryMetadata(entry_name=key)
        loaded.normalize(EntryArchive(metadata=metadata, data=loaded), log)
        assert (log.errors, log.warnings) == ([], [])
        return loaded

    return run


#: What is derived for display, from what the rows below already compare: the
#: instructions' `label`s and the protocol's timeline. Neither is part of the standard.
DISPLAY = {'label', 'figures'}


def without_display(value):
    """An archive without what is derived for display (`DISPLAY`)."""
    if isinstance(value, dict):
        return {k: without_display(v) for k, v in value.items() if k not in DISPLAY}
    if isinstance(value, list):
        return [without_display(each) for each in value]
    return value


def test_every_variant_has_an_expectation_and_every_expectation_a_variant():
    assert sorted(SHIPPED) == sorted(EXPECTED)


@pytest.mark.parametrize('key', sorted(EXPECTED))
def test_a_shipped_protocol_is_exactly_its_row_of_the_table(key, protocol_file):
    archive = without_display(protocol_file(key).m_to_dict())
    notes = archive.pop('notes')

    assert archive == EXPECTED[key]
    # Short, and only what the standard says — never how it was transcribed (§18.3).
    assert 0 < len(notes) <= NOTES_AT_MOST
    assert not any(word in notes for word in SCHEMA_WORDS)


def test_every_shipped_protocol_draws_its_timeline_quickly(protocol_file):
    protocols = [protocol_file(key) for key in sorted(SHIPPED)]

    started = time.perf_counter()
    figures = [protocol.figures_for_plotting() for protocol in protocols]
    took = time.perf_counter() - started

    assert all(figures)  # every one has something to show
    assert took < TIMELINES_WITHIN
