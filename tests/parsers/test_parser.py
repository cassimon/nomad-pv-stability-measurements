"""The whole path: an authored file, through NOMAD, into a normalized entry."""

import os
from unittest.mock import MagicMock

import pytest
from nomad.client import normalize_all, parse
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.parser import StabilityYamlParser
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


def test_nomad_reads_an_authored_file_into_a_protocol_entry():
    archive = parse(os.path.join(DATA_DIR, 'channels.stability.yaml'))[0]
    normalize_all(archive)
    *settings, soak = archive.data.instructions

    assert isinstance(archive.data, StabilityProtocol)
    assert isinstance(soak.sub_instructions[3], HoldVoltage)
    assert soak.sub_instructions[3].set_point.to(ureg.volt).magnitude == (
        pytest.approx(0.8)
    )
    # One pass of the routine: 500 h + 100 h + 100 h + 24 h + 1 h. The settings last as
    # long as it, and so does the protocol.
    assert soak.duration.value.to(ureg.hour).magnitude == pytest.approx(725)
    assert archive.data.duration.value.to(ureg.hour).magnitude == pytest.approx(725)


def test_a_file_with_options_is_one_entry_per_variant(tmp_path):
    mainfile = tmp_path / 'P.stability.yaml'
    mainfile.write_text(
        'data:\n'
        '  name: P\n'
        '  channel_settings:\n'
        '    temperature: {options: [{hold: 65 °C}, {hold: 85 °C}]}\n'
    )

    main, *children = parse(str(mainfile))

    assert main.data is None
    assert {child.metadata.mainfile_key: child.data.name for child in children} == {
        'P (65 °C)': 'P (65 °C)',
        'P (85 °C)': 'P (85 °C)',
    }


def test_problems_are_logged_with_their_path_and_the_rest_still_loads(tmp_path):
    mainfile = tmp_path / 'typo.stability.yaml'
    mainfile.write_text(
        'data:\n  routine:\n    instructions:\n      - {channel: temperature, duraton: 1 h}\n'
    )
    logger = MagicMock()
    archive = EntryArchive(metadata=EntryMetadata())

    StabilityYamlParser().parse(str(mainfile), archive, logger)

    [(message,), details] = logger.error.call_args
    assert details == {'path': 'data.routine.instructions[0].duraton'}
    assert 'Did you mean `duration`?' in message
    assert isinstance(archive.data.instructions[0].sub_instructions[0], HoldTemperature)
