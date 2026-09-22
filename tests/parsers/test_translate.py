"""The `.stability.yaml` format: authored dict in, bare archive and problems out
(Design.md §13.4, §15.2, §17, §20.6, §22, §23)."""

import os

import pytest
import yaml

from nomad_pv_stability_measurements.parsers.translate import (
    m_def,
    translate,
    translate_section,
)
from nomad_pv_stability_measurements.schema_packages.general import (
    CountingRepeatingBlock,
    IndefiniteRepeatingBlock,
    InstructionBlock,
    TimedRepeatingBlock,
)
from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBelowRelativeHumidity,
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    BalanceGas,
    HoldAbsoluteHumidity,
    HoldBendRadius,
    HoldCurrent,
    HoldIrradiance,
    HoldOxygenFraction,
    HoldRelativeHumidity,
    HoldResistance,
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

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
approx = pytest.approx


def read(name: str) -> dict:
    with open(os.path.join(DATA_DIR, name)) as file:
        return yaml.safe_load(file)


def entry(cls, **fields) -> dict:
    return {'m_def': m_def(cls), **fields}


#: What a protocol's own instruction lasts where it writes no duration.
WHOLE_BLOCK = {'kind': 'whole_block'}
HOUR = {'kind': 'fixed', 'value': 3600.0}


def instructions(*authored):
    """Authored instructions, read the way a protocol reads its own."""
    return translate_section({'instructions': list(authored)}, StabilityProtocol)


def read_as(translation) -> list[dict]:
    """The instructions read, without the duration a setting is given where it writes
    none: the tests using it are about something else."""
    return [
        {key: value for key, value in each.items() if value != WHOLE_BLOCK}
        for each in translation.archive['instructions']
    ]


def only(translation) -> dict:
    """The one instruction a translation without problems produced."""
    assert translation.problems == []
    [instruction] = read_as(translation)
    return instruction


# An instruction: a channel or variable names the class, a value becomes its field.


@pytest.mark.parametrize(
    ('authored', 'expected'),
    [
        (
            {'channel': 'temperature', 'hold': '65 °C'},
            entry(HoldTemperature, control=True, set_point=approx(338.15)),
        ),
        (
            {'channel': 'electrical_load', 'voltage': '0.8 V'},
            entry(HoldVoltage, control=True, set_point=0.8),
        ),
        (
            {'channel': 'electrical_load', 'variable': 'current', 'hold': '5 mA'},
            entry(HoldCurrent, control=True, set_point=approx(0.005)),
        ),
        (
            {'channel': 'mechanical', 'bend_radius': '2 m', 'duration': '1 h'},
            entry(HoldBendRadius, control=True, set_point=2.0, duration=HOUR),
        ),
        (
            {'channel': 'temperature', 'monitor': True, 'control': False},
            entry(HoldTemperature, monitor=True, control=False),
        ),
    ],
)
def test_a_channel_and_a_value_become_one_instruction(authored, expected):
    assert only(instructions(authored)) == expected


def test_a_channel_logged_as_a_whole_is_one_instruction_per_variable():
    translation = instructions({'channel': 'electrical_load', 'monitor': True})

    assert translation.problems == []
    assert read_as(translation) == [
        entry(cls, monitor=True) for cls in (HoldVoltage, HoldCurrent, HoldResistance)
    ]


@pytest.mark.parametrize(
    ('authored', 'expected'),
    [
        # A word the standard defines is written as its numbers, tolerance included.
        (
            {'channel': 'temperature', 'hold': 'RT'},
            entry(
                HoldTemperature,
                control=True,
                set_point=approx(296.15),
                set_point_tolerance=approx(4),
            ),
        ),
        (
            {'channel': 'irradiation', 'hold': 'dark'},
            entry(HoldIrradiance, control=True, set_point=0.0),
        ),
        (
            {'channel': 'temperature', 'hold': '85 °C', 'hold_tolerance': '2 K'},
            entry(
                HoldTemperature,
                control=True,
                set_point=approx(358.15),
                set_point_tolerance=approx(2),
            ),
        ),
    ],
)
def test_named_values_and_tolerances(authored, expected):
    assert only(instructions(authored)) == expected


@pytest.mark.parametrize(
    ('authored', 'expected'),
    [
        (
            {'channel': 'electrical_load', 'hold': 'mpp'},
            entry(MPPTracking, control=True),
        ),
        (
            {'channel': 'electrical_load', 'hold': 'open_circuit'},
            entry(VOCTracking, control=True),
        ),
        (
            {'channel': 'atmosphere', 'balance_gas': 'N2'},
            entry(BalanceGas, gas='N2', control=True),
        ),
    ],
)
def test_a_point_the_cell_decides_or_a_gas_is_named_not_given_a_number(
    authored, expected
):
    assert only(instructions(authored)) == expected


@pytest.mark.parametrize(
    ('authored', 'expected'),
    [
        (
            {
                'channel': 'temperature',
                'ramp': {'from': 'RT', 'to': '65 °C'},
                'end_of_ramp_behavior': 'cycle',
            },
            entry(
                RampTemperature,
                control=True,
                start_point=approx(296.15),
                end_point=approx(338.15),
                end_of_ramp_behavior='cycle',
            ),
        ),
        (
            {
                'channel': 'atmosphere',
                'variable': 'relative_humidity',
                'hold_below': '55 %',
            },
            entry(HoldBelowRelativeHumidity, control=True, upper_bound=approx(0.55)),
        ),
        (
            {
                'channel': 'irradiation',
                'hold_between': {'lower': '800 W/m^2', 'upper': '1 sun'},
            },
            entry(
                HoldBetweenIrradiance,
                control=True,
                lower_bound=approx(800),
                upper_bound=approx(1000),
            ),
        ),
    ],
)
def test_ramp_hold_below_and_hold_between_choose_their_kind(authored, expected):
    assert only(instructions(authored)) == expected


@pytest.mark.parametrize(
    ('authored', 'expected'),
    [
        (
            {'channel': 'atmosphere', 'relative_humidity': '85 %RH'},
            entry(HoldRelativeHumidity, control=True, set_point=approx(0.85)),
        ),
        # The water as a volume ratio, from a relative humidity and its temperature.
        (
            {
                'channel': 'atmosphere',
                'absolute_humidity': {'rh': '85 %', 'at': '65 °C'},
            },
            entry(
                HoldAbsoluteHumidity, control=True, set_point=approx(0.2109, rel=1e-3)
            ),
        ),
        # The former key of the absolute humidity.
        (
            {'channel': 'atmosphere', 'water_vapor': '500 ppm'},
            entry(HoldAbsoluteHumidity, control=True, set_point=approx(5e-4)),
        ),
    ],
)
def test_humidity_is_relative_or_absolute(authored, expected):
    assert only(instructions(authored)) == expected


# Blocks and repetition (§23).


@pytest.mark.parametrize(
    ('authored', 'expected'),
    [
        ({}, entry(IndefiniteRepeatingBlock)),  # left out: indefinitely
        ({'repeat': 'indefinitely'}, entry(IndefiniteRepeatingBlock)),
        ({'repeat': 5}, entry(CountingRepeatingBlock, repeat_n=5)),
        ({'repeat_for': '12 h'}, entry(TimedRepeatingBlock, repeat_duration=43200.0)),
        (
            {'mode': 'parallel'},
            entry(IndefiniteRepeatingBlock, sub_instruction_execution_mode='parallel'),
        ),
    ],
)
def test_how_a_block_repeats_and_runs(authored, expected):
    temperature = {'channel': 'temperature', 'duration': '1 h'}
    translation = instructions({**authored, 'instructions': [temperature]})

    assert only(translation) == {
        **expected,
        'sub_instructions': [entry(HoldTemperature, duration=HOUR)],
    }


@pytest.mark.parametrize(
    ('authored', 'path', 'reported'),
    [
        ({'repeat': 'until_end_of_protocol'}, 'repeat', '`repeat: indefinitely`'),
        ({'repeat': 'n_times'}, 'repeat', '`repeat: 5`'),
        ({'repeat': 'often'}, 'repeat', 'a number of times'),
        # Only the protocol, or a timed block, stops instructions.
        (
            {'duration': '1 h'},
            'duration',
            "a block's duration follows from its instructions",
        ),
        ({'repeat_for': '1 h', 'repeat': 3}, 'repeat', 'stopped by its `repeat_for`'),
        (
            {'m_def': m_def(InstructionBlock), 'repeat': 3},
            'repeat',
            'runs its instructions once',
        ),
        (
            {'m_def': m_def(CountingRepeatingBlock), 'repeat': 'indefinitely'},
            'repeat',
            'write a number of times',
        ),
    ],
)
def test_what_a_block_cannot_say_is_reported(authored, path, reported):
    translation = instructions(
        {**authored, 'instructions': [{'channel': 'temperature', 'duration': '1 h'}]}
    )

    [problem] = translation.problems
    assert problem.path == f'instructions[0].{path}'
    assert reported in problem.message


# Whole files (§14.3).


@pytest.mark.parametrize('name', ['channels', 'tree'])
def test_an_authored_file_translates_to_its_bare_archive(name):
    translation = translate(read(f'{name}.stability.yaml'))

    assert translation.problems == []
    assert translation.archive == read(f'{name}.archive.yaml')


def test_settings_come_first_then_the_routine():
    translation = translate(
        {
            'data': {
                'duration': '1000 h',
                'channel_settings': {'temperature': {'hold': '65 °C'}},
                'routine': {
                    'instructions': [
                        {'channel': 'irradiation', 'hold': 'dark', 'duration': '1 h'}
                    ]
                },
            }
        }
    )
    data = translation.archive['data']

    assert translation.problems == []
    assert data['m_def'] == m_def(StabilityProtocol)
    assert data['duration'] == {'kind': 'fixed', 'value': approx(3600000)}
    assert [each['m_def'] for each in data['instructions']] == [
        m_def(HoldTemperature),
        m_def(IndefiniteRepeatingBlock),
    ]


def test_a_channel_of_several_variables_lists_one_setting_per_variable():
    translation = translate(
        {
            'data': {
                'channel_settings': {
                    'atmosphere': [
                        {'relative_humidity': '85 %'},
                        {'variable': 'oxygen', 'reference_point': 'ambient air'},
                        'air',
                    ]
                }
            }
        }
    )

    assert [p.path for p in translation.problems] == [
        'data.channel_settings.atmosphere[2]'
    ]
    assert translation.archive['data']['instructions'] == [
        entry(
            HoldRelativeHumidity,
            control=True,
            set_point=approx(0.85),
            duration=WHOLE_BLOCK,
        ),
        entry(HoldOxygenFraction, reference_point='ambient air', duration=WHOLE_BLOCK),
    ]


@pytest.mark.parametrize(
    'archive', ['channels.archive.yaml', 'channels.setpoint.archive.yaml']
)
def test_a_bare_archive_reads_as_itself_even_in_the_old_spelling(archive):
    translation = translate(read(archive))

    assert (translation.archive, translation.problems) == (
        read('channels.archive.yaml'),
        [],
    )


# What the file gets wrong: a problem with the path the file wrote, never an exception,
# and the rest still loads (§7).


@pytest.mark.parametrize(
    ('authored', 'path', 'reported'),
    [
        ({'channel': 'temperature', 'duration': '500'}, 'duration', 'bare number'),
        ({'channel': 'temperature', 'duration': '10 Hz'}, 'duration', 'Cannot convert'),
        ({'channel': 'temperature', 'hold': 'dark'}, 'hold', 'dark'),
        (
            {'channel': 'temperature', 'duraton': '1 h'},
            'duraton',
            'Did you mean `duration`?',
        ),
        (
            {'channel': 'temperature', 'hold_tolerance': '4 °C', 'hold': 'RT'},
            'hold_tolerance',
            'kelvin',
        ),
    ],
)
def test_a_value_that_cannot_be_read_is_a_problem_and_the_instruction_stays(
    authored, path, reported
):
    translation = instructions(authored)

    [problem] = translation.problems
    assert problem.path == f'instructions[0].{path}'
    assert reported in problem.message
    assert len(translation.archive['instructions']) == 1


@pytest.mark.parametrize(
    ('authored', 'reported'),
    [
        ({'channel': 'chuck_T'}, 'not a channel'),
        ({'channel': 'electrical_load', 'hold': '0.8 V'}, 'say which variable'),
        (
            {'channel': 'electrical_load', 'voltage': '1 V', 'current': '1 A'},
            'one variable',
        ),
        (
            {'channel': 'temperature', 'hold': '65 °C', 'ramp': {'to': '85 °C'}},
            'not both',
        ),
        ({'channel': 'atmosphere', 'humidity': '85 %RH'}, 'relative_humidity'),
        ({'m_def': 'no.such.Class'}, 'cannot find the class'),
    ],
)
def test_an_instruction_that_cannot_be_placed_is_left_out(authored, reported):
    translation = instructions(authored)

    [problem] = translation.problems
    assert reported in problem.message
    assert translation.archive.get('instructions', []) == []


def test_the_former_word_commands_is_reported_and_still_read():
    translation = translate_section(
        {'commands': [{'channel': 'temperature', 'duration': '1 h'}]},
        CountingRepeatingBlock,
    )

    [problem] = translation.problems
    assert problem.path == 'commands'
    assert 'write `instructions`' in problem.message
    assert translation.archive['sub_instructions'] == [
        entry(HoldTemperature, duration=HOUR)
    ]


# Durations.


@pytest.mark.parametrize(
    ('written', 'duration'),
    [
        ('1 h', HOUR),
        ('typical 1 min', {'kind': 'typical', 'value': 60.0}),
        ('open-ended', {'kind': 'open_ended'}),
        ('whole block', WHOLE_BLOCK),
    ],
)
def test_a_duration_is_a_length_or_says_what_kind_it_is(written, duration):
    translation = translate_section(
        {'instructions': [{'channel': 'temperature', 'duration': written}]},
        CountingRepeatingBlock,
    )

    assert translation.problems == []
    assert translation.archive['sub_instructions'][0]['duration'] == duration


def test_a_setting_written_without_a_duration_lasts_as_long_as_the_protocol():
    translation = translate(
        {
            'data': {
                'channel_settings': {'temperature': {'hold': '65 °C'}},
                'instructions': [{'channel': 'irradiation', 'hold': 'dark'}],
            }
        }
    )

    assert translation.problems == []
    durations = [
        each['duration'] for each in translation.archive['data']['instructions']
    ]
    assert durations == [WHOLE_BLOCK, WHOLE_BLOCK]


@pytest.mark.parametrize(
    ('ramp', 'reported'),
    [
        ({'from': '25 °C', 'to': '85 °C'}, ['writes its `duration`']),
        # A rate works the duration out.
        ({'from': '25 °C', 'to': '85 °C', 'rate': '60 K/h'}, []),
    ],
)
def test_an_instruction_in_the_routine_writes_its_duration(ramp, reported):
    translation = translate(
        {
            'data': {
                'routine': {'instructions': [{'channel': 'temperature', 'ramp': ramp}]}
            }
        }
    )

    assert [problem.path for problem in translation.problems] == [
        'data.routine.instructions[0]' for _ in reported
    ]
    for problem, fragment in zip(translation.problems, reported):
        assert fragment in problem.message
