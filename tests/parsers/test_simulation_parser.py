"""A simulated run of a plan: the example upload, through NOMAD, into a measurement."""

import os
from unittest.mock import MagicMock

import numpy as np
import pytest
from nomad.client import normalize_all, parse
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.simulation_parser import (
    StabilitySimulationParser,
    set_value,
)
from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.measurement_plan import (
    StabilityMeasurement,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import MPPTracking
from nomad_pv_stability_measurements.schema_packages.ramp_instructions import (
    RampTemperature,
)

EXAMPLE = os.path.join(
    os.path.dirname(__file__),
    '..',
    '..',
    'src',
    'nomad_pv_stability_measurements',
    'example_uploads',
    'simulation',
    'cell-a.simulation.yaml',
)


def test_nomad_simulates_a_run_of_the_example_plan():
    archive = parse(EXAMPLE)[0]
    normalize_all(archive)
    measurement = archive.data
    series = [each for step in measurement.steps for each in step.series().values()]

    assert isinstance(measurement, StabilityMeasurement)
    # 24 h of 1 h light, 1 h dark: a step each.
    assert [step.duration.to('hour').magnitude for step in measurement.steps] == [
        1
    ] * 24
    assert {step.irradiance.set_value.magnitude[0] for step in measurement.steps} == {
        1000,
        0,
    }
    # Only what can be known without a model of the cell or its surroundings: the set
    # values the plan states. Nothing is measured, and a tracker's value is the cell's.
    assert {
        name: each.set_value is not None
        for name, each in measurement.steps[0].series().items()
    } == {
        'temperature': True,
        'irradiance': True,
        'power': False,
        'relative_humidity': False,
    }
    for each in series:
        assert each.value is None
        assert each.set_value is None or len(each.set_value) == len(each.time)
    assert [row['name'] for row in measurement.figures[0].figure['data']] == [
        'temperature (set value)',
        'irradiance (set value)',
        # Which step runs when, by its index: 24 steps, the last to the run's end.
        'step',
    ]
    [*_, steps] = measurement.figures[0].figure['data']
    assert (steps['y'][0], steps['y'][-1], steps['x'][-1]) == (0, 23, 24)


def test_a_plan_with_options_needs_a_variant(tmp_path):
    (tmp_path / 'P.stability.yaml').write_text(
        'data:\n'
        '  name: P\n'
        '  channel_settings:\n'
        '    temperature: {options: [{hold: 65 °C}, {hold: 85 °C}]}\n'
    )
    mainfile = tmp_path / 'run.simulation.yaml'
    mainfile.write_text(
        'simulation:\n'
        '  protocol: P.stability.yaml\n'
        '  start: 2026-01-01T00:00:00Z\n'
        '  duration: 1 h\n'
    )
    logger = MagicMock()
    archive = EntryArchive(metadata=EntryMetadata())

    StabilitySimulationParser().parse(str(mainfile), archive, logger)

    [(message,), _] = logger.error.call_args
    assert 'name one as `variant`' in message
    assert 'P (65 °C)' in message
    assert archive.data is None


K_PER_S = ureg.kelvin / ureg.second


@pytest.mark.parametrize(
    ('instruction', 'expected'),
    [
        (HoldTemperature(set_point=338.15), [338.15, 338.15, 338.15]),
        # 300 K → 310 K at 1 K/s, then back at the same rate.
        (
            RampTemperature(
                start_point=300,
                end_point=310,
                ramp_rate=1 * K_PER_S,
                end_of_ramp_behavior='triangle',
            ),
            [300, 310, 305],
        ),
        # Not stated by the plan: a point on the cell's characteristic, what a tracker
        # finds, a bound, and a cycle by an unstated path.
        (HoldVoltage(reference_point='near V_MPP'), None),
        (MPPTracking(), None),
        (HoldBetweenIrradiance(lower_bound=800, upper_bound=1000), None),
        (
            RampTemperature(
                start_point=300,
                end_point=310,
                ramp_rate=1 * K_PER_S,
                end_of_ramp_behavior='cycle',
            ),
            None,
        ),
    ],
)
def test_only_a_value_the_plan_states_is_set(instruction, expected):
    value = set_value(instruction, np.array([0.0, 10.0, 15.0]))

    if expected is None:
        assert value is None
    else:
        assert value.to('K').magnitude == pytest.approx(expected)
