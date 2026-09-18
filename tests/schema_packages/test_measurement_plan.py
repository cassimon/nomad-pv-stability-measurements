"""A stability protocol run as a measurement: its instructions laid out as one flat list
of steps, each carrying a time series per controlled or monitored quantity."""

from datetime import datetime, timedelta, timezone

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    CountingRepeatingBlock,
    TimedRepeatingBlock,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldIrradiance,
    HoldTemperature,
)
from nomad_pv_stability_measurements.schema_packages.measurement_plan import (
    StabilityMeasurement,
    StabilityProtocolMeasurementPlan,
)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = 3600 * ureg.second


def light(hours):
    """Light for `hours`; for ever if `None`."""
    duration = None if hours is None else hours * HOUR
    return HoldIrradiance(name='light', set_point=1000, control=True, duration=duration)


def dark(hours):
    return HoldIrradiance(name='dark', set_point=0, control=True, duration=hours * HOUR)


def measured(normalized, instructions, hours, **plan_fields):
    plan = normalized(
        StabilityProtocolMeasurementPlan(instructions=instructions, **plan_fields)
    )
    return plan.create_activity(
        name='run 1', datetime=START, datetime_end=START + timedelta(hours=hours)
    )


@pytest.mark.parametrize(
    ('instructions', 'hours', 'plan_fields', 'steps'),
    [
        # A setting holds throughout; the routine's instructions each start a step.
        (
            [
                HoldTemperature(name='hot', set_point=338.15, control=True),
                CountingRepeatingBlock(
                    repeat_n=2, sub_instructions=[light(1), dark(1)]
                ),
            ],
            5,
            {},
            [
                (0, 1, 'hot, light'),
                (1, 1, 'dark'),
                (2, 1, 'light'),
                (3, 1, 'dark'),
                (4, 1, 'hot'),
            ],
        ),
        # A timed block stops its instructions wherever they are.
        (
            [
                TimedRepeatingBlock(
                    repeat_duration=3 * HOUR, sub_instructions=[light(2), dark(2)]
                )
            ],
            5,
            {},
            [(0, 2, 'light'), (2, 1, 'dark')],
        ),
        # The plan's own duration stops the run before the caller's end.
        (
            [
                CountingRepeatingBlock(sub_instructions=[light(1), dark(1)]),
            ],
            5,
            {'duration': 1.5 * HOUR},
            [(0, 1, 'light'), (1, 0.5, 'dark')],
        ),
    ],
)
def test_the_plan_is_laid_out_as_a_step_wherever_an_instruction_starts_or_ends(
    normalized, instructions, hours, plan_fields, steps
):
    measurement = measured(normalized, instructions, hours, **plan_fields)

    assert [
        (
            step.elapsed_at_start.to('hour').magnitude,
            step.duration.to('hour').magnitude,
            step.name,
        )
        for step in measurement.steps
    ] == steps
    assert measurement.steps[1].start_time == START + timedelta(hours=steps[1][0])


def test_a_quantity_follows_the_innermost_instruction_and_is_logged_as_its_setting_says(
    normalized,
):
    setting = HoldTemperature(
        name='hot', set_point=338.15, control=True, monitor=True, sample_every=60
    )
    episode = HoldTemperature(name='hotter', set_point=358.15, control=True)
    measurement = measured(
        normalized,
        [setting, CountingRepeatingBlock(repeat_n=1, sub_instructions=[episode])],
        2,
    )
    [step] = measurement.steps
    series = step.temperature

    assert series.instruction.name == 'hotter'
    assert (series.controlled, series.monitored) == (True, True)
    assert series.sample_every.to('s').magnitude == pytest.approx(60)
    assert step.instructions == ['hotter']


def test_a_quantity_neither_controlled_nor_monitored_has_no_series(normalized):
    measurement = measured(normalized, [HoldTemperature(name='idle')], 1)

    assert measurement.steps[0].series() == {}


def test_a_plan_that_never_ends_needs_the_callers_end(normalized):
    plan = normalized(StabilityProtocolMeasurementPlan(instructions=[light(None)]))

    with pytest.raises(ValueError, match='never ends on its own'):
        plan.create_activity(name='run 1', datetime=START)


def test_the_measurement_keeps_the_plan_as_it_was_run(normalized):
    plan = normalized(
        StabilityProtocolMeasurementPlan(
            standard='ISOS-LC-2', location='Lab A', instructions=[light(1)]
        )
    )
    measurement = plan.create_activity(name='run 1', datetime=START)

    assert isinstance(measurement, StabilityMeasurement)
    assert measurement.protocol is measurement.plan
    assert measurement.plan is not plan
    assert measurement.steps[0].irradiance.instruction.m_parent is measurement.plan
    assert (measurement.method, measurement.location) == ('ISOS-LC-2', 'Lab A')
