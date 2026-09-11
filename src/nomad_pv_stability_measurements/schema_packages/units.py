"""Parsing authored value strings into pint quantities (Design.md §6).

The one place that calls pint. Everything else asks for a parsed value from here,
so the traps below are handled once — including `WrittenUnits` at the bottom, which
is how a written unit reaches a quantity that stores a plain number (D19).
"""

import re

import pint
from nomad.datamodel.data import ArchiveSection
from nomad.units import ureg

# §6 step 0 — characters a human (or Word) writes that `float()` will not read.
_CHARACTER_FIXES = {
    '−': '-',  # true minus
    'µ': 'u',  # micro sign
    'μ': 'u',  # greek mu
    ' ': '',  # thin space
    ' ': ' ',  # non-breaking space
}

# §6 step 2 — pint reads a bare `h` as Planck's constant and `min` as milli-inch,
# both silently. Days are worse: this registry defines no `day`, `week` or `year`
# at all (verified), and `ureg.define()` is forbidden — the registry is shared with
# every other plugin — so a day is written as the hours it is. Only a unit that is
# exactly one of these is aliased, so `ms` and `Hz` pass through untouched.
_UNIT_ALIASES = {
    'h': (1, 'hour'),
    'hr': (1, 'hour'),
    'hrs': (1, 'hour'),
    'min': (1, 'minute'),
    'd': (24, 'hour'),
    'day': (24, 'hour'),
    'days': (24, 'hour'),
}

_NUMBER_AND_UNIT = re.compile(
    r'(?P<number>[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<unit>.*)'
)


def split(text: str) -> tuple[float, str]:
    """`'24 h'` as `(24.0, 'hour')`, `'2 d'` as `(48.0, 'hour')`.

    A bare number is an error (D6). Splitting the number off ourselves is also what
    makes offset units work: `ureg.Quantity('65 °C')` raises, `ureg.Quantity(65, '°C')`
    does not.
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
    number, unit = split(text)
    return ureg.Quantity(number, unit).to(expected)


def parse_duration(text: str) -> ureg.Quantity:
    """`'24 h'` -> 86400 s."""
    return parse(text, ureg.second)


def parse_frequency(text: str) -> ureg.Quantity:
    """`'10 Hz'` -> 10 Hz."""
    return parse(text, ureg.hertz)


#: Where `m_set` leaves what it could not read, for `normalize()` to report (D19a).
_UNREADABLE = 'unreadable_values'


class WrittenUnits(ArchiveSection):
    """A section whose unit-ful quantities also accept the unit written out (D19).

    `Quantity(type=np.float64, unit='s')` natively takes a bare number of seconds and
    rejects `'500 h'`, which would make the file unreadable or the archive untyped —
    an earlier draft paid for both with a string field and a typed twin beside it.
    Reading the string one step earlier costs one override: `m_set` is the single
    gateway every assignment passes through (**verified** — `m_from_dict`,
    `m_update_from_dict` and `Section(**kwargs)` all funnel into it), so parsing there
    hands NOMAD a pint quantity, which its own type normalization converts and stores.
    One field, authored with its unit and held as a number.
    """

    def m_set(self, def_or_name, value, **kwargs):
        definition = self._ensure_definition(def_or_name, hint=kwargs.get('hint'))
        unit = getattr(definition, 'unit', None)
        if isinstance(value, str) and unit is not None:
            # Whatever is set now replaces what was complained about before: the ELN
            # edits a field by setting it again, through this same gateway.
            unreadable = self.m_cache.setdefault(_UNREADABLE, {})
            unreadable.pop(definition.name, None)
            if not value.strip():
                return  # asking nothing is the neutral element (D8)
            try:
                value = parse(value, unit)
            except (ValueError, pint.errors.PintError) as error:
                # Reported by `normalize()`, never raised: a typo in one value must not
                # stop the entry from loading (§7). The field stays unset.
                unreadable[definition.name] = (
                    f'could not read `{definition.name}` {value!r}: {error}'
                )
                return
        return super().m_set(def_or_name, value, **kwargs)

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        for complaint in self.m_cache.get(_UNREADABLE, {}).values():
            logger.error(complaint)
