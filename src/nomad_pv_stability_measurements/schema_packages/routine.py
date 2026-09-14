from dataclasses import dataclass, replace

from nomad.datamodel.data import ArchiveSection
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection

from nomad_pv_stability_measurements.schema_packages.units import (
    UNREADABLE_VALUES,
    StabilityUnitAwareFloat,
)
from nomad_pv_stability_measurements.schema_packages.utils import with_m_def

m_package = SchemaPackage()

#: The channel vocabulary. One member per class below, one slot per member in
#: `ChannelSettings` (protocol.py), and the values a `ChannelCommand.channel`
#: may take.
CHANNELS = ('temperature', 'irradiation', 'electrical_load', 'mechanical')


@dataclass(frozen=True)
class Variable:
    """What one axis of a channel can be asked for — a schema constant, not metainfo.

    The setpoint itself is a real quantity on the channel class, in `unit`; this says
    what that quantity means. `field` names it, and is written only where that is not
    the variable's own name: a channel with a single variable spells it `hold`, since
    there is no second variable to tell it from (D19b).

    Whether it can be asked for or logged is asked of the variable, not of the channel
    through a wrapper (D4c) — the channel's own part of that answer is whether
    `ChannelCommand.variables` holds the name at all.
    """

    unit: str
    display: str | None = None  # what a plot prefers, e.g. 'degC'
    control: bool = True
    monitor: bool = True
    field: str | None = None
    #: Stamped on by the group that takes it, never written by hand: the keyword a
    #: `ControlGroup` is given IS the name, so the variable may as well carry it.
    name: str | None = None

    @property
    def setpoint_field(self) -> str | None:
        """The quantity on the channel class that carries this variable's setpoint
        (D19b): its own name, unless the class spells it something else."""
        return self.field or self.name


class ControlGroup:
    """Variables one device cannot set independently of one another (D4c).

    Written `ControlGroup(voltage=Variable('V'), current=Variable('A'))`: the
    keywords are the variables, in ELN order, so `numberless` and `tied_by` are the
    only two names a variable may not have. Most groups hold one — bending a device
    says nothing about stretching it.

    What it encodes is actuation, not physics: humidity and oxygen are separate
    groups because a gas mixer sets them separately, though their partial pressures
    do sum to the total.
    """

    __slots__ = ('numberless', 'tied_by', 'variables')

    def __init__(
        self,
        *,
        numberless: tuple[str, ...] = (),
        tied_by: str | None = None,
        **variables: Variable,
    ):
        #: `replace` copies, so nothing the caller wrote is mutated and two variables
        #: built alike stay equal until they are named.
        self.variables = {
            name: replace(declared, name=name) for name, declared in variables.items()
        }
        #: Words this group accepts in place of a number (D8a). They belong to the
        #: group, not to a variable: `open_circuit` releases the whole load, and it
        #: is neither 0 V nor 0 A, so no unit-ful field could carry it.
        self.numberless = numberless
        #: Why the variables are tied, in words — read by the ELN and by the
        #: messages. Never an equation: the law here is the cell's own I–V curve,
        #: which is what a run measures rather than a constant the schema holds (D1).
        self.tied_by = tied_by

    @property
    def names(self) -> frozenset:
        """The variables this group ties together."""
        return frozenset(self.variables)

    def __contains__(self, variable: str) -> bool:
        return variable in self.variables


class StabilityUnitAwareSection(ArchiveSection):
    """Base class for sections with `StabilityUnitAwareFloat` fields: reports what
    they could not read.

    Parsing itself happens in the field's own type (units.py, D19). A value that
    type could not read is left unset and remembered here, so that one typo does
    not stop the entry from loading; this reports the lot on the next normalize
    (§7).
    """

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        for complaint in self.m_cache.get(UNREADABLE_VALUES, {}).values():
            logger.error(complaint)


class RoutineCommand(StabilityUnitAwareSection):
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
        type=StabilityUnitAwareFloat(),
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

    What an axis can be asked for is the subclass's business: each declares its
    `control_groups` and a unit-ful quantity per variable (D4c, D19b). This holds
    the part that is the same everywhere — which variable a command speaks about,
    and what the channel can do with it.
    """

    #: The channel's whole capability, and the only table it writes (D4c): what it
    #: can be asked for, and which of those a device cannot set independently.
    control_groups: tuple[ControlGroup, ...] = ()

    @classmethod
    def variables(cls) -> dict[str, Variable]:
        """Every variable this channel has, in declaration order: the groups flattened.
        Each has a quantity of its own on the class, named by `Variable.field` or by
        the variable itself (D19b).

        Derived on demand, so `control_groups` stays the only place a channel's
        capability is written *or* read (D4c). Not cached onto the class at creation
        and not built in `normalize()` — D19b's `hold` rewriting runs while the entry
        loads, before any normalize, and a channel has three variables at most.
        """
        return {
            name: declared
            for group in cls.control_groups
            for name, declared in group.variables.items()
        }

    @classmethod
    def numberless(cls) -> tuple[str, ...]:
        """Every word this channel takes in place of a number (D8a). Each is a boolean
        quantity of the same name, and `hold:` accepts the word, so it is written
        wherever a value is written."""
        return tuple(word for group in cls.control_groups for word in group.numberless)

    channel = Quantity(
        type=MEnum(*CHANNELS),
        description='Which stress axis this command acts on. Leave empty under '
        '`channel_settings`, where the slot already says the axis.',
    )
    variable = Quantity(
        type=str,
        description='Which variable of the channel this command acts on, e.g. '
        '`voltage`. Needed where the channel has more than one and the setpoint is '
        'written as `hold`; writing the variable as the key instead says the same '
        'thing. Filled in from the setpoint wherever only one variable is set.',
    )
    available_variables = Quantity(
        type=str,
        shape=['*'],
        description='What this channel can be asked for. Derived from the schema, so '
        'it is the same for every command on the channel.',
    )
    monitor = Quantity(
        type=bool,
        description='Log data from this channel. Independent of `hold` — a '
        'channel nobody regulates can still be logged.',
    )
    sample_every = Quantity(
        type=StabilityUnitAwareFloat(),
        unit='s',
        description='How often to sample, authored with its unit, e.g. `60 s`. '
        'Write either this or `sampling_rate`; the other is derived from it.',
    )
    sampling_rate = Quantity(
        type=StabilityUnitAwareFloat(),
        unit='Hz',
        description='How fast to sample a continuous stream, authored with its '
        'unit, e.g. `10 Hz`. Write either this or `sample_every`; the other is '
        'derived from it.',
    )

    @classmethod
    def group_of(cls, variable: str) -> ControlGroup | None:
        """The group `variable` belongs to — `.names` is what cannot be commanded
        independently of it, and `.tied_by` says why. `None` where this channel has
        no such variable."""
        for group in cls.control_groups:
            if variable in group:
                return group
        return None

    @property
    def setpoints(self) -> dict:
        """What this command asks the channel for, by variable. Empty means it asks
        nothing — the neutral element (D8). Read by `getattr` because the quantities
        belong to the channel class (D19a, D19b), so the base has none of them."""
        asked = {}
        for name, declared in self.variables().items():
            value = getattr(self, declared.setpoint_field, None)
            if value is not None:
                asked[name] = value
        return asked

    @property
    def asks_for_anything(self) -> bool:
        """Whether this command asks the channel for anything at all — an `any`, not an
        `all`: one setpoint out of a channel's three makes it true, and asking for more
        than one is a contradiction (§4.2) rather than a fuller answer. A word standing
        for no number counts too, so `open_circuit` makes it true while `setpoints` is
        empty (D8a) — which is why this is not `has_setpoint`.

        Says nothing about what the channel does over time: that is `is_controlled`,
        derived over the whole tree, and the reason this is not `controlled` (D8).

        There is no `monitored` beside it: `monitor` is already a boolean quantity, and
        §4.1 gives that name to the list of variables a command logs.
        """
        return bool(self.setpoints) or any(
            getattr(self, word, None) for word in self.numberless()
        )

    def m_update_from_dict(self, dct: dict, **kwargs) -> None:
        """Moves an authored `hold` into the quantity of the variable it belongs to,
        so that `{variable: voltage, hold: 0.8 V}` and `{voltage: 0.8 V}` are one
        field (D19b). A class that declares `hold` itself has a single variable and
        keeps that spelling, so there is nothing to move."""
        if 'hold' in dct and 'hold' not in self.m_def.all_quantities:
            dct = {**dct}
            self._route_hold(dct)
        super().m_update_from_dict(dct, **kwargs)

    def _route_hold(self, dct: dict) -> None:
        """`dct`'s `hold` under the name of the variable that carries it. A `hold`
        with nowhere to go is remembered for `normalize()` to report (§7) rather than
        guessed at — and rather than dropped in silence, which is what NOMAD would do
        with a key the class does not declare."""
        value = dct.pop('hold')
        declared_variables = self.variables()
        controllable = [
            name for name, declared in declared_variables.items() if declared.control
        ]

        if isinstance(value, str) and value.strip() in self.numberless():
            dct[value.strip()] = True  # a word standing for no number (D8a)
            return

        named = dct.get('variable')
        if named is None and len(controllable) == 1:
            named = controllable[0]  # only one thing it could mean
        if named not in controllable:
            self.m_cache.setdefault(UNREADABLE_VALUES, {})['hold'] = (
                f'could not place `hold` {value!r}: say which variable it sets, as '
                f'`variable:` or as the key itself — '
                f'{", ".join(controllable) or "this channel has none"}.'
            )
            return
        dct[declared_variables[named].setpoint_field] = value

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        declared_variables = self.variables()
        if declared_variables:
            self.available_variables = list(declared_variables)
        # The file need not name a variable it cannot have meant: one setpoint is set,
        # and that is the one this command speaks about.
        if self.variable is None:
            asked = list(self.setpoints)
            if len(asked) == 1:
                self.variable = asked[0]
        elif (declared := declared_variables.get(self.variable)) is None:
            logger.error(
                f'`{self.variable}` is not something `{self.channel or "this channel"}` '
                f'can be asked to hold; it has '
                f'{", ".join(declared_variables) or "no variables"}.'
            )
        elif not declared.control:
            logger.error(
                f'`{self.variable}` is read from `{self.channel or "this channel"}`, '
                f'never asked of it.'
            )
        # One sampling figure is authored and the other follows from it, so whichever
        # the file wrote, everything downstream can read either (D9).
        if self.sampling_rate is None and self.sample_every is not None:
            self.sampling_rate = 1 / self.sample_every
        if self.sample_every is None and self.sampling_rate is not None:
            self.sample_every = 1 / self.sampling_rate


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

        # Deferred: channel_commands.py imports `ChannelCommand` from this module,
        # so a module-level import of the channel classes here would be circular.
        from nomad_pv_stability_measurements.schema_packages.channel_commands import (
            CHANNEL_CLASSES,
        )

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
