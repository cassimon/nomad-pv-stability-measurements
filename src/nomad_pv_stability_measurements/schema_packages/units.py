import re

import numpy as np
import pint
from nomad.metainfo.data_type import m_float64
from nomad.units import ureg

# §6 step 0 — characters a human (or Word) writes that `float()` will not read.
_CHARACTER_FIXES = {
    '−': '-',  # true minus
    'µ': 'u',  # micro sign
    'μ': 'u',  # greek mu
    ' ': '',  # thin space
    ' ': ' ',  # non-breaking space
}

# §6 steps 2 and 4 — what this registry reads wrongly, or not at all, written as
# (factor, unit). pint reads a bare `h` as Planck's constant and `min` as milli-inch,
# both silently. Days are worse: this registry defines no `day`, `week` or `year`
# at all (verified), and `ureg.define()` is forbidden — the registry is shared with
# every other plugin — so a day is written as the hours it is, and a sun as the
# irradiance it is. Only a unit that is exactly one of these is aliased, so `ms` and
# `Hz` pass through untouched.
_UNIT_ALIASES = {
    'h': (1, 'hour'),
    'hr': (1, 'hour'),
    'hrs': (1, 'hour'),
    'min': (1, 'minute'),
    'd': (24, 'hour'),
    'day': (24, 'hour'),
    'days': (24, 'hour'),
    'sun': (1000, 'W/m^2'),
}

_NUMBER_AND_UNIT = re.compile(
    r'(?P<number>[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<unit>.*)'
)


def split_match_convert(text: str) -> tuple[float, str]:
    """`'24 h'` as `(24.0, 'hour')`, `'2 d'` as `(48.0, 'hour')`.

    A bare number is an error. Splitting the number off ourselves is also what
    makes offset units work
    """
    cleaned = text
    for written, readable in _CHARACTER_FIXES.items():
        cleaned = cleaned.replace(written, readable)

    match = _NUMBER_AND_UNIT.fullmatch(cleaned.strip())
    if match is None:
        raise ValueError(f'{text!r} is not a number followed by a unit')

    unit = match.group('unit').strip()
    if not unit:
        raise ValueError(f'{text!r} has no unit, and a bare number is ambiguous')

    factor, unit = _UNIT_ALIASES.get(unit, (1, unit))
    return float(match.group('number')) * factor, unit


def parse(text: str, expected) -> ureg.Quantity:
    """`text` as a quantity in `expected`'s unit; a wrong dimension raises (§6 step 5)."""
    number, unit = split_match_convert(text)
    return ureg.Quantity(number, unit).to(expected)


def parse_duration(text: str) -> ureg.Quantity:
    """`'24 h'` -> 86400 s."""
    return parse(text, ureg.second)


def parse_frequency(text: str) -> ureg.Quantity:
    """`'10 Hz'` -> 10 Hz."""
    return parse(text, ureg.hertz)


#: Where `StabilityUnitAwareFloat` leaves what it could not read, for
#: `StabilityUnitAwareSection.normalize` to report (D19a, routine.py).
UNREADABLE_VALUES = 'unreadable_values'


class StabilityUnitAwareFloat(m_float64):
    """A float quantity whose value may be authored with its unit (D19).

    NOMAD's stock float takes a bare number in the declared unit and rejects
    `'500 h'`. This is the same float, plus a string step in front of it: the text
    is parsed against the field's own `unit=` and handed on as a pint quantity,
    which `m_float64` already knows how to convert and store. So
    `duration: 500 h` lands as `1800000.0` seconds — the file keeps its unit, the
    archive keeps a number.

    Declared per field, the way NOMAD's own `Datetime` type is:

        duration = Quantity(type=StabilityUnitAwareFloat(), unit='s')
        hold = Quantity(
            type=StabilityUnitAwareFloat(named={'dark': '0 W/m^2'}), unit='W/m^2'
        )

    `named` gives words that stand for values (D8a) — they belong to the one field
    they can be written into, not to every unit-ful field on the section.

    Text that does not parse never raises: it is remembered on the section and
    reported by `StabilityUnitAwareSection.normalize` (routine.py), so one bad
    value does not stop the entry from loading (§7). The field is left unset.
    """

    __slots__ = ('_named',)

    def __init__(self, *, named: dict[str, str] | None = None):
        # np.float64, not the base class's default python float, so the schema
        # serializes exactly as the `type=np.float64` declarations it replaced.
        super().__init__(dtype=np.float64)
        self._named = named or {}

    def normalize(self, value, **kwargs):
        if isinstance(value, str):
            value = self._read(value.strip(), kwargs.get('section'))
            if value is None:
                return None
        return super().normalize(value, **kwargs)

    def _read(self, authored: str, section):
        """`authored` as a pint quantity, or `None` with a complaint left on `section`."""
        name = self._definition.name
        # A later, valid value clears what this field complained about before: an
        # ELN edit sets the field again, through this same type.
        unreadable = (
            section.m_cache.setdefault(UNREADABLE_VALUES, {}) if section else {}
        )
        unreadable.pop(name, None)

        if not authored:
            return None  # blank text asks nothing, like never setting it (D8)
        try:
            return parse(self._named.get(authored, authored), self.unit)
        except (ValueError, pint.errors.PintError) as error:
            # The complaint quotes what the file wrote, not what a name resolved to.
            unreadable[name] = f'could not read `{name}` {authored!r}: {error}'
            return None
