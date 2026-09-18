"""A simulated run of a plan: the example upload, through NOMAD, into a measurement."""

import os
from unittest.mock import MagicMock

import numpy as np
from nomad.client import normalize_all, parse
from nomad.datamodel import EntryArchive, EntryMetadata

from nomad_pv_stability_measurements.parsers.simulation_parser import (
    NOISE,
    StabilitySimulationParser,
)
from nomad_pv_stability_measurements.schema_packages.measurement_plan import (
    StabilityMeasurement,
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
    # Whatever is monitored is measured, whatever is controlled is set, when sampled.
    for each in series:
        assert (each.value is not None) == each.monitored
        assert (each.set_value is not None) == (
            each.controlled and each.m_def.name != 'PowerSeries'
        )
        for values in (each.value, each.set_value):
            assert values is None or len(values) == len(each.time)
    # The cell delivers no power in the dark: what is measured is only noise.
    dark = measurement.steps[1].power.value.to('W').magnitude
    assert np.abs(dark).max() < 5 * NOISE['power']
    assert [figure.label for figure in measurement.figures] == ['Time series']


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
