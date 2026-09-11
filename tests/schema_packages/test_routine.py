import os

import pytest
from nomad import utils
from nomad.client import normalize_all, parse
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.protocol import ChannelSettings
from nomad_pv_stability_measurements.schema_packages.routine import (
    CHANNELS,
    ChannelCommand,
    RoutineCommand,
    Subroutine,
    TemperatureChannel,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


def test_every_channel_has_a_settings_slot():
    slots = ChannelSettings.m_def.all_sub_sections

    assert tuple(slots) == CHANNELS


def test_settings_carry_conditions_for_the_whole_run():
    channel = TemperatureChannel.m_from_dict(
        {'hold': '65 °C', 'monitor': True, 'sample_every': '60 s'}
    )

    assert (channel.hold, channel.monitor, channel.sample_every) == (
        '65 °C',
        True,
        '60 s',
    )
    assert channel.sampling_rate is None
    channel.normalize(None, utils.get_logger(__name__))

    # The authored strings are untouched; the parsed values live in the twins (D19a).
    assert channel.sample_every == '60 s'
    assert channel.sample_every_value.to(ureg.second).magnitude == pytest.approx(60)
    # No `sampling_rate` string is invented — only its twin is derived.
    assert channel.sampling_rate is None
    assert channel.sampling_rate_value.to(ureg.hertz).magnitude == pytest.approx(1 / 60)


def test_a_channel_slot_holds_one_block_and_needs_no_m_def():
    settings = ChannelSettings.m_from_dict({'temperature': {'hold': '65 °C'}})

    assert isinstance(settings.temperature, TemperatureChannel)
    assert settings.temperature.hold == '65 °C'


def test_settings_are_optional():
    assert ChannelSettings().temperature is None


def test_only_channel_commands_carry_conditions():
    # The vocabulary sits on ChannelCommand, so a settings block has it and a
    # block does not — that is what splitting the two classes bought.
    conditions = {'hold', 'monitor', 'sample_every', 'sampling_rate'}

    assert conditions <= set(ChannelCommand.m_def.all_quantities)
    assert conditions <= set(TemperatureChannel.m_def.all_quantities)
    assert conditions.isdisjoint(Subroutine.m_def.all_quantities)


def test_both_kinds_of_command_share_one_base():
    assert issubclass(ChannelCommand, RoutineCommand)
    assert issubclass(Subroutine, RoutineCommand)
    assert 'name' in RoutineCommand.m_def.all_quantities


def test_asking_nothing_is_the_neutral_element():
    # No setpoint means the channel is not regulated, which is also what it is
    # wherever nothing says otherwise.
    silent = TemperatureChannel()
    held = TemperatureChannel.m_from_dict({'hold': '65 °C'})
    empty = TemperatureChannel.m_from_dict({'hold': ''})
    empty_space = TemperatureChannel.m_from_dict({'hold': ' '})
    empty_tab = TemperatureChannel.m_from_dict({'hold': '\t'})
    empty_linebreak = TemperatureChannel.m_from_dict({'hold': '\n'})

    assert (
        silent.controlled,
        held.controlled,
        empty.controlled,
        empty_space.controlled,
        empty_tab.controlled,
        empty_linebreak.controlled,
    ) == (False, True, False, False, False, False)


def test_channel_is_a_closed_vocabulary():
    assert ChannelCommand(channel='temperature').channel == 'temperature'
    with pytest.raises(ValueError):
        ChannelCommand(channel='chuck_T')


def test_monitored_follows_the_tag():
    assert TemperatureChannel().monitored is False
    assert TemperatureChannel.m_from_dict({'monitor': True}).monitored is True


def test_a_block_commands_channels_through_its_commands_list():
    node = Subroutine.m_from_dict(
        {
            'name': 'hot phase',
            'commands': [{'channel': 'temperature', 'hold': '85 °C', 'monitor': True}],
        }
    )
    command = node.commands[0]

    assert isinstance(command, ChannelCommand)
    assert (command.controlled, command.monitored) == (True, True)


def test_two_commands_on_one_channel_are_not_merged(normalized, log):
    # Not "hold and log": the second names the channel and asks nothing of it, which
    # says *not regulated here* (D8). Siblings have equal scope, so nothing decides
    # between them — a contradiction, not two halves of one command (D13a, R4).
    node = normalized(
        Subroutine.m_from_dict(
            {
                'name': 'hot phase',
                'commands': [
                    {'channel': 'temperature', 'hold': '85 °C'},
                    {'channel': 'temperature', 'monitor': True},
                ],
            }
        )
    )

    assert len(log.errors) == 1
    assert 'overlap' in log.errors[0]
    assert 'not merged' in log.errors[0]
    # Reported, never repaired: the commands stay as authored.
    assert [command.channel for command in node.commands] == [
        'temperature',
        'temperature',
    ]


def test_two_commands_on_one_channel_may_be_truly_subsequent(normalized, log):
    # Each has its own turn in a sequential block, so they never overlap (R4).
    normalized(
        Subroutine.m_from_dict(
            {
                'commands': [
                    {'channel': 'temperature', 'hold': '25 °C', 'duration': '1 h'},
                    {'channel': 'temperature', 'hold': '85 °C', 'duration': '500 h'},
                ]
            }
        )
    )

    assert log.errors == []


def test_a_parallel_block_cannot_command_one_channel_twice(normalized, log):
    # Durations do not help here: a parallel block runs its commands at the same time.
    normalized(
        Subroutine.m_from_dict(
            {
                'mode': 'parallel',
                'commands': [
                    {'channel': 'temperature', 'hold': '25 °C', 'duration': '1 h'},
                    {'channel': 'temperature', 'hold': '85 °C', 'duration': '1 h'},
                ],
            }
        )
    )

    assert len(log.errors) == 1
    assert 'parallel' in log.errors[0]


def test_a_command_the_block_leaves_no_time_for_is_flagged(normalized, log):
    # Subsequent, so R4 is satisfied — but the block's own `duration` is spent before
    # the second command's turn comes, so it is authored and never executed (R5).
    normalized(
        Subroutine.m_from_dict(
            {
                'name': 'phase',
                'duration': '500 h',
                'commands': [
                    {'channel': 'temperature', 'hold': '85 °C', 'duration': '500 h'},
                    {
                        'name': 'cool down',
                        'channel': 'temperature',
                        'hold': '25 °C',
                        'duration': '1 h',
                    },
                ],
            }
        )
    )

    assert log.errors == []
    assert len(log.warnings) == 1
    assert 'cool down' in log.warnings[0]
    assert 'never runs' in log.warnings[0]


def test_a_command_without_a_duration_takes_no_turn(normalized, log):
    # A condition holds for the whole span instead of queueing, so it spends none of
    # the block's budget and what follows it still runs (D13, R5).
    normalized(
        Subroutine.m_from_dict(
            {
                'duration': '500 h',
                'commands': [
                    {'name': 'warm', 'channel': 'temperature', 'hold': '85 °C'},
                    {'name': 'phase', 'duration': '500 h'},
                ],
            }
        )
    )

    assert (log.errors, log.warnings) == ([], [])


def test_a_command_carries_its_own_duration():
    # No block is needed just to give a command a lifetime: `duration` is on
    # RoutineCommand, so both kinds have it.
    episode = ChannelCommand.m_from_dict(
        {'channel': 'temperature', 'hold': '85 °C', 'duration': '24 h'}
    )
    block = Subroutine.m_from_dict({'name': 'phase', 'duration': '24 h'})

    assert episode.duration == '24 h'
    assert block.duration == '24 h'
    # A command without one is a condition, not an episode.
    assert ChannelCommand.m_from_dict({'channel': 'temperature'}).duration is None


def test_logging_is_orthogonal_to_the_setpoint():
    # A channel nobody regulates can still be logged, and vice versa.
    logged = TemperatureChannel.m_from_dict({'monitor': True})

    assert (logged.controlled, logged.monitored) == (False, True)


def test_settings_take_no_time_varying_state():
    # A ramp belongs in the routine, where time lives (Design.md §4.1).
    assert 'ramp' not in TemperatureChannel.m_def.all_properties


def test_entry_loads_settings_and_a_command_that_overrides_them():
    archive = parse(os.path.join(DATA_DIR, 'channels.archive.yaml'))[0]
    normalize_all(archive)
    settings = archive.data.channel_settings.temperature
    command = archive.data.routine.commands[0]

    assert (settings.hold, settings.monitor, settings.sample_every) == (
        '65 °C',
        True,
        '60 s',
    )
    # The command stands directly in `commands`, with its own duration — no
    # block wrapped around it.
    assert (command.channel, command.hold, command.duration) == (
        'temperature',
        '85 °C',
        '500 h',
    )
    assert command.sampling_rate == '10 Hz'
    # The twins are filled by NOMAD's own normalize pass, all the way down the tree.
    assert settings.sample_every_value.to(ureg.second).magnitude == pytest.approx(60)
    assert command.sampling_rate_value.to(ureg.hertz).magnitude == pytest.approx(10)
    # `500 h` is hours, not Planck's constant (§6 step 2).
    assert command.duration_value.to(ureg.hour).magnitude == pytest.approx(500)
    # The second asks nothing of the channel — it only names it and a span.
    assert archive.data.routine.commands[1].controlled is False
