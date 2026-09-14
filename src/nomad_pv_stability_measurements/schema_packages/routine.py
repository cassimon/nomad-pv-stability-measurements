import numpy as np
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection

from nomad_pv_stability_measurements.schema_packages.units import WrittenUnits
from nomad_pv_stability_measurements.schema_packages.utils import with_m_def

m_package = SchemaPackage()

#: The channel vocabulary. One member per class below, one slot per member in
#: `ChannelSettings` (protocol.py), and the values a `ChannelCommand.channel`
#: may take.
CHANNELS = ('temperature',)


class RoutineCommand(WrittenUnits):
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
        type=np.float64,
        unit='s',
        description='How long this command lasts, authored with its unit, e.g. '
        '`24 h`. With one, the command takes its turn in the block around it; '
        'leave it empty to last as long as that block does.',
    )


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
    monitor = Quantity(
        type=bool,
        description='Log data from this channel. Independent of `hold` — a '
        'channel nobody regulates can still be logged.',
    )
    sample_every = Quantity(
        type=np.float64,
        unit='s',
        description='How often to sample, authored with its unit, e.g. `60 s`. '
        'Write either this or `sampling_rate`; the other is derived from it.',
    )
    sampling_rate = Quantity(
        type=np.float64,
        unit='Hz',
        description='How fast to sample a continuous stream, authored with its '
        'unit, e.g. `10 Hz`. Write either this or `sample_every`; the other is '
        'derived from it.',
    )

    @property
    def controlled(self) -> bool:
        """Whether this command asks for a setpoint. Says nothing about what the
        channel does over time — that belongs to the derived timeline. Asks by
        `getattr` because `hold` belongs to the channel class (D19a), so a command
        that never reached one has no setpoint to give."""
        return getattr(self, 'hold', None) is not None

    @property
    def monitored(self) -> bool:
        """Whether this command logs the channel."""
        return bool(self.monitor)

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # One sampling figure is authored and the other follows from it, so whichever
        # the file wrote, everything downstream can read either (D9).
        if self.sampling_rate is None and self.sample_every is not None:
            self.sampling_rate = 1 / self.sample_every
        if self.sample_every is None and self.sampling_rate is not None:
            self.sample_every = 1 / self.sampling_rate


class TemperatureChannel(ChannelCommand):
    """The temperature axis."""

    hold = Quantity(
        type=np.float64,
        unit='K',
        description='Constant temperature to hold, authored with its unit, e.g. '
        '`65 °C`. Leave it empty to keep the channel uncontrolled in this command.',
    )


#: Which class an authored `channel:` names (D19a). Not cosmetic: a `hold` loaded as
#: the base class is dropped without a word, since only the channel class declares it.
CHANNEL_CLASSES = {'temperature': TemperatureChannel}


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
        """Fills in each `commands` entry's `m_def` — a `channel` names that
        channel's own class, anything else a nested `Subroutine` — before NOMAD
        loads the list natively (see `utils.with_m_def`). The channel's *value*
        decides, not just the key: the setpoint is declared on the channel class
        and NOMAD drops it silently if the entry is built as the base (D19a)."""

        def named(entry):
            channel = entry.get('channel') if isinstance(entry, dict) else None
            if channel is None:
                return with_m_def(entry, Subroutine)
            return with_m_def(entry, CHANNEL_CLASSES.get(channel, ChannelCommand))

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
            elif any(command.duration is None for command in commands):
                # A command without a `duration` is a condition and spans the whole
                # block, so it overlaps whatever else speaks to the channel (D13).
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

        if self.mode != 'sequential' or self.duration is None:
            return
        budget = self.duration.to('s').magnitude
        spent = 0.0
        for command in self.commands:
            if command.duration is None:
                continue
            if spent >= budget:
                logger.warning(
                    f'{command.name or "<unnamed>"} never runs: the `duration` of '
                    f'{self.name or "<unnamed>"} is already spent by the commands '
                    f'before it.'
                )
            spent += command.duration.to('s').magnitude


class Routine(Subroutine):
    """
    The root of the routine tree.

    A block like any other, but authored under the protocol instead of inside a
    `commands` list.
    """


m_package.__init_metainfo__()
