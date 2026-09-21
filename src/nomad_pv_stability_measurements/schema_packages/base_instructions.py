from math import isclose

import numpy as np
from nomad.metainfo import MEnum, Quantity, SchemaPackage
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import SingleInstruction
from nomad_pv_stability_measurements.schema_packages.utils import shown, words

m_package = SchemaPackage()


class MonitorControlInstruction(SingleInstruction):
    """
    One quantity, monitored, controlled, or both.
    """

    #: The start of a class name that says the kind, not the quantity: `Hold` in
    #: `HoldTemperature`. Empty for a class that names what it does as a whole.
    kind = ''

    monitor = Quantity(
        type=bool,
        description='Log data from this quantity.',
    )
    control = Quantity(
        type=bool,
        description='Regulate this quantity.',
    )
    sample_every = Quantity(
        type=np.float64,
        unit='s',
        description='How often to sample. Write this or `sampling_rate`; the other '
        'is derived from it.',
    )
    sampling_rate = Quantity(
        type=np.float64,
        unit='Hz',
        description='How fast to sample a continuous stream. Write this or '
        '`sample_every`; the other is derived from it.',
    )
    reference_point = Quantity(
        type=str,
        description="A point on the device's own characteristic that the value is taken "
        'from, where the protocol names one instead of a number — e.g. `V_MPP`, measured '
        'on the fresh device. Free text here; an instruction class that has such points narrows '
        'it to the ones it takes (Design.md §20.3).',
    )

    def describe(self) -> str:
        """`Hold temperature 65 °C`; `Monitor relative humidity` where the quantity is
        only logged."""
        name = type(self).__name__
        if not self.kind or not name.startswith(self.kind):
            return words(name) + self.describe_values()
        verb = 'Monitor' if self.monitor and not self.control else 'Hold'
        if self.kind == 'Ramp' and verb == 'Hold':
            verb = 'Ramp'
        return f'{verb} {self.quantity_name()}{self.describe_values()}'

    def quantity_name(self) -> str:
        """What it monitors or controls, in words: `temperature` in `HoldTemperature`."""
        quantity = words(type(self).__name__.removeprefix(self.kind))
        return quantity if quantity[:2].isupper() else quantity.lower()

    def describe_values(self) -> str:
        """What follows the quantity: its value, point or bounds."""
        if self.reference_point is not None:
            return f' at {self.reference_point}'
        return ''

    def set_values_for_plotting(self, length):
        """What the protocol sets the quantity to over `length` of this instruction, as
        `(times, values)` at the corners of the line, times from its own start. `None`
        where the protocol states no value: a point the device decides, bounds, or
        nothing at all. `length` is how long it is drawn — its `duration`, or less."""
        return None

    def row_for_plotting(self) -> str:
        """One row per quantity, whichever instruction acts on it."""
        return self.quantity_name()

    def annotation_for_plotting(self) -> str:
        """What is written in place of a value, where `set_values_for_plotting` gives none."""
        if self.reference_point is not None:
            return self.reference_point
        if self.monitor and not self.control:
            return 'monitored'
        return 'not specified'

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # Whichever sampling figure was written, both are stored, so everything
        # downstream can read either (D9).
        if self.sampling_rate is None and self.sample_every is not None:
            self.sampling_rate = 1 / self.sample_every
        if self.sample_every is None and self.sampling_rate is not None:
            self.sample_every = 1 / self.sampling_rate
        if type(self) in ABSTRACT_INSTRUCTIONS:
            logger.error(
                f'{self.name or "<unnamed>"} is a bare '
                f'`{type(self).__name__}`, which names no quantity: use one of the '
                f'instruction classes in `hold_instructions.py`, `hold_below_instructions.py` or '
                f'`ramp_instructions.py`.'
            )


class HoldInstruction(MonitorControlInstruction):
    """One value, held for as long as the instruction lasts (§15.11)."""

    set_point = Quantity(
        type=np.float64,
        description='The value to hold. Each instruction class declares it in its own unit.',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        description='How far either side of `set_point` still counts: `set_point ± '
        'set_point_tolerance`. A difference, so a temperature tolerance is in kelvin — '
        '`4 K`, never `4 °C` (§17.4). Each instruction class declares it in its own unit.',
    )

    kind = 'Hold'

    def describe_values(self) -> str:
        value = f' {shown(self.set_point)}' if self.set_point is not None else ''
        return value + super().describe_values() + held_for(self)

    def set_values_for_plotting(self, length):
        if self.set_point is None:
            return None
        return line([0, length.to('s').magnitude], [0, 0], self.set_point, 0)


class HoldBelowInstruction(MonitorControlInstruction):
    """One value, kept under a bound for as long as the instruction lasts."""

    upper_bound = Quantity(
        type=np.float64,
        description='The most the value may be. Each instruction class declares it in its own '
        'unit.',
    )

    kind = 'HoldBelow'

    def describe_values(self) -> str:
        if self.upper_bound is None:
            return held_for(self)
        return f' below {shown(self.upper_bound)}' + held_for(self)

    def annotation_for_plotting(self) -> str:
        if self.upper_bound is None:
            return super().annotation_for_plotting()
        return f'below {shown(self.upper_bound)}'


class HoldBetweenInstruction(HoldBelowInstruction):
    """One value, kept between two bounds for as long as the instruction lasts."""

    lower_bound = Quantity(
        type=np.float64,
        description='The least the value may be. Each instruction class declares it in its own '
        'unit.',
    )

    kind = 'HoldBetween'

    def describe_values(self) -> str:
        if self.lower_bound is None or self.upper_bound is None:
            return held_for(self)
        return (
            f' between {shown(self.lower_bound)} and {shown(self.upper_bound)}'
            + held_for(self)
        )

    def annotation_for_plotting(self) -> str:
        if self.lower_bound is None or self.upper_bound is None:
            return super().annotation_for_plotting()
        return f'{shown(self.lower_bound)}–{shown(self.upper_bound)}'

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if type(self) in ABSTRACT_INSTRUCTIONS:
            return  # already reported, and the base's own fields carry no unit
        where = self.name or '<unnamed>'
        if self.lower_bound is None or self.upper_bound is None:
            logger.error(
                f'{where} keeps a value between two bounds but is missing one: write '
                f'both `lower_bound` and `upper_bound`.'
            )
        elif self.lower_bound > self.upper_bound:
            logger.error(
                f'{where} writes a `lower_bound` above its `upper_bound`, so no value '
                f'lies between them.'
            )


class RampInstruction(MonitorControlInstruction):
    """One value, moving from `start_point` to `end_point` over the instruction ."""

    start_point = Quantity(
        type=np.float64,
        description='The value the instruction starts from. Each instruction class declares it in '
        'its own unit.',
    )
    end_point = Quantity(
        type=np.float64,
        description='The value the instruction moves to. Each instruction class declares it in its '
        'own unit.',
    )
    ramp_rate = Quantity(
        type=np.float64,
        description='How fast the value moves, as a positive magnitude — the direction '
        'is `start_point` to `end_point`. Write this or `duration`; the '
        'other is derived from it (D16).',
    )
    end_of_ramp_behavior = Quantity(
        type=MEnum('hold', 'sawtooth', 'triangle', 'cycle'),
        default='hold',
        description='Whether the ramp runs once and then holds end_point until the end of the instruction duration, '
        'repeats with an abrupt jump back to `start_point`, '
        'repeats with a downward ramp at the same rate back to `start_point`, '
        'or cycles back to `start_point` by a path the protocol does not state ',
    )

    kind = 'Ramp'

    def describe_values(self) -> str:
        """The ends, and how it goes on — never the duration, which may be derived."""
        values = ''
        if self.start_point is not None and self.end_point is not None:
            values = f' {shown(self.start_point)} → {shown(self.end_point)}'
        if self.end_of_ramp_behavior != 'hold':
            values += f' ({self.end_of_ramp_behavior})'
        return values

    def set_values_for_plotting(self, length):
        """Once to `end_point` and held there (`hold`), again and again with a jump back
        (`sawtooth`), or up and down (`triangle`). A `cycle` states no path, so no value."""
        period = self.ramp_period()
        if period is None:
            return None
        shape = RAMP_SHAPES[self.end_of_ramp_behavior]
        times, phases = shape(period, length.to('s').magnitude)
        return line(times, phases, self.start_point, self.end_point - self.start_point)

    def ramp_period(self) -> float | None:
        """How long one ramp from `start_point` to `end_point` takes, in seconds: from
        `ramp_rate`, else from `duration`. `None` where the path is not stated."""
        start, end = self.start_point, self.end_point
        if start is None or end is None or self.end_of_ramp_behavior == 'cycle':
            return None
        if self.ramp_rate is not None:
            rate = self.ramp_rate.to(start.units / ureg.second).magnitude
            return abs((end - start).to(start.units).magnitude / rate)
        if self.duration is not None:
            return self.duration.to('s').magnitude
        return None

    def annotation_for_plotting(self) -> str:
        if self.end_of_ramp_behavior == 'cycle' and self.describe_values():
            return self.describe_values().strip()
        return super().annotation_for_plotting()

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if type(self) in ABSTRACT_INSTRUCTIONS:
            return  # already reported, and the base's own fields carry no unit
        where = self.name or '<unnamed>'
        if self.start_point is None or self.end_point is None:
            logger.error(
                f'{where} moves between two values but is missing an end: write both '
                f'`start_point` and `end_point`.'
            )
            return
        if self.end_of_ramp_behavior == 'cycle':
            if self.ramp_rate is not None:
                logger.error(
                    f'{where} cycles by a path the protocol does not state, so it has '
                    f'no `ramp_rate`: write `triangle` or `sawtooth` for a linear one.'
                )
            return
        span = abs(self.end_point - self.start_point)
        # The rate and the duration say one thing, so whichever was written, both are
        # stored (D16, as the sampling pair is).
        if self.ramp_rate is None and self.duration is not None:
            self.ramp_rate = span / self.duration
        elif self.ramp_rate is not None and self.duration is None:
            self.duration = span / self.ramp_rate
        elif self.ramp_rate is not None:
            self.report_a_rate_that_contradicts_the_duration(span, where, logger)

    def report_a_rate_that_contradicts_the_duration(self, span, where, logger):
        """Reported, never repaired: both stand as authored (D13a)."""
        derived = span / self.duration
        written = self.ramp_rate.to(derived.units)
        if isclose(written.magnitude, derived.magnitude, rel_tol=1e-9):
            return
        logger.error(
            f'{where} writes a `ramp_rate` of {written.magnitude:g} {derived.units}, '
            f'but its ends over an `duration` of '
            f'{self.duration.to("s").magnitude:g} s make it '
            f'{derived.magnitude:g}.'
        )


def line(times, phases, start, span):
    """The corners `(times, values)` of a line: `times` in seconds, each value `start`
    plus `span` times its phase, in `start`'s unit."""
    span = span.to(start.units).magnitude if span else 0
    values = start.magnitude + span * np.asarray(phases, dtype=float)
    return np.asarray(times, dtype=float) * ureg.second, values * start.units


def hold_after_ramp(period: float, length: float):
    """Phases of a ramp that runs once, then holds its end."""
    if length <= period:
        return [0, length], [0, length / period]
    return [0, period, length], [0, 1, 1]


def sawtooth(period: float, length: float):
    """Phases of a ramp that jumps back to its start at the end of each period."""
    jumps = np.arange(period, length, period)
    last = jumps[-1] if len(jumps) else 0
    times = np.concatenate([[0], np.repeat(jumps, 2), [length]])
    phases = np.concatenate(
        [[0], np.tile([1, 0], len(jumps)), [(length - last) / period]]
    )
    return times, phases


def triangle(period: float, length: float):
    """Phases of a ramp that goes back down at the same rate, and up again."""
    times = np.append(np.arange(0, length, period), length)
    return times, 1 - np.abs(times / period % 2 - 1)


RAMP_SHAPES = {'hold': hold_after_ramp, 'sawtooth': sawtooth, 'triangle': triangle}


def held_for(instruction) -> str:
    """` for 12 h`, where a hold writes its duration; a hold never derives one."""
    if instruction.duration is None:
        return ''
    return f' for {shown(instruction.duration)}'


#: The bases that name no quantity: writing one directly is an authoring mistake.
ABSTRACT_INSTRUCTIONS = (
    MonitorControlInstruction,
    HoldInstruction,
    HoldBelowInstruction,
    HoldBetweenInstruction,
    RampInstruction,
)


m_package.__init_metainfo__()
