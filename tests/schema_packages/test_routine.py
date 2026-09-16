"""The steps and the block, tested on bare dicts: `m_def` written out, numbers in the
declared unit (Design.md §15.1). How an authored file gets here is tests/parsers."""

import os

import pytest
from nomad.client import normalize_all, parse
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.activity_steps import (
    Current,
    Irradiance,
    Resistance,
    Temperature,
    Voltage,
)
from nomad_pv_stability_measurements.schema_packages.general import PlannedProcessStep
from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedMonitorControlStep,
    PlannedSubroutineStep,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
BLOCK = PlannedSubroutineStep


def entry(cls, **fields) -> dict:
    """One section as the bare archive writes it, naming its class."""
    return {'m_def': f'{cls.__module__}.{cls.__name__}', **fields}


@pytest.mark.parametrize(
    ('written', 'derived', 'expected'),
    [
        ({'sample_every': 60}, 'sampling_rate', 1 / 60),
        ({'sampling_rate': 10}, 'sample_every', 0.1),
    ],
)
def test_both_sampling_figures_are_stored(normalized, written, derived, expected):
    # Whichever the archive holds, the other is calculated from it (13.5 a).
    step = normalized(Temperature.m_from_dict(written))

    assert getattr(step, derived).magnitude == pytest.approx(expected)


def test_both_kinds_of_step_share_one_base():
    assert issubclass(PlannedMonitorControlStep, PlannedProcessStep)
    assert issubclass(BLOCK, PlannedProcessStep)
    assert {'name', 'estimated_duration'} <= set(
        PlannedProcessStep.m_def.all_quantities
    )


def test_only_monitor_control_steps_carry_tags():
    tags = {'monitor', 'control', 'setpoint', 'sample_every', 'sampling_rate'}

    assert tags <= set(PlannedMonitorControlStep.m_def.all_quantities)
    assert tags.isdisjoint(BLOCK.m_def.all_quantities)


def test_a_step_built_as_the_base_names_no_quantity(normalized, log):
    normalized(PlannedMonitorControlStep(name='stray'))

    [error] = log.errors
    assert 'stray is a bare `PlannedMonitorControlStep`' in error


def test_two_steps_on_one_quantity_are_not_merged(normalized, log):
    # Not "hold and log": siblings have equal scope, so nothing decides between them —
    # a contradiction, not two halves of one step (D13a, R4).
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'hot phase',
                'steps': [
                    entry(Temperature, control=True, setpoint=358.15),
                    entry(Temperature, monitor=True),
                ],
            }
        )
    )

    [error] = log.errors
    assert '2 Temperature steps overlap in hot phase' in error
    assert 'not merged' in error
    # Reported, never repaired: the steps stay as authored.
    assert [step.monitor for step in node.steps] == [None, True]


def test_two_steps_on_one_quantity_may_be_truly_subsequent(normalized, log):
    normalized(
        BLOCK.m_from_dict(
            {
                'steps': [
                    entry(Temperature, estimated_duration=3600),
                    entry(Temperature, estimated_duration=7200),
                ]
            }
        )
    )

    assert log.errors == []


def test_steps_on_different_quantities_do_not_overlap(normalized, log):
    # Voltage and current are tied by the cell, but that is physics, and the schema
    # holds none (§15.1).
    normalized(
        BLOCK.m_from_dict(
            {'steps': [entry(Voltage), entry(Current), entry(Irradiance)]}
        )
    )

    assert log.errors == []


def test_a_parallel_block_cannot_run_one_quantity_twice(normalized, log):
    normalized(
        BLOCK.m_from_dict(
            {
                'execution_mode': 'parallel',
                'steps': [
                    entry(Resistance, estimated_duration=3600),
                    entry(Resistance, estimated_duration=3600),
                ],
            }
        )
    )

    [error] = log.errors
    assert 'parallel' in error


def test_a_step_the_block_leaves_no_time_for_is_flagged(normalized, log):
    normalized(
        BLOCK.m_from_dict(
            {
                'name': 'phase',
                'estimated_duration': 1800000,
                'steps': [
                    entry(Temperature, estimated_duration=1800000),
                    entry(Temperature, name='cool down', estimated_duration=3600),
                ],
            }
        )
    )

    assert log.errors == []
    [warning] = log.warnings
    assert 'cool down never runs' in warning


def test_a_step_without_an_estimated_duration_takes_no_turn(normalized, log):
    normalized(
        BLOCK.m_from_dict(
            {
                'estimated_duration': 1800000,
                'steps': [
                    entry(Temperature, name='warm', control=True, setpoint=358.15),
                    entry(BLOCK, name='phase', estimated_duration=1800000),
                ],
            }
        )
    )

    assert (log.errors, log.warnings) == ([], [])


# R6: steps fitted to their block's duration (§15.4).


def test_a_step_that_outlasts_a_sequential_block_is_shortened(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'phase',
                'estimated_duration': 3600,
                'steps': [
                    entry(Temperature, name='warm', estimated_duration=1800),
                    entry(Temperature, name='hot', estimated_duration=3600),
                ],
            }
        )
    )

    # The time runs out during `hot`, so only `hot` is shortened, to what is left.
    assert [step.estimated_duration.magnitude for step in node.steps] == [1800, 1800]
    [warning] = log.warnings
    assert 'hot is shortened from 3600 s to 1800 s' in warning
    assert 'phase' in warning
    assert log.errors == []


def test_a_step_that_outlasts_a_parallel_block_is_shortened(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'fork',
                'execution_mode': 'parallel',
                'estimated_duration': 3600,
                'steps': [
                    entry(Temperature, name='long', estimated_duration=7200),
                    entry(Irradiance, name='short', estimated_duration=1800),
                ],
            }
        )
    )

    assert [step.estimated_duration.magnitude for step in node.steps] == [3600, 1800]
    [warning] = log.warnings
    assert 'long is shortened from 7200 s to 3600 s' in warning


def test_a_condition_keeps_lasting_as_long_as_its_block(normalized, log):
    # Giving it a duration would turn it into an episode that takes a turn (D13).
    node = normalized(
        BLOCK.m_from_dict(
            {
                'estimated_duration': 3600,
                'steps': [entry(Temperature, monitor=True)],
            }
        )
    )

    assert node.steps[0].estimated_duration is None
    assert log.warnings == []


# A missing duration is derived from the steps (§15.4).


def test_a_sequential_block_lasts_as_long_as_its_steps_together(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'steps': [
                    entry(Irradiance, monitor=True),
                    entry(Temperature, estimated_duration=1800),
                    entry(Voltage, estimated_duration=3600),
                ]
            }
        )
    )

    # The condition adds nothing: it lasts as long as the block (D13).
    assert node.estimated_duration.magnitude == pytest.approx(5400)
    assert (log.errors, log.warnings) == ([], [])


def test_a_parallel_block_lasts_as_long_as_its_longest_step(normalized):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'execution_mode': 'parallel',
                'steps': [
                    entry(Temperature, estimated_duration=7200),
                    entry(Irradiance, estimated_duration=1800),
                ],
            }
        )
    )

    assert node.estimated_duration.magnitude == pytest.approx(7200)


def test_a_block_whose_steps_have_no_duration_stays_without_one(normalized):
    node = normalized(BLOCK.m_from_dict({'steps': [entry(Temperature, monitor=True)]}))

    assert node.estimated_duration is None


def test_a_nested_block_is_measured_before_its_parent_adds_it_up(normalized):
    # NOMAD normalizes nested sections first (verified), so `inner` has its length when
    # the outer block adds it up.
    node = normalized(
        BLOCK.m_from_dict(
            {
                'steps': [
                    entry(
                        BLOCK,
                        name='inner',
                        steps=[
                            entry(Temperature, estimated_duration=1800),
                            entry(Irradiance, estimated_duration=1800),
                        ],
                    ),
                    entry(Voltage, estimated_duration=600),
                ]
            }
        )
    )

    assert [step.estimated_duration.magnitude for step in node.steps] == [3600, 600]
    assert node.estimated_duration.magnitude == pytest.approx(4200)


def test_entry_loads_the_bare_archive_file():
    archive = parse(os.path.join(DATA_DIR, 'channels.archive.yaml'))[0]
    normalize_all(archive)
    *settings, soak = archive.data.steps

    # What held for the whole run comes first, as conditions without a duration.
    assert [type(step) for step in settings] == [
        Temperature,
        Irradiance,
        Voltage,
        Current,
        Resistance,
    ]
    temperature, irradiance, voltage = settings[:3]
    assert temperature.estimated_duration is None
    assert (temperature.control, temperature.monitor) == (True, True)
    assert temperature.setpoint.to(ureg.degC).magnitude == pytest.approx(65)
    assert irradiance.spectrum == 'AM1.5G'
    assert (voltage.control, voltage.setpoint, voltage.monitor) == (None, None, True)

    assert isinstance(soak, BLOCK)
    assert [type(step) for step in soak.steps] == [
        Temperature,
        Temperature,
        Irradiance,
        Voltage,
    ]
    hot = soak.steps[0]
    assert hot.estimated_duration.to(ureg.hour).magnitude == pytest.approx(500)


# A block that repeats its steps (§15.8).


def test_a_block_runs_until_its_duration_is_up_unless_told_otherwise():
    assert BLOCK().repeat == 'until_end_of_duration'
    assert BLOCK(repeat='n_times').repeat == 'n_times'


def test_repeat_rejects_unknown_values():
    with pytest.raises(ValueError):
        BLOCK(repeat='forever')


def test_only_a_block_repeats():
    # An episode on one quantity is run again by the block around it, not by itself.
    fields = {'repeat', 'repeat_n', 'estimated_duration_one_iteration'}

    assert fields <= set(BLOCK.m_def.all_quantities)
    assert fields.isdisjoint(PlannedMonitorControlStep.m_def.all_quantities)


def test_n_iterations_last_as_long_as_all_of_them_together(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'daily cycle',
                'repeat': 'n_times',
                'repeat_n': 42,
                'estimated_duration_one_iteration': 86400,
                'steps': [entry(Temperature, estimated_duration=43200)],
            }
        )
    )

    assert node.estimated_duration.to(ureg.hour).magnitude == pytest.approx(42 * 24)
    assert (log.errors, log.warnings) == ([], [])


def test_an_iteration_lasts_as_long_as_its_steps_when_none_is_written(normalized, log):
    # A thermal cycle is then two steps and a count, and nothing else.
    node = normalized(
        BLOCK.m_from_dict(
            {
                'repeat': 'n_times',
                'repeat_n': 10,
                'steps': [
                    entry(Temperature, estimated_duration=3600),
                    entry(Irradiance, estimated_duration=1800),
                ],
            }
        )
    )

    assert node.estimated_duration_one_iteration.magnitude == pytest.approx(5400)
    assert node.estimated_duration.magnitude == pytest.approx(54000)
    assert (log.errors, log.warnings) == ([], [])


def test_the_steps_are_fitted_to_one_iteration_not_to_all_of_them(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'cycle',
                'repeat': 'n_times',
                'repeat_n': 10,
                'estimated_duration_one_iteration': 3600,
                'steps': [entry(Temperature, name='hot', estimated_duration=7200)],
            }
        )
    )

    # Against all ten iterations together, 2 h would have looked as if it fitted.
    assert node.steps[0].estimated_duration.magnitude == pytest.approx(3600)
    [warning] = log.warnings
    assert 'hot is shortened from 7200 s to 3600 s' in warning


def test_a_duration_that_contradicts_the_iterations_is_reported(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'cycle',
                'repeat': 'n_times',
                'repeat_n': 10,
                'estimated_duration_one_iteration': 3600,
                'estimated_duration': 7200,
                'steps': [entry(Temperature, estimated_duration=3600)],
            }
        )
    )

    # Reported, never repaired: the authored duration stands (D13a).
    assert node.estimated_duration.magnitude == pytest.approx(7200)
    [error] = log.errors
    assert '10 iterations of 3600 s last 36000 s' in error


def test_n_times_without_a_count_is_reported(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'cycle',
                'repeat': 'n_times',
                'steps': [entry(Temperature, estimated_duration=3600)],
            }
        )
    )

    assert node.estimated_duration is None
    [error] = log.errors
    assert 'no `repeat_n`' in error


def test_a_block_runs_at_least_once(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'cycle',
                'repeat': 'n_times',
                'repeat_n': 0,
                'steps': [entry(Temperature, estimated_duration=3600)],
            }
        )
    )

    assert node.estimated_duration is None
    [error] = log.errors
    assert 'at least once' in error


def test_a_count_without_n_times_has_no_effect(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'phase',
                'repeat_n': 42,
                'steps': [entry(Temperature, estimated_duration=3600)],
            }
        )
    )

    # The block lasts one pass, as it always did.
    assert node.estimated_duration.magnitude == pytest.approx(3600)
    [warning] = log.warnings
    assert '`repeat_n`' in warning
    assert 'no effect' in warning
