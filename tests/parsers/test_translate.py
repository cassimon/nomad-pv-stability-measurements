"""The translator on its own: authored dict in, bare dict and problems out (§13.4, §15.2)."""

import os

import pytest
import yaml

from nomad_pv_stability_measurements.parsers.translate import (
    m_def,
    translate,
    translate_section,
)
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldBendRadius,
    HoldCurrent,
    HoldIrradiance,
    HoldResistance,
    HoldStrain,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
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
            entry(HoldVoltage, control=True, setpoint=0.8),
            entry(
                BLOCK,
                name='phase',
                steps=[entry(HoldBendRadius, control=True, setpoint=2.0)],
            ),
        ]
    }


def test_an_entry_that_carries_its_m_def_keeps_it():
    authored = {
        'steps': [
            entry(HoldVoltage, control=True, setpoint=0.8, monitor=True),
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
                setpoint=358.15,
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
                setpoint=pytest.approx(0.005),
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
        'steps': [entry(HoldTemperature, control=True, setpoint=pytest.approx(338.15))]
    }


def test_hold_beside_a_variable_sets_that_step():
    translation = steps(
        {'channel': 'electrical_load', 'variable': 'voltage', 'hold': '0.8 V'}
    )

    assert translation.problems == []
    assert translation.archive == {
        'steps': [entry(HoldVoltage, control=True, setpoint=0.8)]
    }


def test_a_named_word_becomes_the_value_it_stands_for():
    translation = steps({'channel': 'irradiation', 'hold': 'dark'})

    assert translation.problems == []
    assert translation.archive == {
        'steps': [entry(HoldIrradiance, control=True, setpoint=0.0)]
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
        'steps': [entry(HoldStrain, control=True, setpoint=pytest.approx(0.02))]
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
        'steps': [entry(HoldVoltage, control=True, setpoint=pytest.approx(0.7))]
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
    ('authored', 'path'),
    [
        ({'hold': 'open_circuit'}, 'steps[0].hold'),
        ({'open_circuit': True}, 'steps[0].open_circuit'),
    ],
)
def test_open_circuit_is_reported_and_its_step_left_out(authored, path):
    translation = steps({'channel': 'electrical_load', **authored})

    assert translation.archive == {'steps': []}
    [problem] = translation.problems
    assert problem.path == path
    assert 'not part of the schema any more' in problem.message


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
                setpoint=pytest.approx(1000),
                spectrum='AM1.5G',
            )
        ]
    }


def test_spectrum_is_no_field_of_another_step():
    translation = steps({'channel': 'temperature', 'spectrum': 'AM1.5G'})

    assert translation.problems[0].path == 'steps[0].spectrum'
    assert 'not a field of HoldTemperature' in translation.problems[0].message


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
        # The example keeps `open_circuit`, which has no place in the schema (§15.2).
        ('channels', ['data.routine.commands[4].hold']),
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
