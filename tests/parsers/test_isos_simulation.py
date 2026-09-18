"""A protocol after an ISOS standard gets a simulated run of it when it is parsed, as
an entry of its own that references the protocol's entry."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from nomad.datamodel import EntryArchive, EntryMetadata

from nomad_pv_stability_measurements.parsers.isos_simulation import (
    RUN_LENGTH,
    StabilityYamlSimulatingParser,
)
from nomad_pv_stability_measurements.schema_packages.measurement_plan import (
    StabilityMeasurement,
)

LIGHT_SOAK = (
    '  channel_settings:\n'
    '    temperature: {hold: 65 °C}\n'
    '  routine:\n'
    '    repeat: indefinitely\n'
    '    instructions:\n'
    '      - {channel: irradiation, hold: 1 sun, duration: 1 h}\n'
    '      - {channel: irradiation, hold: dark, duration: 1 h}\n'
)


def protocol_file(tmp_path, standard, options=False):
    mainfile = tmp_path / 'P.stability.yaml'
    temperature = (
        '    temperature: {options: [{hold: 65 °C}, {hold: 85 °C}]}\n'
        if options
        else '    temperature: {hold: 65 °C}\n'
    )
    mainfile.write_text(
        f'data:\n  name: P\n  standard: {standard}\n'
        + LIGHT_SOAK.replace('    temperature: {hold: 65 °C}\n', temperature)
    )
    return str(mainfile)


def matched(mainfile):
    return StabilityYamlSimulatingParser(
        name='test', mainfile_name_re=r'.*\.stability\.yaml$'
    ).is_mainfile(mainfile, 'text/plain', b'', '')


@pytest.mark.parametrize(
    ('standard', 'options', 'entries'),
    [
        # The file's own entry is the protocol; its run is a child.
        ('ISOS-L-2', False, {'P (simulated)'}),
        # One protocol per variant, and one run of each.
        (
            'ISOS-L-2',
            True,
            {
                'P (65 °C)',
                'P (85 °C)',
                'P (65 °C) (simulated)',
                'P (85 °C) (simulated)',
            },
        ),
        # Not an ISOS standard: the protocols only.
        ('IEC 61215', True, {'P (65 °C)', 'P (85 °C)'}),
        ('IEC 61215', False, True),
    ],
)
def test_a_protocol_after_an_isos_standard_gets_an_entry_for_its_simulated_run(
    tmp_path, standard, options, entries
):
    assert matched(protocol_file(tmp_path, standard, options)) == entries


def test_the_simulated_run_references_the_protocol_entry_and_lasts_1000_h(tmp_path):
    mainfile = protocol_file(tmp_path, 'ISOS-LC-2')
    protocol = EntryArchive(metadata=EntryMetadata(entry_id='protocol-entry'))
    run = EntryArchive(metadata=EntryMetadata(entry_id='run-entry'))

    StabilityYamlSimulatingParser().parse(
        mainfile, protocol, MagicMock(), {'P (simulated)': run}
    )
    measurement = run.data

    assert isinstance(measurement, StabilityMeasurement)
    assert measurement.m_to_dict()['protocol'] == (
        '../upload/archive/protocol-entry#/data'
    )
    assert measurement.name == 'P (simulated)'
    # Generated when parsed.
    assert datetime.now(timezone.utc) - measurement.datetime < timedelta(minutes=1)
    # It never ends on its own, so it runs for the whole horizon: 1 h light, 1 h dark.
    assert len(measurement.steps) == RUN_LENGTH / timedelta(hours=1)
