"""How long things last: the lengths of time in a plan.

A `Duration` is a length of time, whatever it is the length of: how long an instruction
or a plan lasts, or the time from one measurement to the next. The field it fills says
which. Each kind of length is a class of its own, which says what it is and how it counts:
a `FiniteDuration` has a value, which may be only typical; a `DerivedDuration` is one
worked out from what an instruction or plan holds; an `OpenEndedDuration` is decided
outside the plan; a `WholeBlockDuration` lasts as long as its block. What lasts a while,
an instruction or a plan, is `Timed`: it states its duration, or works it out.

To add lengths up, each gives its `Span`: its seconds, and whether some of it is only
typical. How a block or a plan runs what it holds, one after another or all at once, is
not decided here: it is the instructions' to say.
"""

from dataclasses import dataclass
from math import inf

import numpy as np
from nomad.datamodel.data import ArchiveSection
from nomad.metainfo import Quantity, SchemaPackage, SubSection
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.utils import shown

m_package = SchemaPackage()


@dataclass(frozen=True)
class Span:
    """A length of time to count with: `seconds`, `inf` where nothing ends it, and
    whether some of it is only `typical`."""

    seconds: float = inf
    typical: bool = False

    def __add__(self, other: 'Span') -> 'Span':
        return Span(self.seconds + other.seconds, self.typical or other.typical)

    def __mul__(self, count: float) -> 'Span':
        return Span(self.seconds * count, self.typical)

    @property
    def ends(self) -> bool:
        return self.seconds < inf

    @staticmethod
    def total(spans) -> 'Span':
        """`spans` one after another: their sum. Nothing takes no time."""
        return sum(spans, Span(0.0))

    @staticmethod
    def longest(spans) -> 'Span':
        """`spans` all at once: as long as the longest, and typical where any of them
        is. Nothing takes no time."""
        spans = list(spans)
        return Span(
            max((each.seconds for each in spans), default=0.0),
            any(each.typical for each in spans),
        )

    def as_duration(self) -> 'Duration':
        """This span as a duration worked out: open-ended where nothing ends it."""
        if not self.ends:
            return OpenEndedDuration()
        return DerivedDuration(value=self.seconds * ureg.second, typical=self.typical)

    def written_for_plotting(self) -> str:
        """As a figure's title gives it: `725 h`, `≈ 725 h` where some of it is only
        typical; empty where nothing ends it."""
        if not self.ends:
            return ''
        length = shown(self.seconds * ureg.second, exact=not self.typical)
        return f'≈ {length}' if self.typical else length

    def titled_for_plotting(self, title: str) -> str:
        """`title`, and this length where it has one: `soak · ≈ 725 h`."""
        length = self.written_for_plotting()
        return f'{title} · {length}' if length and title else title or length


class Duration(ArchiveSection):
    """A length of time: how long an instruction or a plan lasts, or the time from one
    repetition to the next, as the field it fills says. Each kind of length is a
    subclass: `FiniteDuration` (with a value), `OpenEndedDuration`, `WholeBlockDuration`
    and, worked out, `DerivedDuration`. This class itself says no kind, and so is reported
    where it is written: as nothing ends it, it never ends.
    """

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if type(self) is Duration:
            owner, field = self.owner()
            logger.error(
                f'{owner} writes a bare `Duration` as its `{field}`, which does not say '
                f'what kind of length it is: write a FiniteDuration, an '
                f'OpenEndedDuration or a WholeBlockDuration.'
            )

    def owner(self) -> tuple[str, str]:
        """Whose length it is, by name, and in which of its fields."""
        owner = getattr(self.m_parent, 'name', None) or '<unnamed>'
        sub_section = self.m_parent_sub_section
        return owner, sub_section.name if sub_section else 'length'

    def span(self) -> Span:
        """How long it is, to count with. A length with no value never ends."""
        return Span()

    def written(self, about: str = '≈ ') -> str:
        """The length as a label says it, `12 h`, after `about` where it is only
        typical; nothing where it has no value."""
        return ''

    def typical_for_plotting(self) -> str | None:
        """What it typically lasts, where it is only a typical length; `None`
        otherwise."""
        return None

    @staticmethod
    def together(durations, parallel: bool) -> Span:
        """How long `durations` last together: all at once (`parallel`), the longest,
        not counting one that lasts as long as its block, and never ending where
        nothing else is there; one after another, their sum. A missing one, or one
        that never ends, makes the whole never end."""
        durations = list(durations)

        def span(duration) -> Span:
            return Span() if duration is None else duration.span()

        if not parallel:
            return Span.total(span(each) for each in durations)
        deciding = [
            each for each in durations if not isinstance(each, WholeBlockDuration)
        ]
        if durations and not deciding:
            return Span()
        return Span.longest(span(each) for each in deciding)


class FiniteDuration(Duration):
    """A length of `value`: exactly that, or, where it is `typical`, about that."""

    value = Quantity(
        type=np.float64,
        unit='s',
        description='The length. Required, and positive.',
    )
    typical = Quantity(
        type=bool,
        default=False,
        description='Whether the length is only a typical one: it takes a time the plan '
        'does not fix, and `value` is a typical one, to add up and draw the plan with. '
        'Of a length worked out, whether some part of it is.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        owner, field = self.owner()
        if self.value is None:
            logger.error(f'{owner} writes a `{field}` of a length, but no value.')
        elif self.value <= 0:
            logger.error(
                f'{owner} writes a `{field}` of {self.value.to("s").magnitude:g} s: '
                f'it must be positive.'
            )

    def span(self) -> Span:
        if self.value is None:
            return Span()
        return Span(self.value.to('s').magnitude, bool(self.typical))

    def written(self, about: str = '≈ ') -> str:
        if self.value is None:
            return ''
        return f'{about if self.typical else ""}{shown(self.value)}'

    def typical_for_plotting(self) -> str | None:
        return self.written('typically ') if self.typical else None


class DerivedDuration(FiniteDuration):
    """A length worked out from what an instruction or plan holds, as a block's is from
    its sub-instructions; never written by hand. Worked out again, it is replaced."""


class OpenEndedDuration(Duration):
    """A length the plan does not fix, decided outside it: an instruction that lasts
    until something stops it, such as an objective being reached or the operator, or
    measurements repeated as often as whoever runs the test chooses."""


class WholeBlockDuration(Duration):
    """As long as the block or plan it is in, which runs it in parallel with the rest:
    it does not count toward that length. One after another, or in no block, there is
    no whole to last as long as."""


class Timed(ArchiveSection):
    """What lasts a while, an instruction or a plan: inherited next to what it is. It
    states its `duration`, or works it out from what it holds."""

    duration = SubSection(
        section_def=Duration,
        description='How long it lasts, and what kind of length that is.',
    )

    def derive_duration(self) -> Duration | None:
        """Its duration, worked out from what it holds or what is written in it;
        `None` where it has none to work out, and states one instead."""
        return None

    def states_its_duration(self) -> bool:
        """Whether its duration is written, rather than worked out."""
        return self.duration is not None and not isinstance(
            self.duration, DerivedDuration
        )

    def span(self) -> Span:
        """How long it lasts, to count with; it never ends where it has no duration."""
        return Span() if self.duration is None else self.duration.span()

    def seconds(self) -> float:
        """How long it lasts in seconds; `inf` where it has no length of its own."""
        return self.span().seconds

    def settle_duration(self, logger) -> None:
        """The duration it works out itself, where it does; else the one it states.
        Only what works it out writes a derived one."""
        derived = self.derive_duration()
        if derived is not None:
            self.duration = derived
            return
        name = getattr(self, 'name', None) or '<unnamed>'
        stated = 'a FiniteDuration, an OpenEndedDuration or a WholeBlockDuration'
        if self.duration is None:
            logger.error(f'{name} states no duration: write {stated}.')
        elif isinstance(self.duration, DerivedDuration):
            logger.error(
                f'{name} has a derived duration, but nothing to derive it from: write '
                f'{stated}.'
            )


m_package.__init_metainfo__()
