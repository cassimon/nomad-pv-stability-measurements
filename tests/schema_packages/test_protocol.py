import os

import pytest
from nomad import utils
from nomad.client import normalize_all, parse

from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
from nomad_pv_stability_measurements.schema_packages.routine import (
    ChannelCommand,
    Routine,
    RoutineCommand,
    Subroutine,
    TemperatureChannel,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# "A, then B and C at the same time, then D" (Design.md §3).
TREE = {
    'name': 'example',
    'commands': [
        {'name': 'A'},
        {
            'name': 'fork',
            'mode': 'parallel',
            'commands': [{'name': 'B'}, {'name': 'C'}],
        },
        {'name': 'D'},
    ],
}


def as_authored(node: Routine) -> dict:
    """`node` as a dict without `m_def`, which `m_to_dict` writes on every command
    (each is a subclass of the declared `RoutineCommand`)."""

    def strip(data):
        if isinstance(data, dict):
            return {k: strip(v) for k, v in data.items() if k != 'm_def'}
        if isinstance(data, list):
            return [strip(v) for v in data]
        return data

    return strip(node.m_to_dict())


def test_blocks_nest_through_commands():
    root = Routine.m_from_dict(TREE)
    fork = root.commands[1]

    assert [block.name for block in root.commands] == ['A', 'fork', 'D']
    assert [block.name for block in fork.commands] == ['B', 'C']
    assert all(
        isinstance(block, Subroutine) for block in [*root.commands, *fork.commands]
    )


def test_one_list_holds_both_kinds_of_command():
    node = Routine.m_from_dict(
        {
            'name': 'soak',
            'commands': [
                {'channel': 'temperature', 'hold': '65 °C'},
                {'name': 'phase', 'commands': [{'channel': 'temperature'}]},
            ],
        }
    )

    assert [type(command).__name__ for command in node.commands] == [
        'TemperatureChannel',
        'Subroutine',
    ]


def test_a_nested_block_s_own_commands_get_the_m_def_too():
    # `m_update_from_dict` only annotates one level; a nested block's own
    # `commands` get theirs when NOMAD builds that block and calls back into
    # this same method for its entries.
    root = Routine.m_from_dict(
        {
            'commands': [
                {'name': 'phase', 'commands': [{'channel': 'temperature'}]},
            ]
        }
    )

    assert isinstance(root.commands[0].commands[0], ChannelCommand)


def test_the_root_is_a_block_with_a_single_base():
    # One chain: ArchiveSection -> RoutineCommand -> Subroutine -> Routine.
    assert issubclass(Routine, Subroutine)
    assert Subroutine.__bases__ == (RoutineCommand,)
    assert Routine.__bases__ == (Subroutine,)


def test_commands_is_the_only_list_on_a_node():
    sections = Subroutine.m_def.all_sub_sections

    assert tuple(sections) == ('commands',)
    assert sections['commands'].sub_section.section_cls is RoutineCommand


def test_mode_defaults_to_sequential():
    assert Routine().mode == 'sequential'
    assert Routine(mode='parallel').mode == 'parallel'
    # Every block says how its own commands run, not just the root.
    assert Subroutine().mode == 'sequential'


def test_mode_rejects_unknown_values():
    with pytest.raises(ValueError):
        Routine(mode='interleaved')


def test_normalize_drops_a_command_that_names_no_channel():
    # NOMAD's own normalizer catches a raise and logs it as a plugin crash
    # (verified against nomad.normalizing.metainfo); an authoring mistake like
    # a stray `channel:` should read as a warning, not break processing.
    node = Subroutine()
    node.commands.append(TemperatureChannel(hold='65 °C'))
    node.commands.append(TemperatureChannel(channel='temperature', hold='85 °C'))

    node.normalize(None, utils.get_logger(__name__))

    assert [command.channel for command in node.commands] == ['temperature']


def test_tree_round_trips():
    assert as_authored(Routine.m_from_dict(TREE)) == TREE


def test_entry_loads_from_yaml():
    archive = parse(os.path.join(DATA_DIR, 'tree.archive.yaml'))[0]
    normalize_all(archive)
    root = archive.data.routine

    assert isinstance(archive.data, StabilityProtocol)
    assert archive.data.name == 'my protocol'
    assert root.name == 'example'
    assert [block.name for block in root.commands] == ['A', 'fork', 'D']
    assert [block.name for block in root.commands[1].commands] == ['B', 'C']
    assert root.commands[1].mode == 'parallel'
