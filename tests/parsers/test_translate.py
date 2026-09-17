"""The translator on its own: authored dict in, bare dict and problems out (§13.4, §15.2)."""

import os

import pytest
import yaml

from nomad_pv_stability_measurements.parsers.translate import (
    m_def,
    translate,
    translate_section,
)
from nomad_pv_stability_measurements.schema_packages.hold_below_steps import (
    HoldBelowWaterVaporFraction,
)
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldBendRadius,
    HoldCurrent,
    HoldIrradiance,
    HoldResistance,
    HoldStrain,
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

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
BLOCK = PlannedSubroutineStep


def read(name: str) -> dict:
    with open(os.path.join(DATA_DIR, name)) as file:
        return yaml.safe_load(file)


def entry(cls, **fields) -> dict:
    return {'m_def': m_def(cls), **fields}


def steps(*authored):
    """Authored steps, read the way a block reads its list."""
    return translate_section({'steps': list(authored)}, BLOCK)


# Dispatch: which class an entry is (D11, §15.2).


def test_a_channel_and_a_variable_name_the_step_class():
    translation = translate_section(
        {
            'steps': [
                {'channel': 'electrical_load', 'voltage': '0.8 V'},
                {
                    'name': 'phase',
                    'steps': [{'channel': 'mechanical', 'bend_radius': '2 m'}],
                },
            ]
        },
        BLOCK,
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [
            entry(HoldVoltage, control=True, set_point=0.8),
            entry(
                BLOCK,
                name='phase',
                steps=[entry(HoldBendRadius, control=True, set_point=2.0)],
            ),
        ]
    }


def test_an_entry_that_carries_its_m_def_keeps_it():
    authored = {
        'steps': [
            entry(HoldVoltage, control=True, set_point=0.8, monitor=True),
            entry(BLOCK, name='phase'),
        ]
    }

    assert translate_section(authored, BLOCK).archive == authored


def test_an_unknown_channel_is_a_problem_and_the_entry_is_left_out():
    translation = steps({'channel': 'chuck_T'}, {'name': 'kept'})

    assert translation.archive == {'steps': [entry(BLOCK, name='kept')]}
    [problem] = translation.problems
    assert problem.path == 'steps[0].channel'
    assert 'temperature, irradiation' in problem.message


def test_a_channel_word_must_agree_with_the_class():
    translation = steps(entry(HoldTemperature, channel='irradiation'))

    assert translation.archive == {'steps': []}
    assert 'does not match HoldTemperature' in translation.problems[0].message


def test_an_unresolvable_m_def_is_a_problem():
    translation = steps({'m_def': 'no.such.Class'})

    assert translation.archive == {'steps': []}
    assert translation.problems[0].path == 'steps[0].m_def'


def test_an_old_channel_class_is_read_as_its_channel():
    # §13's bare archives named the channel's own class.
    translation = steps(
        {
            'm_def': 'nomad_pv_stability_measurements.schema_packages.'
            'channel_commands.TemperatureChannelCommand',
            'temperature': 358.15,
            'duration': 3600,
        }
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [
            entry(
                HoldTemperature,
                control=True,
                set_point=358.15,
                estimated_duration=3600.0,
            )
        ]
    }


def test_commands_and_duration_are_read_as_steps_and_estimated_duration():
    translation = translate_section(
        {'commands': [{'name': 'a', 'duration': '1 h'}]}, BLOCK
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [entry(BLOCK, name='a', estimated_duration=3600.0)]
    }


def test_mode_is_read_as_execution_mode():
    translation = translate_section({'mode': 'parallel'}, BLOCK)

    assert translation.problems == []
    assert translation.archive == {'execution_mode': 'parallel'}


def test_a_word_and_its_field_written_together_is_a_problem():
    translation = translate_section({'duration': 60, 'estimated_duration': 60}, BLOCK)

    assert 'are one field' in translation.problems[0].message


# Values: a number in the declared unit (§6).


def test_a_value_is_read_into_the_declared_unit():
    translation = steps(
        {
            'channel': 'electrical_load',
            'current': '5 mA',
            'duration': '2 d',
            'sampling_rate': '10 Hz',
        }
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [
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
    translation = translate_section({'duration': 60}, BLOCK)

    assert translation.archive == {'estimated_duration': 60.0}
    assert isinstance(translation.archive['estimated_duration'], float)


def test_blank_text_is_left_out():
    assert translate_section({'duration': ' '}, BLOCK).archive == {}


def test_what_cannot_be_read_is_a_problem_with_its_path():
    translation = translate_section(
        {
            'commands': [
                {'name': 'a', 'duration': '1 h'},
                {'name': 'b', 'duration': 'a fortnight'},
                {'name': 'c', 'duration': '500'},
                {'name': 'd', 'duration': '10 Hz'},
            ]
        },
        BLOCK,
    )

    assert [
        step.get('estimated_duration') for step in translation.archive['steps']
    ] == [3600.0, None, None, None]
    # The path names what the file wrote.
    assert [problem.path for problem in translation.problems] == [
        'commands[1].duration',
        'commands[2].duration',
        'commands[3].duration',
    ]
    assert 'bare number' in translation.problems[1].message


# Setpoints: `hold`, `variable`, the variable's own key, named words (§15.2).


def test_hold_on_a_single_variable_channel_sets_that_step():
    translation = steps({'channel': 'temperature', 'hold': '65 °C'})

    assert translation.problems == []
    assert translation.archive == {
        'steps': [entry(HoldTemperature, control=True, set_point=pytest.approx(338.15))]
    }


def test_hold_beside_a_variable_sets_that_step():
    translation = steps(
        {'channel': 'electrical_load', 'variable': 'voltage', 'hold': '0.8 V'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [entry(HoldVoltage, control=True, set_point=0.8)]
    }


def test_a_named_word_becomes_the_value_it_stands_for():
    translation = steps({'channel': 'irradiation', 'hold': 'dark'})

    assert translation.problems == []
    assert translation.archive == {
        'steps': [entry(HoldIrradiance, control=True, set_point=0.0)]
    }


def test_a_named_word_is_read_nowhere_else():
    temperature = steps({'channel': 'temperature', 'hold': 'dark'})
    duration = steps({'channel': 'irradiation', 'duration': 'dark'})

    assert temperature.archive == {'steps': [entry(HoldTemperature)]}
    assert duration.archive == {'steps': [entry(HoldIrradiance)]}
    # The problem quotes the key the file wrote, not the field it was moved to.
    assert temperature.problems[0].path == 'steps[0].hold'
    assert 'could not read `hold`' in temperature.problems[0].message
    assert 'not a number followed by a unit' in duration.problems[0].message


def test_a_hold_with_nowhere_to_go_is_a_problem():
    translation = steps({'channel': 'electrical_load', 'hold': '0.8 V'})

    assert translation.archive == {'steps': []}
    assert 'voltage, current, resistance' in translation.problems[0].message


def test_a_variable_the_channel_does_not_have_is_a_problem():
    translation = steps(
        {'channel': 'mechanical', 'variable': 'voltage', 'strain': '2 %'}
    )

    assert translation.archive == {
        'steps': [entry(HoldStrain, control=True, set_point=pytest.approx(0.02))]
    }
    [problem] = translation.problems
    assert 'bend_radius, strain' in problem.message


def test_one_variable_set_twice_is_a_problem():
    translation = steps(
        {
            'channel': 'electrical_load',
            'variable': 'voltage',
            'hold': '0.8 V',
            'voltage': '0.7 V',
        }
    )

    assert translation.archive == {
        'steps': [entry(HoldVoltage, control=True, set_point=pytest.approx(0.7))]
    }
    assert 'both set voltage' in translation.problems[0].message


def test_a_step_sets_one_variable():
    translation = steps(
        {'channel': 'electrical_load', 'voltage': '0.8 V', 'current': '1 mA'}
    )

    assert translation.archive == {'steps': []}
    assert 'writes voltage, current' in translation.problems[0].message


def test_a_channel_logged_as_a_whole_becomes_one_step_per_variable():
    translation = steps(
        {'channel': 'electrical_load', 'monitor': True, 'sampling_rate': '1 Hz'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [
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
def test_open_circuit_names_the_step_that_sits_there(authored):
    # ISOS writes `OC`; the schema calls it `VOCTracking`, and both words reach it.
    translation = steps({'channel': 'electrical_load', **authored})

    assert translation.problems == []
    assert translation.archive == {'steps': [entry(VOCTracking, control=True)]}


def test_mpp_names_the_tracking_step():
    translation = steps(
        {'channel': 'electrical_load', 'hold': 'mpp', 'duration': '24 h'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [entry(MPPTracking, estimated_duration=86400.0, control=True)]
    }


def test_a_point_written_on_another_channel_is_a_problem():
    # Per channel, never global, exactly as `dark` is refused off irradiance (D8a).
    translation = steps({'channel': 'temperature', 'hold': 'mpp'})

    assert translation.archive == {'steps': []}
    assert 'not of `temperature`' in translation.problems[0].message


def test_a_point_takes_no_setpoint_beside_it():
    translation = steps({'channel': 'electrical_load', 'mpp': True, 'voltage': '0.8 V'})

    assert translation.archive == {'steps': []}
    assert 'takes no set point' in translation.problems[0].message


# Ramps: `ramp:` picks the ramping kind of the variable (§15.14).


def test_a_ramp_names_the_ramping_kind_of_the_variable():
    translation = steps(
        {
            'channel': 'temperature',
            'ramp': {'from': '25 °C', 'to': '85 °C', 'rate': '2 K/min'},
            'duration': '1 h',
        }
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [
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
    translation = steps(
        {'channel': 'temperature', 'ramp': {'from': '25 °C', 'to': '85 °C'}}
    )

    assert translation.problems == []
    assert 'ramp_rate' not in translation.archive['steps'][0]


def test_a_step_ramps_or_holds_but_not_both():
    translation = steps(
        {'channel': 'temperature', 'hold': '65 °C', 'ramp': {'from': '25 °C'}}
    )

    assert translation.archive == {'steps': []}
    assert 'ramps or holds' in translation.problems[0].message


def test_an_unknown_key_inside_a_ramp_is_a_problem():
    translation = steps(
        {
            'channel': 'temperature',
            'ramp': {'from': '25 °C', 'to': '85 °C', 'slope': 3},
        }
    )

    [problem] = translation.problems
    assert problem.path == 'steps[0].ramp.slope'
    assert 'no part of a ramp' in problem.message


def test_spectrum_is_a_plain_field_of_the_irradiance_step():
    translation = steps(
        {'channel': 'irradiation', 'hold': '1 sun', 'spectrum': 'AM1.5G'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [
            entry(
                HoldIrradiance,
                control=True,
                set_point=pytest.approx(1000),
                spectrum='AM1.5G',
            )
        ]
    }


def test_spectrum_is_no_field_of_another_step():
    translation = steps({'channel': 'temperature', 'spectrum': 'AM1.5G'})

    assert translation.problems[0].path == 'steps[0].spectrum'
    assert 'not a field of HoldTemperature' in translation.problems[0].message


# A relative humidity, carrying the temperature it was read at (§15.16).


def test_a_relative_humidity_is_read_with_the_temperature_beside_it():
    translation = steps(
        {'channel': 'atmosphere', 'water_vapor': {'rh': '85 %', 'at': '65 °C'}}
    )

    assert translation.problems == []
    [step] = translation.archive['steps']
    # The archive keeps the absolute ratio, exactly as §15.7 decided.
    assert step['m_def'] == m_def(HoldWaterVaporFraction)
    assert step['set_point'] == pytest.approx(0.2109, rel=1e-3)


def test_a_relative_humidity_needs_both_halves():
    translation = steps({'channel': 'atmosphere', 'water_vapor': {'rh': '85 %'}})

    assert translation.archive == {'steps': [entry(HoldWaterVaporFraction)]}
    assert 'both halves' in translation.problems[0].message


def test_only_the_water_axis_reads_a_section():
    translation = steps(
        {'channel': 'temperature', 'hold': {'rh': '85 %', 'at': '65 °C'}}
    )

    assert 'takes a value, not a section' in translation.problems[0].message


# Keys NOMAD would drop without a word (§9).


def test_an_unknown_key_is_a_problem_with_a_suggestion():
    translation = steps({'chanel': 'temperature', 'duraton': '1 h'})

    assert translation.archive == {'steps': [entry(BLOCK)]}
    assert [problem.path for problem in translation.problems] == [
        'steps[0].chanel',
        'steps[0].duraton',
    ]
    assert 'Did you mean `channel`?' in translation.problems[0].message
    assert 'Did you mean `duration`?' in translation.problems[1].message


# Whole files: `channel_settings` and `routine` become steps (§14.3).


def test_channel_settings_become_the_first_steps_and_the_routine_follows():
    translation = translate(read('channels.stability.yaml'))
    data = translation.archive['data']
    *settings, soak = data['steps']

    assert {'channel_settings', 'routine'}.isdisjoint(data)
    assert [step['m_def'] for step in settings] == [
        m_def(cls)
        for cls in (
            HoldTemperature,
            HoldIrradiance,
            HoldVoltage,
            HoldCurrent,
            HoldResistance,
        )
    ]
    # Settings are conditions: they hold for the whole protocol (D13).
    assert not any('estimated_duration' in step for step in settings)
    assert (soak['m_def'], soak['name']) == (m_def(BLOCK), 'soak')


def test_authored_steps_sit_between_the_settings_and_the_routine():
    translation = translate(
        {
            'data': {
                'channel_settings': {'temperature': {'hold': '65 °C'}},
                'steps': [
                    {'channel': 'irradiation', 'hold': 'dark', 'duration': '1 h'}
                ],
                'routine': {'name': 'soak'},
            }
        }
    )

    assert translation.problems == []
    assert [step['m_def'] for step in translation.archive['data']['steps']] == [
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
    [root] = data['steps']

    assert translation.problems == []
    assert data['m_def'] == m_def(StabilityProtocol)
    assert [block['name'] for block in root['steps']] == ['A', 'fork', 'D']


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
    translation = steps(entry(HoldTemperature, setpoint=300.0, set_point=300.0))

    assert 'are one field' in translation.problems[0].message


# Tolerances, and values a standard names (§17.3, §17.4).


@pytest.mark.parametrize(
    'authored',
    [{'hold': 'RT'}, {'temperature': 'RT'}],
)
def test_room_temperature_writes_its_value_and_its_tolerance(authored):
    translation = steps({'channel': 'temperature', **authored})

    assert translation.problems == []
    # 23 ± 4 °C, as ISOS Table 1 defines it — and no trace of the word (§17.3).
    assert translation.archive == {
        'steps': [
            entry(
                HoldTemperature,
                set_point=pytest.approx(296.15),
                control=True,
                set_point_tolerance=pytest.approx(4.0),
            )
        ]
    }


def test_a_tolerance_is_written_beside_the_hold():
    translation = steps(
        {'channel': 'temperature', 'hold': '65 °C', 'hold_tolerance': '2 K'}
    )

    assert translation.problems == []
    [step] = translation.archive['steps']
    assert step['set_point_tolerance'] == pytest.approx(2)


def test_a_written_tolerance_overrides_the_one_a_standard_value_brings():
    # A lab whose oven holds tighter than the standard asks is stating a fact (§17.4).
    translation = steps(
        {'channel': 'temperature', 'hold': 'RT', 'hold_tolerance': '1 K'}
    )

    assert translation.problems == []
    [step] = translation.archive['steps']
    assert (step['set_point'], step['set_point_tolerance']) == (
        pytest.approx(296.15),
        pytest.approx(1),
    )


@pytest.mark.parametrize('written', ['4 °C', '4 degC', '7 degF'])
def test_a_tolerance_in_an_offset_unit_is_refused(written):
    # `4 °C` converts to 277.15 K, a temperature and not a spread of four degrees.
    translation = steps(
        {'channel': 'temperature', 'hold': '65 °C', 'hold_tolerance': written}
    )

    [step] = translation.archive['steps']
    assert 'set_point_tolerance' not in step
    [problem] = translation.problems
    assert problem.path == 'steps[0].hold_tolerance'
    assert 'in kelvin' in problem.message


def test_a_named_value_is_read_at_either_end_of_a_ramp():
    # `ramp: {from: RT}` is ISOS-T-1, and `from: dark` is what D8a always promised.
    temperature = steps(
        {'channel': 'temperature', 'ramp': {'from': 'RT', 'to': '65 °C'}}
    )
    light = steps({'channel': 'irradiation', 'ramp': {'from': 'dark', 'to': '1 sun'}})

    assert (temperature.problems, light.problems) == ([], [])
    [ramp] = temperature.archive['steps']
    assert ramp['start_point'] == pytest.approx(296.15)
    # A ramp end has no tolerance to hold the standard value's ± 4 K (§17.3).
    assert 'set_point_tolerance' not in ramp
    assert light.archive['steps'][0]['start_point'] == pytest.approx(0)


def test_a_named_value_belongs_to_its_own_variable():
    translation = steps({'channel': 'irradiation', 'hold': 'RT'})

    assert translation.archive == {'steps': [entry(HoldIrradiance)]}
    assert 'could not read `hold`' in translation.problems[0].message


def test_dark_brings_no_tolerance():
    translation = steps({'channel': 'irradiation', 'hold': 'dark'})

    assert translation.archive == {
        'steps': [entry(HoldIrradiance, control=True, set_point=0.0)]
    }


def test_a_relative_humidity_may_be_read_at_room_temperature():
    translation = steps(
        {'channel': 'atmosphere', 'water_vapor': {'rh': '50 %', 'at': 'RT'}}
    )

    assert translation.problems == []
    assert translation.archive['steps'][0]['set_point'] == pytest.approx(
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
    translation = steps({**authored, 'hold_tolerance': '1 K'})

    assert any(message in problem.message for problem in translation.problems)
    assert not any(
        'set_point_tolerance' in step for step in translation.archive['steps']
    )


# A bound: `hold_below:` picks the bounded kind (§17.5).


def test_hold_below_names_the_bounded_kind_of_the_variable():
    translation = steps(
        {'channel': 'atmosphere', 'variable': 'water_vapor', 'hold_below': '55 %'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [
            entry(
                HoldBelowWaterVaporFraction,
                upper_bound=pytest.approx(0.55),
                control=True,
            )
        ]
    }


def test_a_bound_may_be_a_relative_humidity_at_its_temperature():
    translation = steps(
        {
            'channel': 'atmosphere',
            'variable': 'water_vapor',
            'hold_below': {'rh': '50 %', 'at': 'RT'},
        }
    )

    assert translation.problems == []
    [step] = translation.archive['steps']
    assert step['upper_bound'] == pytest.approx(0.0138, rel=1e-2)


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
    translation = steps({**authored, 'hold_below': '55 %'})

    assert translation.archive == {'steps': []}
    [problem] = translation.problems
    assert problem.path == f'steps[0].{path}'
    assert message in problem.message


def test_a_stored_bound_reads_back_as_a_bound():
    # No `hold_below:` in a bare archive: the class alone must pick the kind (§17.5).
    bare = {
        'steps': [entry(HoldBelowWaterVaporFraction, upper_bound=0.5, control=True)]
    }

    translation = translate_section(bare, BLOCK)

    assert (translation.archive, translation.problems) == (bare, [])
