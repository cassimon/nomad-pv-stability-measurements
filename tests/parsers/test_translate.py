"""The translator on its own: authored dict in, bare dict and problems out (§13.4, §15.2)."""

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
    InstructionBlock,
    TimedRepeatingBlock,
)
from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBelowAbsoluteHumidity,
    HoldBelowOxygenFraction,
    HoldBelowRelativeHumidity,
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    BalanceGas,
    HoldAbsoluteHumidity,
    HoldBendRadius,
    HoldCurrent,
    HoldIrradiance,
    HoldRelativeHumidity,
    HoldResistance,
    HoldStrain,
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
BLOCK = CountingRepeatingBlock


def read(name: str) -> dict:
    with open(os.path.join(DATA_DIR, name)) as file:
        return yaml.safe_load(file)


def entry(cls, **fields) -> dict:
    return {'m_def': m_def(cls), **fields}


def instructions(*authored):
    """Authored instructions, read the way a block reads its list."""
    return translate_section({'sub_instructions': list(authored)}, BLOCK)


# Dispatch: which class an entry is (D11, §15.2).


def test_a_channel_and_a_variable_name_the_instruction_class():
    translation = translate_section(
        {
            'sub_instructions': [
                {'channel': 'electrical_load', 'voltage': '0.8 V'},
                {
                    'name': 'phase',
                    'sub_instructions': [
                        {'channel': 'mechanical', 'bend_radius': '2 m'}
                    ],
                },
            ]
        },
        BLOCK,
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(HoldVoltage, control=True, set_point=0.8),
            entry(
                BLOCK,
                name='phase',
                sub_instructions=[entry(HoldBendRadius, control=True, set_point=2.0)],
            ),
        ]
    }


def test_an_entry_that_carries_its_m_def_keeps_it():
    authored = {
        'sub_instructions': [
            entry(HoldVoltage, control=True, set_point=0.8, monitor=True),
            entry(BLOCK, name='phase'),
        ]
    }

    assert translate_section(authored, BLOCK).archive == authored


def test_an_unknown_channel_is_a_problem_and_the_entry_is_left_out():
    translation = instructions({'channel': 'chuck_T'}, {'name': 'kept'})

    assert translation.archive == {'sub_instructions': [entry(BLOCK, name='kept')]}
    [problem] = translation.problems
    assert problem.path == 'sub_instructions[0].channel'
    assert 'temperature, irradiation' in problem.message


def test_a_channel_word_must_agree_with_the_class():
    translation = instructions(entry(HoldTemperature, channel='irradiation'))

    assert translation.archive == {'sub_instructions': []}
    assert 'does not match HoldTemperature' in translation.problems[0].message


def test_an_unresolvable_m_def_is_a_problem():
    translation = instructions({'m_def': 'no.such.Class'})

    assert translation.archive == {'sub_instructions': []}
    assert translation.problems[0].path == 'sub_instructions[0].m_def'


def test_an_old_channel_class_is_read_as_its_channel():
    # §13's bare archives named the channel's own class.
    translation = instructions(
        {
            'm_def': 'nomad_pv_stability_measurements.schema_packages.'
            'channel_commands.TemperatureChannelCommand',
            'temperature': 358.15,
            'duration': 3600,
        }
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(
                HoldTemperature,
                control=True,
                set_point=358.15,
                estimated_duration=3600.0,
            )
        ]
    }


def test_commands_and_duration_are_read_as_instructions_and_estimated_duration():
    translation = translate_section(
        {'commands': [{'channel': 'temperature', 'duration': '1 h'}]}, BLOCK
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [entry(HoldTemperature, estimated_duration=3600.0)]
    }


def test_a_protocols_commands_are_its_instructions():
    translation = translate_section(
        {'commands': [{'channel': 'temperature'}], 'duration': '1000 h'},
        StabilityProtocol,
    )

    assert translation.problems == []
    assert translation.archive == {
        'instructions': [entry(HoldTemperature)],
        'estimated_duration': 3600000.0,
    }


def test_mode_is_read_as_execution_mode():
    translation = translate_section({'mode': 'parallel'}, BLOCK)

    assert translation.problems == []
    assert translation.archive == {'sub_instruction_execution_mode': 'parallel'}


# Repetition: `repeat` and `repeat_for` (§23).


def test_a_block_without_repeat_repeats_indefinitely():
    translation = translate_section({'commands': [{'channel': 'temperature'}]}, BLOCK)

    assert translation.problems == []
    assert 'repeat_n' not in translation.archive


def test_repeat_indefinitely_says_so_and_writes_nothing():
    translation = translate_section({'repeat': 'indefinitely'}, BLOCK)

    assert (translation.archive, translation.problems) == ({}, [])


def test_repeat_a_number_of_times_is_repeat_n():
    translation = translate_section({'repeat': 5}, BLOCK)

    assert (translation.archive, translation.problems) == ({'repeat_n': 5}, [])


@pytest.mark.parametrize(
    ('old', 'instead'),
    [
        ('until_end_of_protocol', '`repeat: indefinitely`'),
        ('until_end_of_duration', '`repeat_for: 12 h`'),
        ('n_times', '`repeat: 5`'),
    ],
)
def test_the_former_repeat_words_say_what_to_write_instead(old, instead):
    translation = translate_section({'repeat': old}, BLOCK)

    [problem] = translation.problems
    assert problem.path == 'repeat'
    assert f'`repeat: {old}` is not written any more' in problem.message
    assert instead in problem.message


@pytest.mark.parametrize('written', ['often', True, 2.5])
def test_a_repeat_that_is_no_count_is_a_problem(written):
    [problem] = translate_section({'repeat': written}, BLOCK).problems

    assert 'write a number of times, or `indefinitely`' in problem.message


def test_repeat_for_makes_a_timed_block():
    translation = instructions(
        {'repeat_for': '1000 h', 'commands': [{'channel': 'temperature'}]}
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(
                TimedRepeatingBlock,
                repeat_duration=3600000.0,
                sub_instructions=[entry(HoldTemperature)],
            )
        ]
    }


def test_a_plain_block_runs_once_and_takes_no_repeat():
    translation = instructions(
        entry(InstructionBlock, repeat=3, commands=[{'channel': 'temperature'}])
    )

    [problem] = translation.problems
    assert 'InstructionBlock runs its commands once' in problem.message
    assert 'repeat_n' not in translation.archive['sub_instructions'][0]


def test_a_timed_block_takes_no_repeat():
    translation = instructions(
        {'repeat_for': '1 h', 'repeat': 3, 'commands': [{'channel': 'temperature'}]}
    )

    [problem] = translation.problems
    assert 'stopped by its `repeat_for`' in problem.message


def test_a_block_takes_no_duration():
    # Only the protocol stops instructions; a block's length follows from its commands.
    translation = instructions(
        {'duration': '1 h', 'commands': [{'channel': 'temperature'}]}
    )

    [problem] = translation.problems
    assert problem.path == 'sub_instructions[0].duration'
    assert "a block's duration follows from its commands" in problem.message
    assert 'estimated_duration' not in translation.archive['sub_instructions'][0]


def test_a_word_and_its_field_written_together_is_a_problem():
    translation = translate_section(
        {'duration': 60, 'estimated_duration': 60}, HoldTemperature
    )

    assert 'are one field' in translation.problems[0].message


# Values: a number in the declared unit (§6).


def test_a_value_is_read_into_the_declared_unit():
    translation = instructions(
        {
            'channel': 'electrical_load',
            'current': '5 mA',
            'duration': '2 d',
            'sampling_rate': '10 Hz',
        }
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(
                HoldCurrent,
                control=True,
                set_point=pytest.approx(0.005),
                estimated_duration=172800.0,
                sampling_rate=10.0,
            )
        ]
    }


def test_a_plain_number_is_already_in_the_declared_unit():
    translation = translate_section({'duration': 60}, HoldTemperature)

    assert translation.archive == {'estimated_duration': 60.0}
    assert isinstance(translation.archive['estimated_duration'], float)


def test_blank_text_is_left_out():
    assert translate_section({'duration': ' '}, HoldTemperature).archive == {}


def test_what_cannot_be_read_is_a_problem_with_its_path():
    translation = translate_section(
        {
            'commands': [
                {'channel': 'temperature', 'duration': '1 h'},
                {'channel': 'temperature', 'duration': 'a fortnight'},
                {'channel': 'temperature', 'duration': '500'},
                {'channel': 'temperature', 'duration': '10 Hz'},
            ]
        },
        BLOCK,
    )

    assert [
        each.get('estimated_duration')
        for each in translation.archive['sub_instructions']
    ] == [3600.0, None, None, None]
    # The path names what the file wrote.
    assert [problem.path for problem in translation.problems] == [
        'commands[1].duration',
        'commands[2].duration',
        'commands[3].duration',
    ]
    assert 'bare number' in translation.problems[1].message


# Setpoints: `hold`, `variable`, the variable's own key, named words (§15.2).


def test_hold_on_a_single_variable_channel_sets_that_instruction():
    translation = instructions({'channel': 'temperature', 'hold': '65 °C'})

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(HoldTemperature, control=True, set_point=pytest.approx(338.15))
        ]
    }


def test_hold_beside_a_variable_sets_that_instruction():
    translation = instructions(
        {'channel': 'electrical_load', 'variable': 'voltage', 'hold': '0.8 V'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [entry(HoldVoltage, control=True, set_point=0.8)]
    }


def test_a_named_word_becomes_the_value_it_stands_for():
    translation = instructions({'channel': 'irradiation', 'hold': 'dark'})

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [entry(HoldIrradiance, control=True, set_point=0.0)]
    }


def test_a_named_word_is_read_nowhere_else():
    temperature = instructions({'channel': 'temperature', 'hold': 'dark'})
    duration = instructions({'channel': 'irradiation', 'duration': 'dark'})

    assert temperature.archive == {'sub_instructions': [entry(HoldTemperature)]}
    assert duration.archive == {'sub_instructions': [entry(HoldIrradiance)]}
    # The problem quotes the key the file wrote, not the field it was moved to.
    assert temperature.problems[0].path == 'sub_instructions[0].hold'
    assert 'could not read `hold`' in temperature.problems[0].message
    assert 'not a number followed by a unit' in duration.problems[0].message


def test_a_hold_with_nowhere_to_go_is_a_problem():
    translation = instructions({'channel': 'electrical_load', 'hold': '0.8 V'})

    assert translation.archive == {'sub_instructions': []}
    assert 'voltage, current, resistance' in translation.problems[0].message


def test_a_variable_the_channel_does_not_have_is_a_problem():
    translation = instructions(
        {'channel': 'mechanical', 'variable': 'voltage', 'strain': '2 %'}
    )

    assert translation.archive == {
        'sub_instructions': [
            entry(HoldStrain, control=True, set_point=pytest.approx(0.02))
        ]
    }
    [problem] = translation.problems
    assert 'bend_radius, strain' in problem.message


def test_one_variable_set_twice_is_a_problem():
    translation = instructions(
        {
            'channel': 'electrical_load',
            'variable': 'voltage',
            'hold': '0.8 V',
            'voltage': '0.7 V',
        }
    )

    assert translation.archive == {
        'sub_instructions': [
            entry(HoldVoltage, control=True, set_point=pytest.approx(0.7))
        ]
    }
    assert 'both set voltage' in translation.problems[0].message


def test_an_instruction_sets_one_variable():
    translation = instructions(
        {'channel': 'electrical_load', 'voltage': '0.8 V', 'current': '1 mA'}
    )

    assert translation.archive == {'sub_instructions': []}
    assert 'writes voltage, current' in translation.problems[0].message


def test_a_channel_logged_as_a_whole_becomes_one_instruction_per_variable():
    translation = instructions(
        {'channel': 'electrical_load', 'monitor': True, 'sampling_rate': '1 Hz'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(cls, monitor=True, sampling_rate=1.0)
            for cls in (HoldVoltage, HoldCurrent, HoldResistance)
        ]
    }


@pytest.mark.parametrize(
    'authored',
    [
        {'hold': 'open_circuit'},
        {'open_circuit': True},
        {'hold': 'voc'},
        {'voc': True},
    ],
)
def test_open_circuit_names_the_instruction_that_sits_there(authored):
    # ISOS writes `OC`; the schema calls it `VOCTracking`, and both words reach it.
    translation = instructions({'channel': 'electrical_load', **authored})

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [entry(VOCTracking, control=True)]
    }


def test_mpp_names_the_tracking_instruction():
    translation = instructions(
        {'channel': 'electrical_load', 'hold': 'mpp', 'duration': '24 h'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(MPPTracking, estimated_duration=86400.0, control=True)
        ]
    }


def test_a_point_written_on_another_channel_is_a_problem():
    # Per channel, never global, exactly as `dark` is refused off irradiance (D8a).
    translation = instructions({'channel': 'temperature', 'hold': 'mpp'})

    assert translation.archive == {'sub_instructions': []}
    assert 'not of `temperature`' in translation.problems[0].message


def test_a_point_takes_no_setpoint_beside_it():
    translation = instructions(
        {'channel': 'electrical_load', 'mpp': True, 'voltage': '0.8 V'}
    )

    assert translation.archive == {'sub_instructions': []}
    assert 'takes no set point' in translation.problems[0].message


# Ramps: `ramp:` picks the ramping kind of the variable (§15.14).


def test_a_ramp_names_the_ramping_kind_of_the_variable():
    translation = instructions(
        {
            'channel': 'temperature',
            'ramp': {'from': '25 °C', 'to': '85 °C', 'rate': '2 K/min'},
            'duration': '1 h',
        }
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(
                RampTemperature,
                estimated_duration=3600.0,
                start_point=pytest.approx(298.15),
                end_point=pytest.approx(358.15),
                ramp_rate=pytest.approx(2 / 60),
                control=True,
            )
        ]
    }


def test_a_ramp_may_leave_its_rate_to_the_duration():
    # D16 gives a ramp a rate or a duration; the schema derives the other (§15.11).
    translation = instructions(
        {'channel': 'temperature', 'ramp': {'from': '25 °C', 'to': '85 °C'}}
    )

    assert translation.problems == []
    assert 'ramp_rate' not in translation.archive['sub_instructions'][0]


def test_an_instruction_ramps_or_holds_but_not_both():
    translation = instructions(
        {'channel': 'temperature', 'hold': '65 °C', 'ramp': {'from': '25 °C'}}
    )

    assert translation.archive == {'sub_instructions': []}
    assert 'ramps or holds' in translation.problems[0].message


def test_an_unknown_key_inside_a_ramp_is_a_problem():
    translation = instructions(
        {
            'channel': 'temperature',
            'ramp': {'from': '25 °C', 'to': '85 °C', 'slope': 3},
        }
    )

    [problem] = translation.problems
    assert problem.path == 'sub_instructions[0].ramp.slope'
    assert 'no part of a ramp' in problem.message


def test_spectrum_is_a_plain_field_of_the_irradiance_instruction():
    translation = instructions(
        {'channel': 'irradiation', 'hold': '1 sun', 'spectrum': 'AM1.5G'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(
                HoldIrradiance,
                control=True,
                set_point=pytest.approx(1000),
                spectrum='AM1.5G',
            )
        ]
    }


def test_spectrum_is_no_field_of_another_instruction():
    translation = instructions({'channel': 'temperature', 'spectrum': 'AM1.5G'})

    assert translation.problems[0].path == 'sub_instructions[0].spectrum'
    assert 'not a field of HoldTemperature' in translation.problems[0].message


# A relative humidity, carrying the temperature it was read at (§15.16).


def test_a_relative_humidity_is_read_with_the_temperature_beside_it():
    translation = instructions(
        {'channel': 'atmosphere', 'water_vapor': {'rh': '85 %', 'at': '65 °C'}}
    )

    assert translation.problems == []
    [instruction] = translation.archive['sub_instructions']
    # The archive keeps the absolute ratio, exactly as §15.7 decided.
    assert instruction['m_def'] == m_def(HoldAbsoluteHumidity)
    assert instruction['set_point'] == pytest.approx(0.2109, rel=1e-3)


def test_a_relative_humidity_needs_both_halves():
    translation = instructions({'channel': 'atmosphere', 'water_vapor': {'rh': '85 %'}})

    assert translation.archive == {'sub_instructions': [entry(HoldAbsoluteHumidity)]}
    assert 'both halves' in translation.problems[0].message


def test_only_the_water_axis_reads_a_section():
    translation = instructions(
        {'channel': 'temperature', 'hold': {'rh': '85 %', 'at': '65 °C'}}
    )

    assert 'takes a value, not a section' in translation.problems[0].message


# Keys NOMAD would drop without a word (§9).


def test_an_unknown_key_is_a_problem_with_a_suggestion():
    translation = instructions({'chanel': 'temperature', 'duraton': '1 h'})

    assert translation.archive == {'sub_instructions': [entry(BLOCK)]}
    assert [problem.path for problem in translation.problems] == [
        'sub_instructions[0].chanel',
        'sub_instructions[0].duraton',
    ]
    assert 'Did you mean `channel`?' in translation.problems[0].message
    assert 'Did you mean `duration`?' in translation.problems[1].message


# Whole files: `channel_settings` and `routine` become instructions (§14.3).


def test_channel_settings_become_the_first_instructions_and_the_routine_follows():
    translation = translate(read('channels.stability.yaml'))
    data = translation.archive['data']
    *settings, soak = data['instructions']

    assert {'channel_settings', 'routine'}.isdisjoint(data)
    assert [instruction['m_def'] for instruction in settings] == [
        m_def(cls)
        for cls in (
            HoldTemperature,
            HoldIrradiance,
            HoldVoltage,
            HoldCurrent,
            HoldResistance,
        )
    ]
    # Settings never finish: they hold for the whole protocol (§23).
    assert not any('estimated_duration' in instruction for instruction in settings)
    assert (soak['m_def'], soak['name']) == (m_def(BLOCK), 'soak')


def test_authored_instructions_sit_between_the_settings_and_the_routine():
    translation = translate(
        {
            'data': {
                'channel_settings': {'temperature': {'hold': '65 °C'}},
                'instructions': [
                    {'channel': 'irradiation', 'hold': 'dark', 'duration': '1 h'}
                ],
                'routine': {'name': 'soak', 'commands': [{'channel': 'temperature'}]},
            }
        }
    )

    assert translation.problems == []
    instructions = translation.archive['data']['instructions']
    assert [each['m_def'] for each in instructions] == [
        m_def(HoldTemperature),
        m_def(HoldIrradiance),
        m_def(BLOCK),
    ]


def test_a_settings_slot_must_agree_with_its_channel():
    translation = translate(
        {'data': {'channel_settings': {'temperature': {'channel': 'irradiation'}}}}
    )

    assert translation.problems[0].path == 'data.channel_settings.temperature.channel'


def test_a_whole_file_gets_its_root_m_def():
    translation = translate(read('tree.stability.yaml'))
    data = translation.archive['data']
    [root] = data['instructions']

    assert translation.problems == []
    assert data['m_def'] == m_def(StabilityProtocol)
    assert [block['name'] for block in root['sub_instructions']] == ['A', 'fork', 'D']


def test_a_file_without_data_is_a_problem():
    assert translate({}).problems[0].path == 'data'


@pytest.mark.parametrize(
    ('name', 'paths'),
    [
        # Every word the example writes now has a place in the schema (§15.13).
        ('channels', []),
        ('tree', []),
    ],
)
def test_each_authored_file_translates_to_its_bare_archive(name, paths):
    translation = translate(read(f'{name}.stability.yaml'))

    assert [problem.path for problem in translation.problems] == paths
    assert translation.archive == read(f'{name}.archive.yaml')


def test_a_bare_archive_translates_to_itself():
    # The bare format is a subset of the authored one (§13.1a).
    bare = translate(read('channels.stability.yaml')).archive
    again = translate(bare)

    assert (again.archive, again.problems) == (bare, [])


def test_a_bare_archive_in_the_old_spelling_still_loads():
    # §17.4 renamed `setpoint` to `set_point`. Every archive written before it spells the
    # old name, and §13.1a promises it still loads — to exactly today's archive.
    old = read('channels.setpoint.archive.yaml')
    assert 'setpoint' in str(old) and 'set_point' not in str(old)

    translation = translate(old)

    assert (translation.archive, translation.problems) == (
        read('channels.archive.yaml'),
        [],
    )


def test_the_old_spelling_and_the_new_one_together_are_one_field():
    translation = instructions(entry(HoldTemperature, setpoint=300.0, set_point=300.0))

    assert 'are one field' in translation.problems[0].message


# Tolerances, and values a standard names (§17.3, §17.4).


@pytest.mark.parametrize(
    'authored',
    [{'hold': 'RT'}, {'temperature': 'RT'}],
)
def test_room_temperature_writes_its_value_and_its_tolerance(authored):
    translation = instructions({'channel': 'temperature', **authored})

    assert translation.problems == []
    # 23 ± 4 °C, as ISOS Table 1 defines it — and no trace of the word (§17.3).
    assert translation.archive == {
        'sub_instructions': [
            entry(
                HoldTemperature,
                set_point=pytest.approx(296.15),
                control=True,
                set_point_tolerance=pytest.approx(4.0),
            )
        ]
    }


def test_a_tolerance_is_written_beside_the_hold():
    translation = instructions(
        {'channel': 'temperature', 'hold': '65 °C', 'hold_tolerance': '2 K'}
    )

    assert translation.problems == []
    [instruction] = translation.archive['sub_instructions']
    assert instruction['set_point_tolerance'] == pytest.approx(2)


def test_a_written_tolerance_overrides_the_one_a_standard_value_brings():
    # A lab whose oven holds tighter than the standard asks is stating a fact (§17.4).
    translation = instructions(
        {'channel': 'temperature', 'hold': 'RT', 'hold_tolerance': '1 K'}
    )

    assert translation.problems == []
    [instruction] = translation.archive['sub_instructions']
    assert (instruction['set_point'], instruction['set_point_tolerance']) == (
        pytest.approx(296.15),
        pytest.approx(1),
    )


@pytest.mark.parametrize('written', ['4 °C', '4 degC', '7 degF'])
def test_a_tolerance_in_an_offset_unit_is_refused(written):
    # `4 °C` converts to 277.15 K, a temperature and not a spread of four degrees.
    translation = instructions(
        {'channel': 'temperature', 'hold': '65 °C', 'hold_tolerance': written}
    )

    [instruction] = translation.archive['sub_instructions']
    assert 'set_point_tolerance' not in instruction
    [problem] = translation.problems
    assert problem.path == 'sub_instructions[0].hold_tolerance'
    assert 'in kelvin' in problem.message


def test_a_named_value_is_read_at_either_end_of_a_ramp():
    # `ramp: {from: RT}` is ISOS-T-1, and `from: dark` is what D8a always promised.
    temperature = instructions(
        {'channel': 'temperature', 'ramp': {'from': 'RT', 'to': '65 °C'}}
    )
    light = instructions(
        {'channel': 'irradiation', 'ramp': {'from': 'dark', 'to': '1 sun'}}
    )

    assert (temperature.problems, light.problems) == ([], [])
    [ramp] = temperature.archive['sub_instructions']
    assert ramp['start_point'] == pytest.approx(296.15)
    # A ramp end has no tolerance to hold the standard value's ± 4 K (§17.3).
    assert 'set_point_tolerance' not in ramp
    assert light.archive['sub_instructions'][0]['start_point'] == pytest.approx(0)


def test_a_named_value_belongs_to_its_own_variable():
    translation = instructions({'channel': 'irradiation', 'hold': 'RT'})

    assert translation.archive == {'sub_instructions': [entry(HoldIrradiance)]}
    assert 'could not read `hold`' in translation.problems[0].message


def test_dark_brings_no_tolerance():
    translation = instructions({'channel': 'irradiation', 'hold': 'dark'})

    assert translation.archive == {
        'sub_instructions': [entry(HoldIrradiance, control=True, set_point=0.0)]
    }


def test_a_relative_humidity_may_be_read_at_room_temperature():
    translation = instructions(
        {'channel': 'atmosphere', 'water_vapor': {'rh': '50 %', 'at': 'RT'}}
    )

    assert translation.problems == []
    assert translation.archive['sub_instructions'][0]['set_point'] == pytest.approx(
        0.0138, rel=1e-2
    )


@pytest.mark.parametrize(
    ('authored', 'message'),
    [
        ({'channel': 'electrical_load', 'hold': 'mpp'}, 'no value to be a tolerance'),
        (
            {'channel': 'temperature', 'ramp': {'from': 'RT', 'to': '65 °C'}},
            'ramps or holds',
        ),
        ({'channel': 'electrical_load'}, 'say which variable'),
        ({'channel': 'atmosphere', 'balance_gas': 'N2'}, 'no value to be a tolerance'),
    ],
)
def test_a_tolerance_with_no_held_value_is_a_problem(authored, message):
    translation = instructions({**authored, 'hold_tolerance': '1 K'})

    assert any(message in problem.message for problem in translation.problems)
    assert not any(
        'set_point_tolerance' in instruction
        for instruction in translation.archive['sub_instructions']
    )


# A bound: `hold_below:` picks the bounded kind (§17.5).


def test_hold_below_names_the_bounded_kind_of_the_variable():
    translation = instructions(
        {'channel': 'atmosphere', 'variable': 'water_vapor', 'hold_below': '55 %'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(
                HoldBelowAbsoluteHumidity,
                upper_bound=pytest.approx(0.55),
                control=True,
            )
        ]
    }


def test_a_bound_may_be_a_relative_humidity_at_its_temperature():
    translation = instructions(
        {
            'channel': 'atmosphere',
            'variable': 'water_vapor',
            'hold_below': {'rh': '50 %', 'at': 'RT'},
        }
    )

    assert translation.problems == []
    [instruction] = translation.archive['sub_instructions']
    assert instruction['upper_bound'] == pytest.approx(0.0138, rel=1e-2)


@pytest.mark.parametrize(
    ('authored', 'path', 'message'),
    [
        # No standard bounds a temperature yet, so it has no class (§17.5).
        ({'channel': 'temperature'}, 'hold_below', 'takes no `hold_below`'),
        (
            {'channel': 'atmosphere', 'variable': 'water_vapor', 'hold': '1 %'},
            'hold_below',
            'not both',
        ),
        # Named nowhere: one boundable variable must not be picked for the author.
        ({'channel': 'atmosphere'}, 'hold_below', 'say which variable is bounded'),
    ],
)
def test_a_bound_that_cannot_be_placed_is_a_problem(authored, path, message):
    translation = instructions({**authored, 'hold_below': '55 %'})

    assert translation.archive == {'sub_instructions': []}
    [problem] = translation.problems
    assert problem.path == f'sub_instructions[0].{path}'
    assert message in problem.message


def test_a_stored_bound_reads_back_as_a_bound():
    # No `hold_below:` in a bare archive: the class alone must pick the kind (§17.5).
    bare = {
        'sub_instructions': [
            entry(HoldBelowAbsoluteHumidity, upper_bound=0.5, control=True)
        ]
    }

    translation = translate_section(bare, BLOCK)

    assert (translation.archive, translation.problems) == (bare, [])


# A cycle by a path not stated is a ramp that says so (§21.2).


def test_a_cycle_is_written_as_a_ramp_that_cycles():
    translation = instructions(
        {
            'channel': 'temperature',
            'ramp': {'from': 'RT', 'to': '65 °C'},
            'end_of_ramp_behavior': 'cycle',
        }
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(
                RampTemperature,
                start_point=pytest.approx(296.15),
                end_point=pytest.approx(338.15),
                end_of_ramp_behavior='cycle',
                control=True,
            )
        ]
    }


@pytest.mark.parametrize(
    ('authored', 'key'),
    [
        # Retired with §21: a cycle is no kind of its own, a recommendation no field.
        ({'channel': 'temperature', 'cycle': {'from': 'RT', 'to': '65 °C'}}, 'cycle'),
        (
            {'channel': 'irradiation', 'recommended_hold': '900 W/m^2'},
            'recommended_hold',
        ),
    ],
)
def test_a_word_retired_in_review_is_no_word_any_more(authored, key):
    translation = instructions(authored)

    assert any(
        problem.path == f'sub_instructions[0].{key}' for problem in translation.problems
    )


# Relative and absolute humidity (§20.6).


@pytest.mark.parametrize('written', ['85 %', '85 %RH', '85%rh'])
def test_a_relative_humidity_is_stored_as_the_fraction_itself(written):
    translation = instructions({'channel': 'atmosphere', 'relative_humidity': written})

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(HoldRelativeHumidity, set_point=pytest.approx(0.85), control=True)
        ]
    }


def test_an_absolute_humidity_still_refuses_a_relative_one():
    translation = instructions({'channel': 'atmosphere', 'absolute_humidity': '85 %RH'})

    assert 'not a volume ratio' in translation.problems[0].message


@pytest.mark.parametrize(
    'authored',
    [{'water_vapor': '500 ppm'}, {'variable': 'water_vapor', 'hold': '500 ppm'}],
)
def test_water_vapor_is_read_as_the_absolute_humidity_it_became(authored):
    translation = instructions({'channel': 'atmosphere', **authored})

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(HoldAbsoluteHumidity, set_point=pytest.approx(5e-4), control=True)
        ]
    }


def test_an_archive_naming_the_old_class_loads_as_the_renamed_one():
    old = 'nomad_pv_stability_measurements.schema_packages.hold_steps.HoldWaterVaporFraction'

    translation = instructions({'m_def': old, 'set_point': 5e-4, 'control': True})

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [entry(HoldAbsoluteHumidity, set_point=5e-4, control=True)]
    }


def test_a_relative_humidity_may_be_bounded():
    translation = instructions(
        {'channel': 'atmosphere', 'variable': 'relative_humidity', 'hold_below': '55 %'}
    )

    assert translation.archive == {
        'sub_instructions': [
            entry(
                HoldBelowRelativeHumidity, upper_bound=pytest.approx(0.55), control=True
            )
        ]
    }


# An inert atmosphere (§20.5).


def test_an_inert_atmosphere_is_thresholds_and_a_gas():
    translation = instructions(
        {'channel': 'atmosphere', 'variable': 'oxygen', 'hold_below': '1 ppm'},
        {
            'channel': 'atmosphere',
            'variable': 'absolute_humidity',
            'hold_below': '1 ppm',
        },
        {'channel': 'atmosphere', 'balance_gas': 'N2'},
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(
                HoldBelowOxygenFraction, upper_bound=pytest.approx(1e-6), control=True
            ),
            entry(
                HoldBelowAbsoluteHumidity, upper_bound=pytest.approx(1e-6), control=True
            ),
            entry(BalanceGas, gas='N2', control=True),
        ]
    }


# A range: `hold_between` (§22).


def test_a_range_is_written_as_its_two_bounds():
    translation = instructions(
        {
            'channel': 'irradiation',
            'hold_between': {'lower': '800 W/m^2', 'upper': '1 sun'},
        }
    )

    assert translation.problems == []
    assert translation.archive == {
        'sub_instructions': [
            entry(
                HoldBetweenIrradiance,
                lower_bound=pytest.approx(800),
                upper_bound=pytest.approx(1000),
                control=True,
            )
        ]
    }


@pytest.mark.parametrize(
    ('authored', 'path', 'message'),
    [
        (
            {'channel': 'irradiation', 'hold_between': '800 W/m^2'},
            'hold_between',
            'expected a section with `lower` and `upper`',
        ),
        (
            {
                'channel': 'irradiation',
                'hold_between': {'lower': '800 W/m^2', 'middle': '900 W/m^2'},
            },
            'hold_between.middle',
            'no part of a range',
        ),
        (
            {
                'channel': 'irradiation',
                'hold': '900 W/m^2',
                'hold_between': {'lower': '800 W/m^2', 'upper': '1000 W/m^2'},
            },
            'hold_between',
            'not both',
        ),
        (
            {
                'channel': 'temperature',
                'hold_between': {'lower': '20 °C', 'upper': '30 °C'},
            },
            'hold_between',
            'no standard gives it a range yet',
        ),
        (
            {
                'channel': 'electrical_load',
                'hold_between': {'lower': '0 V', 'upper': '1 V'},
            },
            'hold_between',
            'say which variable is bounded',
        ),
    ],
)
def test_a_range_that_cannot_be_read_is_a_problem(authored, path, message):
    translation = instructions(authored)

    assert any(
        problem.path == f'sub_instructions[0].{path}'
        for problem in translation.problems
    )
    assert any(message in problem.message for problem in translation.problems)


def test_a_stored_range_reads_back_as_a_range():
    # No `hold_between:` in a bare archive: the class alone must pick the kind.
    bare = {
        'sub_instructions': [
            entry(
                HoldBetweenIrradiance, lower_bound=800, upper_bound=1000, control=True
            )
        ]
    }

    translation = translate_section(bare, BLOCK)

    assert (translation.archive, translation.problems) == (bare, [])
