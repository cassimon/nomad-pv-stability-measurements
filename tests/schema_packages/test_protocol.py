"""The stability protocol: a plan whose instructions all start together (Design.md §23),
and what it records about the standard and the place (§15.12, §18.1, §20.7)."""

import os
from datetime import datetime, timezone

import pytest
from nomad.client import normalize_all, parse
from nomad.datamodel.metainfo.basesections.v2 import ActivityStep
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import Duration, Plan
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldIrradiance,
    HoldTemperature,
)
from nomad_pv_stability_measurements.schema_packages.protocol import (
    GeoLocation,
    StabilityActivity,
    StabilityProtocol,
)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fixed(seconds) -> Duration:
    return Duration(kind='fixed', value=seconds * ureg.second)


def whole_block() -> Duration:
    return Duration(kind='whole_block')


def executed(protocol, **given):
    activity = StabilityActivity(name='run 1', datetime=START, plan=protocol, **given)
    activity.populate_from_plan()
    return activity


DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


def test_a_protocol_is_a_plan_whose_instructions_all_start_together(normalized):
    protocol = normalized(
        StabilityProtocol(
            instructions=[
                HoldTemperature(duration=fixed(1800)),
                HoldIrradiance(duration=fixed(3600)),
            ]
        )
    )

    assert isinstance(protocol, Plan)
    assert protocol.seconds() == pytest.approx(3600)


def test_settings_last_as_long_as_what_finishes_beside_them(normalized):
    protocol = normalized(
        StabilityProtocol(
            instructions=[
                HoldIrradiance(monitor=True, duration=whole_block()),
                HoldTemperature(duration=fixed(1800)),
            ]
        )
    )

    assert protocol.seconds() == pytest.approx(1800)


def test_settings_alone_give_the_protocol_no_end(normalized):
    protocol = normalized(
        StabilityProtocol(
            instructions=[HoldIrradiance(monitor=True, duration=whole_block())]
        )
    )

    assert protocol.duration.kind == 'open_ended'


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


def test_executed_what_the_caller_says_stands():
    protocol = StabilityProtocol(
        name='protocol', description='planned', standard='ISOS-L-2', location='Lab A'
    )

    activity = executed(
        protocol,
        description='the first run',
        method='soak',
        location='Lab B',
        steps=[ActivityStep(name='light on')],
    )

    assert isinstance(activity, StabilityActivity)
    assert activity.plan is protocol
    assert (activity.name, activity.description) == ('run 1', 'the first run')
    assert (activity.method, activity.location) == ('soak', 'Lab B')
    assert [step.name for step in activity.steps] == ['light on']
    # Only planned, so not claimed: the end is the caller's to say.
    assert activity.datetime_end is None


def test_executed_it_fills_in_what_the_caller_leaves_out(normalized):
    protocol = normalized(
        StabilityProtocol(
            standard='ISOS-L-2',
            location='Lab A',
            instructions=[
                HoldTemperature(name='hot', duration=whole_block()),
                HoldIrradiance(duration=fixed(3600)),
            ],
        )
    )

    activity = executed(protocol)

    assert (activity.method, activity.location) == ('ISOS-L-2', 'Lab A')
    # One step per instruction, all starting with the test: they run in parallel.
    assert [(step.name, step.start_time) for step in activity.steps] == [
        ('hot', START),
        ('Irradiance for 1 h', START),
    ]


def test_a_stability_test_runs_a_stability_protocol_only():
    with pytest.raises(TypeError):
        StabilityActivity(plan=Plan())


def test_a_bare_archive_file_loads_through_nomad():
    archive = parse(os.path.join(DATA_DIR, 'tree.archive.yaml'))[0]
    normalize_all(archive)
    [root] = archive.data.instructions

    assert isinstance(archive.data, StabilityProtocol)
    assert [block.name for block in root.sub_instructions] == ['A', 'fork', 'D']
    assert root.sub_instructions[1].sub_instruction_execution_mode == 'parallel'
