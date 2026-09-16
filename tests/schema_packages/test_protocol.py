import os

import pytest
from nomad.client import normalize_all, parse
from nomad.datamodel import EntryArchive, EntryMetadata

from nomad_pv_stability_measurements.schema_packages.activity_steps import (
    Irradiance,
    Temperature,
    Voltage,
)
from nomad_pv_stability_measurements.schema_packages.general import PlannedProcessStep
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
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
        {'name': 'soak', 'steps': [entry(Temperature), entry(Temperature)]}
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
                entry(Temperature, control=True, setpoint=338.15),
                entry(
                    BLOCK,
                    steps=[
                        entry(
                            Temperature,
                            control=True,
                            setpoint=358.15,
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
                entry(Temperature, name='warm', estimated_duration=1800),
                entry(Irradiance, name='lit', estimated_duration=3600),
                entry(Voltage, name='late', estimated_duration=600),
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
                entry(Irradiance, monitor=True),
                entry(Temperature, estimated_duration=1800),
                entry(Voltage, estimated_duration=3600),
            ]
        }
    )

    normalize_protocol(protocol, log)

    assert protocol.estimated_duration.magnitude == pytest.approx(5400)
    assert log.errors == []
