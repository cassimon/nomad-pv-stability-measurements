"""The whole path: an authored file, through the parser, into a normalized entry."""

import os
from unittest.mock import MagicMock

import pytest
from nomad.client import normalize_all, parse
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.parser import StabilityYamlParser
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldIrradiance,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
#: The routine's block comes after the five settings steps (§15.2).
ROUTINE = 5


def test_the_parser_reads_an_authored_file_into_an_entry():
    logger = MagicMock()
    archive = EntryArchive(metadata=EntryMetadata())

    StabilityYamlParser().parse(
        os.path.join(DATA_DIR, 'channels.stability.yaml'), archive, logger
    )
    normalize_all(archive)

    # The example's `open_circuit` has no place in the schema, and says so (§15.2).
    [call] = logger.error.call_args_list
    assert call.kwargs == {'path': 'data.routine.commands[4].hold'}
    assert 'open_circuit' in call.args[0]
    assert isinstance(archive.data, StabilityProtocol)
    held = archive.data.steps[ROUTINE].steps[3]
    assert isinstance(held, HoldVoltage)
    assert held.setpoint.to(ureg.volt).magnitude == pytest.approx(0.8)


def test_problems_are_logged_with_their_path(tmp_path):
    mainfile = tmp_path / 'typo.stability.yaml'
    mainfile.write_text(
        'data:\n  routine:\n    commands:\n      - {channel: temperature, duraton: 1 h}\n'
    )
    logger = MagicMock()
    archive = EntryArchive(metadata=EntryMetadata())

    StabilityYamlParser().parse(str(mainfile), archive, logger)

    [(message,), details] = logger.error.call_args
    assert details == {'path': 'data.routine.commands[0].duraton'}
    assert 'Did you mean `duration`?' in message
    # The rest of the file still loads.
    assert isinstance(archive.data.steps[0].steps[0], HoldTemperature)


def test_nomad_matches_an_authored_file_to_this_parser():
    # Through NOMAD's own matching, not a hand-picked parser (§13.1a, step 5).
    archive = parse(os.path.join(DATA_DIR, 'channels.stability.yaml'))[0]

    assert isinstance(archive.data, StabilityProtocol)
    dark = archive.data.steps[ROUTINE].steps[2]
    assert isinstance(dark, HoldIrradiance)
    assert dark.setpoint.magnitude == pytest.approx(0)
