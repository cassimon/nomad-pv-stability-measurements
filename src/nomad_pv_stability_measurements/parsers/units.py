import re

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
    # Volume ratios (§15.7). This registry knows `ppm` and `%`, both dimensionless, and
    # nothing else of the kind (verified), so the spellings a glovebox readout and a gas
    # bottle use are written as the two it does know.
    'ppb': (1e-3, 'ppm'),
    'ppmv': (1, 'ppm'),
    'ppbv': (1e-3, 'ppm'),
    'vol%': (1, 'percent'),
    'mol%': (1, 'percent'),
}

_NOT_OF_THE_ATMOSPHERE = 'relative humidity depends on the temperature'
_NOT_BY_VOLUME = 'a mass ratio is not a volume ratio, and is not converted into one'
_WRITE_A_VOLUME_RATIO = 'write the volume ratio itself, e.g. `500 ppm` or `2 %`'

# §15.7 — spellings this schema refuses rather than reads, each with what to write
# instead. Matched in lower case, since `%RH` is how it is usually written.
_REJECTED_UNITS = {
    '%rh': _NOT_OF_THE_ATMOSPHERE,
    'rh': _NOT_OF_THE_ATMOSPHERE,
    'wt%': _NOT_BY_VOLUME,
    'ppmw': _NOT_BY_VOLUME,
    'ppbw': _NOT_BY_VOLUME,
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

    refused = _REJECTED_UNITS.get(unit.lower())
    if refused is not None:
        raise ValueError(
            f'{text!r} is not a volume ratio: {refused}; {_WRITE_A_VOLUME_RATIO}'
        )

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
