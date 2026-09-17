"""The steps and the block, tested on bare dicts: `m_def` written out, numbers in the
declared unit (Design.md §15.1). How an authored file gets here is tests/parsers."""

import os

import pytest
from nomad.client import normalize_all, parse
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import PlannedProcessStep
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldCurrent,
    HoldIrradiance,
    HoldResistance,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.mpp_steps import VOCTracking
from nomad_pv_stability_measurements.schema_packages.ramp_steps import RampTemperature
from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedMonitorControlStep,
    PlannedSubroutineStep,
    RampStep,
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
    step = normalized(HoldTemperature.m_from_dict(written))

    assert getattr(step, derived).magnitude == pytest.approx(expected)


def test_both_kinds_of_step_share_one_base():
    assert issubclass(PlannedMonitorControlStep, PlannedProcessStep)
    assert issubclass(BLOCK, PlannedProcessStep)
    assert {'name', 'estimated_duration'} <= set(
        PlannedProcessStep.m_def.all_quantities
    )


def test_only_monitor_control_steps_carry_tags():
    tags = {'monitor', 'control', 'sample_every', 'sampling_rate'}

    assert tags <= set(PlannedMonitorControlStep.m_def.all_quantities)
    assert tags.isdisjoint(BLOCK.m_def.all_quantities)
    # What a step holds or moves sits on its kind, not on the base (§15.11).
    assert {'set_point', 'start_point'}.isdisjoint(
        PlannedMonitorControlStep.m_def.all_quantities
    )


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
                    entry(HoldTemperature, control=True, set_point=358.15),
                    entry(HoldTemperature, monitor=True),
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
                    entry(HoldTemperature, estimated_duration=3600),
                    entry(HoldTemperature, estimated_duration=7200),
                ]
            }
        )
    )

    assert log.errors == []


def test_steps_on_different_quantities_do_not_overlap(normalized, log):
    # HoldVoltage and current are tied by the cell, but that is physics, and the schema
    # holds none (§15.1).
    normalized(
        BLOCK.m_from_dict(
            {'steps': [entry(HoldVoltage), entry(HoldCurrent), entry(HoldIrradiance)]}
        )
    )

    assert log.errors == []


def test_a_parallel_block_cannot_run_one_quantity_twice(normalized, log):
    normalized(
        BLOCK.m_from_dict(
            {
                'execution_mode': 'parallel',
                'steps': [
                    entry(HoldResistance, estimated_duration=3600),
                    entry(HoldResistance, estimated_duration=3600),
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
                    entry(HoldTemperature, estimated_duration=1800000),
                    entry(HoldTemperature, name='cool down', estimated_duration=3600),
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
                    entry(HoldTemperature, name='warm', control=True, set_point=358.15),
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
                    entry(HoldTemperature, name='warm', estimated_duration=1800),
                    entry(HoldTemperature, name='hot', estimated_duration=3600),
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
                    entry(HoldTemperature, name='long', estimated_duration=7200),
                    entry(HoldIrradiance, name='short', estimated_duration=1800),
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
                'steps': [entry(HoldTemperature, monitor=True)],
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
                    entry(HoldIrradiance, monitor=True),
                    entry(HoldTemperature, estimated_duration=1800),
                    entry(HoldVoltage, estimated_duration=3600),
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
                    entry(HoldTemperature, estimated_duration=7200),
                    entry(HoldIrradiance, estimated_duration=1800),
                ],
            }
        )
    )

    assert node.estimated_duration.magnitude == pytest.approx(7200)


def test_a_block_whose_steps_have_no_duration_stays_without_one(normalized):
    node = normalized(
        BLOCK.m_from_dict({'steps': [entry(HoldTemperature, monitor=True)]})
    )

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
                            entry(HoldTemperature, estimated_duration=1800),
                            entry(HoldIrradiance, estimated_duration=1800),
                        ],
                    ),
                    entry(HoldVoltage, estimated_duration=600),
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
        HoldTemperature,
        HoldIrradiance,
        HoldVoltage,
        HoldCurrent,
        HoldResistance,
    ]
    temperature, irradiance, voltage = settings[:3]
    assert temperature.estimated_duration is None
    assert (temperature.control, temperature.monitor) == (True, True)
    assert temperature.set_point.to(ureg.degC).magnitude == pytest.approx(65)
    assert irradiance.spectrum == 'AM1.5G'
    assert (voltage.control, voltage.set_point, voltage.monitor) == (None, None, True)

    assert isinstance(soak, BLOCK)
    assert [type(step) for step in soak.steps] == [
        HoldTemperature,
        HoldTemperature,
        HoldIrradiance,
        HoldVoltage,
        # The example's `open_circuit`, which now reaches a step of its own (§15.13).
        VOCTracking,
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
                'steps': [entry(HoldTemperature, estimated_duration=43200)],
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
                    entry(HoldTemperature, estimated_duration=3600),
                    entry(HoldIrradiance, estimated_duration=1800),
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
                'steps': [entry(HoldTemperature, name='hot', estimated_duration=7200)],
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
                'steps': [entry(HoldTemperature, estimated_duration=3600)],
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
                'steps': [entry(HoldTemperature, estimated_duration=3600)],
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
                'steps': [entry(HoldTemperature, estimated_duration=3600)],
            }
        )
    )

    assert node.estimated_duration is None
    [error] = log.errors
    assert 'at least once' in error


# A ramp: both ends, and the rate the duration says (§15.11).


def test_a_ramp_needs_both_its_ends(normalized, log):
    normalized(RampTemperature(name='warm up', start_point=298.15 * ureg.kelvin))

    [error] = log.errors
    assert 'warm up moves between two values but is missing an end' in error


def test_a_ramp_derives_its_rate_from_its_duration(normalized, log):
    step = normalized(
        RampTemperature(
            start_point=298.15 * ureg.kelvin,
            end_point=358.15 * ureg.kelvin,
            estimated_duration=3600 * ureg.second,
        )
    )

    # 60 K in an hour, whichever way round the ends were written.
    assert step.ramp_rate.to(ureg.kelvin / ureg.hour).magnitude == pytest.approx(60)
    assert (log.errors, log.warnings) == ([], [])


def test_a_ramp_derives_its_duration_from_its_rate(normalized, log):
    step = normalized(
        RampTemperature(
            start_point=358.15 * ureg.kelvin,
            end_point=298.15 * ureg.kelvin,
            ramp_rate=60 * ureg.kelvin / ureg.hour,
        )
    )

    # Cooling down: the rate is a magnitude, the direction is the ends (D16).
    assert step.estimated_duration.to(ureg.hour).magnitude == pytest.approx(1)
    assert (log.errors, log.warnings) == ([], [])


def test_a_rate_that_contradicts_the_duration_is_reported(normalized, log):
    step = normalized(
        RampTemperature(
            name='warm up',
            start_point=298.15 * ureg.kelvin,
            end_point=358.15 * ureg.kelvin,
            ramp_rate=60 * ureg.kelvin / ureg.hour,
            estimated_duration=7200 * ureg.second,
        )
    )

    # Reported, never repaired: both stand as authored (D13a).
    assert step.estimated_duration.to(ureg.hour).magnitude == pytest.approx(2)
    [error] = log.errors
    assert 'warm up writes a `ramp_rate`' in error


def test_a_ramp_with_neither_a_rate_nor_a_duration_lasts_as_its_block_does(
    normalized, log
):
    step = normalized(
        RampTemperature(
            start_point=298.15 * ureg.kelvin, end_point=358.15 * ureg.kelvin
        )
    )

    # A condition, like any other step without a duration (D13).
    assert (step.estimated_duration, step.ramp_rate) == (None, None)
    assert (log.errors, log.warnings) == ([], [])


# A ramp that repeats is a cycle, and one member of them states no path (§21.2).


def test_a_cycle_by_an_unstated_path_is_a_ramp_that_says_so(normalized, log):
    step = normalized(
        RampTemperature(
            start_point=296.15 * ureg.kelvin,
            end_point=338.15 * ureg.kelvin,
            end_of_ramp_behavior='cycle',
            estimated_duration=3600 * ureg.second,
        )
    )

    # No path, so no rate along it is derived from the duration.
    assert step.ramp_rate is None
    assert (log.errors, log.warnings) == ([], [])


def test_a_cycle_by_an_unstated_path_takes_no_rate(normalized, log):
    step = normalized(
        RampTemperature(
            name='thermal cycle',
            start_point=296.15 * ureg.kelvin,
            end_point=338.15 * ureg.kelvin,
            end_of_ramp_behavior='cycle',
            ramp_rate=60 * ureg.kelvin / ureg.hour,
        )
    )

    # Reported, never repaired, and no duration derived from it (D13a).
    assert step.estimated_duration is None
    [error] = log.errors
    assert 'thermal cycle cycles by a path the protocol does not state' in error


def test_a_cycle_still_needs_both_its_ends(normalized, log):
    normalized(
        RampTemperature(
            name='thermal cycle',
            start_point=296.15 * ureg.kelvin,
            end_of_ramp_behavior='cycle',
        )
    )

    [error] = log.errors
    assert 'thermal cycle moves between two values but is missing an end' in error


def test_a_step_built_as_a_bare_kind_names_no_quantity(normalized, log):
    normalized(RampStep(name='stray'))

    [error] = log.errors
    assert 'stray is a bare `RampStep`' in error


def test_a_count_without_n_times_has_no_effect(normalized, log):
    node = normalized(
        BLOCK.m_from_dict(
            {
                'name': 'phase',
                'repeat_n': 42,
                'steps': [entry(HoldTemperature, estimated_duration=3600)],
            }
        )
    )

    # The block lasts one pass, as it always did.
    assert node.estimated_duration.magnitude == pytest.approx(3600)
    [warning] = log.warnings
    assert '`repeat_n`' in warning
    assert 'no effect' in warning


# A block that repeats until the protocol ends (§20.1).


def light_dark_cycle(**fields) -> PlannedSubroutineStep:
    block = BLOCK(repeat='until_end_of_protocol', **fields)
    block.steps = [
        HoldIrradiance(control=True, estimated_duration=8 * ureg.hour),
        HoldIrradiance(
            control=True,
            set_point=0 * ureg('W/m^2'),
            estimated_duration=16 * ureg.hour,
        ),
    ]
    return block


def test_a_block_until_the_end_of_the_protocol_claims_no_length(normalized, log):
    block = normalized(light_dark_cycle(name='cycle'))

    # One iteration is the cycle the standard states; how many is not stated.
    assert block.estimated_duration_one_iteration.to(ureg.hour).magnitude == (
        pytest.approx(24)
    )
    assert block.estimated_duration is None
    assert (log.errors, log.warnings) == ([], [])


def test_nothing_around_it_claims_a_length_either(normalized, log):
    outer = BLOCK(name='routine')
    outer.steps = [light_dark_cycle()]

    normalized(outer)

    assert outer.estimated_duration is None


@pytest.mark.parametrize(
    'written', [{'repeat_n': 3}, {'estimated_duration': 48 * ureg.hour}]
)
def test_a_count_or_a_length_there_has_no_effect(normalized, log, written):
    block = normalized(light_dark_cycle(name='cycle', **written))

    [warning] = log.warnings
    assert f'cycle writes `{next(iter(written))}`' in warning
    assert 'repeats until the end of the protocol' in warning
    # Reported, never repaired: what was written stands (D13a).
    assert block.estimated_duration_one_iteration.to(ureg.hour).magnitude == (
        pytest.approx(24)
    )


def test_its_one_iteration_is_still_checked(normalized, log):
    block = BLOCK(name='cycle', repeat='until_end_of_protocol')
    block.steps = [HoldIrradiance(), HoldIrradiance()]

    normalized(block)

    [error] = log.errors
    assert '2 Irradiance steps overlap in cycle' in error
