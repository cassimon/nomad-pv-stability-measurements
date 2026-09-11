"""
States a protocol step can put a channel variable into (Design.md §4.2).

The scalar states (`uncontrolled`, `off`, `hold`, `track`) are plain quantities on the
`Protocol` node; the states with several fields are the sections defined here. Every
value is a unit string (`65 °C`, `50 mV/s`), parsed later by the normalize pipeline.
"""

from nomad.datamodel.data import ArchiveSection
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum
from nomad.metainfo import MEnum, Quantity, SchemaPackage

m_package = SchemaPackage()

# Every state slot of a `Protocol` node, in ELN order.
STATE_SLOTS = (
    'uncontrolled',
    'off',
    'hold',
    'track',
    'ramp',
    'cycle',
    'tabulated',
    'sweep',
)

# Accepted by every channel; channels extend this set in `accepted_states`.
GENERIC_STATES = frozenset({'uncontrolled', 'hold', 'ramp', 'cycle', 'tabulated'})


def _string(description: str, **kwargs) -> Quantity:
    return Quantity(
        type=str,
        description=description,
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
        **kwargs,
    )


class Ramp(ArchiveSection):
    """
    A linear change from `from` to `to`. Needs exactly one of `rate` or the node's
    `duration`; with a `rate`, the ramp determines its node's length.
    """

    # `from` is a Python keyword: read `from:` via the alias, serialized as `from_`.
    from_ = _string('Start value, e.g. `65 °C`.', aliases=['from'])
    to = _string('End value, e.g. `25 °C`.')
    rate = _string(
        'Positive magnitude, e.g. `0.4 K/h`; the direction follows from `from` -> `to`.'
    )


class Cycle(ArchiveSection):
    """
    A periodic setpoint between `low` and `high`. Square: `high` for
    `duty_cycle` x `period`, then `low`. Triangle and sine start at `low` and peak at
    `period` / 2.
    """

    waveform = Quantity(
        type=MEnum('square', 'triangle', 'sine'),
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )
    low = _string('Lower value, e.g. `25 °C`.')
    high = _string('Upper value, e.g. `85 °C`.')
    period = _string('Period, e.g. `24 h`.')
    duty_cycle = Quantity(
        type=float,
        description='Fraction of the period spent at `high`; square waveform only.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
    )


class Tabulated(ArchiveSection):
    """
    A setpoint given point by point. Times are relative to the node's start; the last
    time determines the node's length.
    """

    time = _string('Times relative to the node start, e.g. `[0 h, 1 h]`.', shape=['*'])
    value = _string('One value per time, e.g. `[25 °C, 85 °C]`.', shape=['*'])
    interpolation = Quantity(
        type=MEnum('linear', 'step'),
        default='linear',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )


class Sweep(ArchiveSection):
    """
    An I-V sweep on `voltage` or `current` (electrical load only). Its length is
    |to - from| / rate, twice that for `direction: both`.
    """

    from_ = _string('Start value, e.g. `-0.2 V`.', aliases=['from'])
    to = _string('End value, e.g. `1.3 V`.')
    rate = _string('Sweep rate, e.g. `50 mV/s`.')
    direction = Quantity(
        type=MEnum('forward', 'reverse', 'both'),
        default='forward',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )


m_package.__init_metainfo__()
