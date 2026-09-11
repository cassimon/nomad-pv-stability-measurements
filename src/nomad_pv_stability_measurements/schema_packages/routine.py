import numpy as np
from nomad.datamodel.data import ArchiveSection
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection

from nomad_pv_stability_measurements.schema_packages.units import (
    parse_duration,
    parse_frequency,
)
from nomad_pv_stability_measurements.schema_packages.utils import parsed, with_m_def

m_package = SchemaPackage()

#: The channel vocabulary. One member per class below, one slot per member in
#: `ChannelSettings` (protocol.py), and the values a `ChannelCommand.channel`
#: may take.
CHANNELS = ('temperature',)


def _bounded(command) -> bool:
    """Whether `command` gives a `duration` — an episode that takes its turn, as
    against a condition that holds for its block's whole span (D13)."""
    return bool(command.duration and command.duration.strip())


class RoutineCommand(ArchiveSection):
    """
    One thing a routine does.

    Two kinds: a `ChannelCommand` sets or logs one stress axis, a `Subroutine`
    groups further commands. Both carry a name and a `duration`.
    """

    name = Quantity(
        type=str,
        description='What to call this command. Optional — if empty, it is '
        'derived from what the command does.',
    )
    duration = Quantity(
        type=str,
        description='How long this command lasts, e.g. `24 h`. With one, it '
        'takes its turn in the block around it. Leave empty to last as long as '
        'that block does. Text only so the file can write the unit — the value '
        'is `duration_value`.',
    )
    duration_value = Quantity(
        type=np.float64,
        unit='s',
        description='`duration` as a number. Derived on save — edit `duration`.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.duration_value = parsed(self.duration, parse_duration, 'duration', logger)


class ChannelCommand(RoutineCommand):
    """
    What is asked of one channel: a setpoint, and whether it is logged.

    Used in two places. Under `channel_settings` it holds for the whole run; in
    a block's `commands` it holds for that block's span and wins there. Setpoint
    and logging fall back separately, so a command may change only the sampling
    rate.
    """

    channel = Quantity(
        type=MEnum(*CHANNELS),
        description='Which stress axis this command acts on. Leave empty under '
        '`channel_settings`, where the slot already says the axis.',
    )
    hold = Quantity(
        type=str,
        description='Constant setpoint to hold, e.g. `65 °C`. Leave empty to keep the channel uncontrolled in this command.'
        'States such as `off` or `ambient` are also interpreted as setpoints.',
    )
    monitor = Quantity(
        type=bool,
        description='Log data from this channel. Independent of `hold` — a '
        'channel nobody regulates can still be logged.',
    )
    sample_every = Quantity(
        type=str,
        description='How often to sample, e.g. `60 s`. Use either this or '
        '`sampling_rate`, not both. Text only so the file can write the unit — '
        'the value is `sample_every_value`.',
    )
    sample_every_value = Quantity(
        type=np.float64,
        unit='s',
        description='`sample_every` as a number. Derived on save — edit `sample_every`.',
    )
    sampling_rate = Quantity(
        type=str,
        description='How fast to sample a continuous stream, e.g. `10 Hz`. Use '
        'either this or `sample_every`, not both. Text only so the file can write '
        'the unit — the value is `sampling_rate_value`.',
    )
    sampling_rate_value = Quantity(
        type=np.float64,
        unit='Hz',
        description='`sampling_rate` as a number, or the reciprocal of '
        '`sample_every` when only that was given. Derived on save.',
    )

    @property
    def controlled(self) -> bool:
        """Whether this command asks for a setpoint. Says nothing about what the
        channel does over time — that belongs to the derived timeline."""
        return bool(self.hold and self.hold.strip())

    @property
    def monitored(self) -> bool:
        """Whether this command logs the channel."""
        return bool(self.monitor)

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.sample_every_value = parsed(
            self.sample_every, parse_duration, 'sample_every', logger
        )
        self.sampling_rate_value = parsed(
            self.sampling_rate, parse_frequency, 'sampling_rate', logger
        )
        if self.sampling_rate_value is None and self.sample_every_value:
            self.sampling_rate_value = 1 / self.sample_every_value

        if self.sample_every_value is None and self.sampling_rate_value:
            self.sample_every_value = 1 / self.sampling_rate_value


class TemperatureChannel(ChannelCommand):
    """The temperature axis."""


class Subroutine(RoutineCommand):
    """
    A block of the routine: a name, and the commands it runs.

    Commands that have a `duration` run in the order `mode` gives. A channel
    command without one is a standing condition and holds for this block's whole
    span. So "warm the sample, then run two phases under that warmth" is one
    block: a bare temperature command, then the two phases.
    """

    mode = Quantity(
        type=MEnum('sequential', 'parallel'),
        default='sequential',
        description='How this block runs the commands that have a `duration`: '
        '`sequential` one after another, `parallel` at the same time. Commands '
        "without a duration hold for the block's whole span either way.",
    )
    commands = SubSection(
        section_def=RoutineCommand,
        repeats=True,
        description='What this block does, in one list. Give a command a '
        '`channel` to act on an axis; leave it out to nest another block.',
    )

    def m_update_from_dict(self, dct: dict, **kwargs) -> None:
        """Fills in each `commands` entry's `m_def` — naming a `channel` means
        `ChannelCommand`, anything else a nested `Subroutine` — before NOMAD
        loads the list natively (see `utils.with_m_def`)."""

        def named(entry):
            is_channel_command = isinstance(entry, dict) and 'channel' in entry
            return with_m_def(
                entry, ChannelCommand if is_channel_command else Subroutine
            )

        entries = dct.get('commands')
        if isinstance(entries, list):
            dct = {**dct, 'commands': [named(entry) for entry in entries]}
        super().m_update_from_dict(dct, **kwargs)

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        kept = []
        for command in self.commands:
            # Only register conformal commands. A channel command without a `channel` is a mistake
            if isinstance(command, ChannelCommand) and command.channel is None:
                logger.error(
                    f'a channel command must name its `channel`; dropping '
                    f'{command.name or "<unnamed>"} from the routine.'
                )
                continue
            kept.append(command)
        self.commands = kept
        self._report_overlapping_commands(logger)
        self._report_commands_that_never_run(logger)

    def _report_overlapping_commands(self, logger):
        """R4: two commands on one channel must be truly subsequent — each with its
        own `duration`, in a `sequential` block. Siblings have equal scope, so nothing
        decides between them and they are never merged into one command: asking nothing
        of a channel is itself a statement (D8), so `hold` beside a bare `monitor` is a
        contradiction, not two halves of one command (D13a). Reported, never repaired —
        the authored commands stay as written and expansion is what gets skipped."""
        for channel in CHANNELS:
            commands = [
                command
                for command in self.commands
                if isinstance(command, ChannelCommand) and command.channel == channel
            ]
            if len(commands) <= 1:
                continue
            if self.mode == 'parallel':
                reason = 'a `parallel` block runs its commands at the same time'
            elif any(not _bounded(command) for command in commands):
                reason = (
                    "a command without a `duration` holds for the block's whole span"
                )
            else:
                continue  # each has its own turn — genuinely subsequent
            logger.error(
                f'{len(commands)} commands on `{channel}` overlap in '
                f'{self.name or "<unnamed>"}: {reason}. Siblings are not merged into '
                f'one command — write one command with all the keys, or give each its '
                f'own `duration` in a sequential block.'
            )

    def _report_commands_that_never_run(self, logger):
        """R5: episodes take their turns in order, so if this block's own `duration` is
        already spent by the ones before it, a command gets no time at all — authored,
        but never executed (D13a). Commands without a `duration` are conditions: they
        hold for the whole span and take no turn. Reads the twins, which NOMAD has
        filled by now — it normalizes every nested section before its parent."""
        if self.mode != 'sequential' or self.duration_value is None:
            return
        budget = self.duration_value.to('s').magnitude
        spent = 0.0
        for command in self.commands:
            if command.duration_value is None:
                continue
            if spent >= budget:
                logger.warning(
                    f'{command.name or "<unnamed>"} never runs: the `duration` of '
                    f'{self.name or "<unnamed>"} is already spent by the commands '
                    f'before it.'
                )
            spent += command.duration_value.to('s').magnitude


class Routine(Subroutine):
    """
    The root of the routine tree.

    A block like any other, but authored under the protocol instead of inside a
    `commands` list.
    """


m_package.__init_metainfo__()
