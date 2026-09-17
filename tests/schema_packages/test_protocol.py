"""The stability protocol: a plan whose instructions all start together (Design.md §23),
and what it records about the standard and the place (§15.12, §18.1, §20.7)."""

import os

import pytest
from nomad.client import normalize_all, parse
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.translate import translate
from nomad_pv_stability_measurements.schema_packages.general import Plan
from nomad_pv_stability_measurements.schema_packages.protocol import (
    GeoLocation,
    StabilityProtocol,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


def loaded(normalized, channel_settings: dict) -> StabilityProtocol:
    """A protocol written as `channel_settings`, translated, loaded and normalized."""
    archive = translate({'data': {'channel_settings': channel_settings}}).archive
    protocol = StabilityProtocol.m_from_dict(archive['data'])
    normalized(protocol.instruction_block)
    return normalized(protocol)


def test_a_protocol_is_a_plan_whose_instructions_all_start_together(normalized):
    protocol = loaded(
        normalized,
        {
            'temperature': {'hold': '65 °C', 'duration': '30 min'},
            'irradiation': {'hold': 'dark', 'duration': '1 h'},
        },
    )

    assert isinstance(protocol, Plan)
    assert protocol.estimated_duration.to('s').magnitude == pytest.approx(3600)


def test_settings_that_never_finish_give_the_protocol_no_end(normalized):
    protocol = loaded(
        normalized,
        {
            'irradiation': {'monitor': True},
            'temperature': {'hold': '65 °C', 'duration': '30 min'},
        },
    )

    assert protocol.estimated_duration is None


@pytest.mark.parametrize(
    ('fields', 'level'),
    [
        ({'standard': 'ISOS-D-1'}, 1),
        ({'standard': 'ISOS-LC-3I'}, 3),
        ({'standard': 'IEC 61215'}, None),
        # Written, it stands.
        ({'standard': 'ISOS-L-3', 'standard_level': 2}, 2),
    ],
)
def test_the_level_is_derived_from_an_isos_designation(normalized, fields, level):
    assert normalized(StabilityProtocol(**fields)).standard_level == level


def test_a_protocol_is_indoors_unless_it_says_otherwise():
    assert StabilityProtocol().environment == 'indoor'
    with pytest.raises(ValueError):
        StabilityProtocol(environment='in orbit')


def test_coordinates_the_wrong_way_round_are_reported(normalized, log):
    normalized(
        GeoLocation(latitude=-104.99 * ureg.degree, longitude=39.74 * ureg.degree)
    )

    [error] = log.errors
    assert 'wrong way round' in error


def test_a_bare_archive_file_loads_through_nomad():
    archive = parse(os.path.join(DATA_DIR, 'tree.archive.yaml'))[0]
    normalize_all(archive)
    [root] = archive.data.instruction_block.sub_instructions

    assert isinstance(archive.data, StabilityProtocol)
    assert [block.name for block in root.sub_instructions] == ['A', 'fork', 'D']
    assert root.sub_instructions[1].sub_instruction_execution_mode == 'parallel'
