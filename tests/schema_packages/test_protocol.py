import os

import pytest
from nomad.client import normalize_all, parse
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import PlannedProcessStep
from nomad_pv_stability_measurements.schema_packages.hold_below_steps import (
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldIrradiance,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.mpp_steps import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.protocol import (
    GeoLocation,
    StabilityProtocol,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedMonitorControlStep,
    PlannedSubroutineStep,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
BLOCK = PlannedSubroutineStep


def entry(cls, **fields) -> dict:
    return {'m_def': f'{cls.__module__}.{cls.__name__}', **fields}


# "A, then B and C at the same time, then D" (Design.md §3), as the bare archive
# writes it: every entry names its class.
TREE = {
    'name': 'example',
    'steps': [
        entry(BLOCK, name='A'),
        entry(
            BLOCK,
            name='fork',
            execution_mode='parallel',
            steps=[entry(BLOCK, name='B'), entry(BLOCK, name='C')],
        ),
        entry(BLOCK, name='D'),
    ],
}


def normalize_protocol(protocol, log):
    # A protocol's own normalize reads the archive's metadata, and names a nameless
    # protocol after the entry, as a real upload always has one (§14.2, verified).
    metadata = EntryMetadata(entry_name='protocol.stability.yaml')
    protocol.normalize(EntryArchive(metadata=metadata, data=protocol), log)


def test_blocks_nest_through_steps():
    root = BLOCK.m_from_dict(TREE)
    fork = root.steps[1]

    assert [block.name for block in root.steps] == ['A', 'fork', 'D']
    assert [block.name for block in fork.steps] == ['B', 'C']
    assert all(isinstance(block, BLOCK) for block in [*root.steps, *fork.steps])


def test_both_kinds_of_step_have_a_single_base():
    # One chain each: ProcessStep -> PlannedProcessStep -> the two kinds.
    assert BLOCK.__bases__ == (PlannedProcessStep,)
    assert PlannedMonitorControlStep.__bases__ == (PlannedProcessStep,)


def test_steps_is_the_only_list_on_a_block():
    sections = BLOCK.m_def.all_sub_sections

    assert tuple(sections) == ('steps',)
    assert sections['steps'].sub_section.section_cls is PlannedProcessStep


def test_execution_mode_defaults_to_sequential():
    assert BLOCK().execution_mode == 'sequential'
    assert BLOCK(execution_mode='parallel').execution_mode == 'parallel'


def test_execution_mode_rejects_unknown_values():
    with pytest.raises(ValueError):
        BLOCK(execution_mode='interleaved')


def test_tree_round_trips_exactly():
    # The bare archive is what `m_to_dict` writes, so nothing needs stripping.
    assert BLOCK.m_from_dict(TREE).m_to_dict() == TREE


def test_the_protocol_is_only_steps():
    sections = StabilityProtocol.m_def.all_sub_sections

    assert sections['steps'].sub_section.section_cls is PlannedProcessStep
    # `channel_settings` and `routine` are words of the authored file only (§14.3).
    assert {'channel_settings', 'routine'}.isdisjoint(sections)


def test_the_protocol_checks_its_steps_like_a_block(log):
    protocol = StabilityProtocol.m_from_dict(
        {'name': 'soak', 'steps': [entry(HoldTemperature), entry(HoldTemperature)]}
    )

    normalize_protocol(protocol, log)

    [error] = log.errors
    assert '2 Temperature steps overlap in soak' in error


def test_a_block_overrides_a_condition_for_its_span(log):
    # The settings of an authored file become leading conditions, and the routine a
    # block after them: one level deeper, so not a sibling, so no overlap (§14.3).
    protocol = StabilityProtocol.m_from_dict(
        {
            'steps': [
                entry(HoldTemperature, control=True, set_point=338.15),
                entry(
                    BLOCK,
                    steps=[
                        entry(
                            HoldTemperature,
                            control=True,
                            set_point=358.15,
                            estimated_duration=3600,
                        )
                    ],
                ),
            ]
        }
    )

    normalize_protocol(protocol, log)

    assert log.errors == []


def test_entry_loads_from_the_bare_archive_file():
    archive = parse(os.path.join(DATA_DIR, 'tree.archive.yaml'))[0]
    normalize_all(archive)
    [root] = archive.data.steps

    assert isinstance(archive.data, StabilityProtocol)
    assert archive.data.name == 'my protocol'
    assert root.name == 'example'
    assert [block.name for block in root.steps] == ['A', 'fork', 'D']
    assert root.steps[1].execution_mode == 'parallel'


# The protocol's own duration, checked and set like a block's (§15.4).


def test_the_protocol_fits_its_steps_to_its_duration(log):
    protocol = StabilityProtocol.m_from_dict(
        {
            'name': 'soak',
            'estimated_duration': 3600,
            'steps': [
                entry(HoldTemperature, name='warm', estimated_duration=1800),
                entry(HoldIrradiance, name='lit', estimated_duration=3600),
                entry(HoldVoltage, name='late', estimated_duration=600),
            ],
        }
    )

    normalize_protocol(protocol, log)

    # `lit` is cut to the time left; `late` has none left, so it is only reported.
    assert [step.estimated_duration.magnitude for step in protocol.steps] == [
        1800,
        1800,
        600,
    ]
    assert any('late never runs' in warning for warning in log.warnings)
    assert any(
        'lit is shortened from 3600 s to 1800 s' in warning and 'soak' in warning
        for warning in log.warnings
    )
    assert log.errors == []


def test_the_protocol_derives_its_duration_from_its_steps(log):
    protocol = StabilityProtocol.m_from_dict(
        {
            'steps': [
                entry(HoldIrradiance, monitor=True),
                entry(HoldTemperature, estimated_duration=1800),
                entry(HoldVoltage, estimated_duration=3600),
            ]
        }
    )

    normalize_protocol(protocol, log)

    assert protocol.estimated_duration.magnitude == pytest.approx(5400)
    assert log.errors == []


# What the run itself records (§15.12).


def test_a_protocol_is_indoors_unless_it_says_otherwise():
    # A positive claim rather than a neutral element, because nearly every one of these
    # tests is run in a laboratory (§15.12).
    assert StabilityProtocol().environment == 'indoor'
    assert StabilityProtocol(environment='outdoor').environment == 'outdoor'


def test_environment_rejects_unknown_values():
    with pytest.raises(ValueError):
        StabilityProtocol(environment='in orbit')


def test_a_protocol_takes_free_text_notes():
    assert StabilityProtocol(notes='ran over a weekend').notes == 'ran over a weekend'


def test_a_place_is_nomads_own_location_plus_our_coordinates():
    protocol = StabilityProtocol(
        environment='outdoor',
        location='Denver, U.S.',
        geo_location=GeoLocation(
            latitude=39.7392 * ureg.degree,
            longitude=-104.9903 * ureg.degree,
        ),
    )

    # The label is NOMAD's own field, so it searches beside every other activity.
    assert protocol.location == 'Denver, U.S.'
    assert protocol.geo_location.latitude.magnitude == pytest.approx(39.7392)
    assert protocol.geo_location.longitude.magnitude == pytest.approx(-104.9903)


def test_the_schema_adds_no_second_place_to_write_the_name():
    # Declaring our own `location` sub-section collided with NOMAD's own quantity
    # (`MetainfoError: Cannot inherit from different property types`) — verified.
    assert 'name' not in GeoLocation.m_def.all_quantities
    # `location` stays NOMAD's own quantity, and takes the name directly.
    assert 'location' in StabilityProtocol.m_def.all_quantities
    assert 'location' not in StabilityProtocol.m_def.all_sub_sections
    assert StabilityProtocol(location='Denver, U.S.').location == 'Denver, U.S.'


def test_coordinates_round_trip():
    data = {'latitude': 39.7392, 'longitude': -104.9903, 'altitude': 1609.0}

    assert GeoLocation.m_from_dict(data).m_to_dict() == data


def test_a_place_records_how_high_it_is():
    # Denver in the unit its own signs use, stored in metres either way.
    denver = GeoLocation(altitude=5280 * ureg.foot)

    assert denver.altitude.to(ureg.meter).magnitude == pytest.approx(1609, rel=1e-3)


def test_below_sea_level_is_a_negative_altitude():
    # No bound is checked: unlike a latitude, there is no number that is simply wrong.
    dead_sea = GeoLocation(altitude=-430 * ureg.meter)

    assert dead_sea.altitude.magnitude == pytest.approx(-430)


def test_a_place_may_be_named_without_being_surveyed():
    # The name stands on its own: it is a different field, not half of this section.
    assert StabilityProtocol(location='Denver, U.S.').geo_location is None


def test_coordinates_the_wrong_way_round_are_reported(normalized, log):
    # A latitude past ±90° is what catches the classic swap.
    normalized(GeoLocation(latitude=-104.9903 * ureg.degree))

    [error] = log.errors
    assert '`latitude` is -104.99' in error
    assert 'wrong way round' in error


def test_an_option_of_a_standard_is_a_protocol_of_its_own():
    # One instance per option the standard offers, told apart by `standard_variant`, while
    # `standard` stays the bare designation every variant is found by (§18.1).
    low = StabilityProtocol(standard='ISOS-D-2', standard_variant='65 °C')
    high = StabilityProtocol(standard='ISOS-D-2', standard_variant='85 °C')

    assert (low.standard, low.standard_variant) == ('ISOS-D-2', '65 °C')
    assert StabilityProtocol.m_from_dict(high.m_to_dict()).standard_variant == '85 °C'
    assert StabilityProtocol().standard_variant is None


# The level-3 rule (§20.7).


def checked(standard, *steps, log, **fields) -> StabilityProtocol:
    protocol = StabilityProtocol(standard=standard, **fields)
    protocol.steps = list(steps)
    metadata = EntryMetadata(entry_name='protocol')
    protocol.normalize(EntryArchive(metadata=metadata, data=protocol), log)
    return protocol


#: A level the protocol writes itself, differing from its designation's.
WRITTEN_LEVEL = 2


@pytest.mark.parametrize(
    ('standard', 'level'),
    [
        ('ISOS-D-1', 1),
        ('ISOS-L-2', 2),
        ('ISOS-L-3', 3),
        ('ISOS-LC-3I', 3),
        ('IEC 61215', None),
    ],
)
def test_the_level_is_derived_from_an_isos_designation(standard, level, log):
    assert checked(standard, log=log).standard_level == level


def test_a_written_level_is_kept(log):
    protocol = checked(
        'ISOS-L-3',
        HoldIrradiance(control=True),
        VOCTracking(),
        standard_level=WRITTEN_LEVEL,
        log=log,
    )

    assert protocol.standard_level == WRITTEN_LEVEL
    assert log.errors == []


@pytest.mark.parametrize(
    ('load', 'found'),
    [(VOCTracking(), 'VOCTracking'), (HoldVoltage(control=True), 'HoldVoltage')],
)
def test_level_3_under_light_must_track_the_mpp(load, found, log):
    checked('ISOS-L-3', HoldIrradiance(control=True), load, log=log)

    [error] = log.errors
    assert 'MPP tracking is mandatory' in error
    assert f'writes {found}' in error


def test_level_3_under_light_without_a_load_is_reported(log):
    checked('ISOS-LT-3', HoldIrradiance(control=True), log=log)

    [error] = log.errors
    assert 'no electrical load at all' in error


def test_what_the_rule_does_not_reach(log):
    dark = HoldIrradiance(control=True, set_point=0 * ureg('W/m^2'))
    checked('ISOS-L-3', HoldIrradiance(control=True), MPPTracking(), log=log)
    checked('ISOS-D-3', dark, VOCTracking(), log=log)  # dark: no MPP to track
    dark_range = HoldBetweenIrradiance(
        lower_bound=0 * ureg('W/m^2'), upper_bound=0 * ureg('W/m^2')
    )
    checked('ISOS-D-3', dark_range, VOCTracking(), log=log)
    checked('ISOS-L-2', HoldIrradiance(control=True), VOCTracking(), log=log)
    checked(
        'IEC 61215',
        HoldIrradiance(control=True),
        VOCTracking(),
        standard_level=3,
        log=log,
    )

    assert log.errors == []


def test_a_range_of_irradiance_is_light_too(log):
    # The recommended 800–1000 W m⁻² variants are under light (§22).
    light = HoldBetweenIrradiance(
        lower_bound=800 * ureg('W/m^2'), upper_bound=1000 * ureg('W/m^2')
    )
    checked('ISOS-L-3', light, VOCTracking(), log=log)

    [error] = log.errors
    assert 'MPP tracking is mandatory' in error
