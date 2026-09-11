"""
Channels: the devices a stability protocol controls and/or monitors (Design.md §4.1).

A channel is a table of named variables plus the control groups those variables form.
A new channel type is one `Channel` subclass supplying that table and one sub-section
in `Channels`; all behaviour lives in the base class.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from nomad.datamodel.data import ArchiveSection
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum
from nomad.datamodel.metainfo.basesections import InstrumentReference
from nomad.metainfo import Any, MEnum, Quantity, SchemaPackage, SubSection

from nomad_pv_stability_measurements.schema_packages.states import GENERIC_STATES

if TYPE_CHECKING:
    from collections.abc import Iterator

    from nomad.datamodel.datamodel import EntryArchive
    from structlog.stdlib import BoundLogger

m_package = SchemaPackage()

# Kind name of a variable that has only one quantity kind.
DEFAULT_KIND = 'default'


@dataclass(frozen=True)
class Kind:
    """
    A quantity kind of a variable (`relative`, `molar_ratio` ...) and the canonical
    unit its values are converted to. Values are never converted across kinds.
    """

    name: str
    unit: str


@dataclass(frozen=True)
class Variable:
    """
    A variable of a channel -- a schema constant, not metainfo.

    `kinds` may be given as a unit string, shorthand for a single kind with that
    canonical unit.
    """

    kinds: tuple[Kind, ...] | str
    display: str | None = None
    control: bool = True
    monitor: bool = True

    def __post_init__(self):
        if isinstance(self.kinds, str):
            object.__setattr__(self, 'kinds', (Kind(DEFAULT_KIND, self.kinds),))
        if not self.kinds:
            raise ValueError('a variable needs at least one kind')

    @property
    def kind_names(self) -> tuple[str, ...]:
        return tuple(kind.name for kind in self.kinds)

    def kind(self, name: str) -> Kind:
        for kind in self.kinds:
            if kind.name == name:
                return kind
        raise KeyError(f'unknown kind {name!r}, expected one of {self.kind_names}')


HUMIDITY_KINDS = (
    Kind('relative', 'dimensionless'),
    Kind('molar_ratio', 'mol/mol'),
    Kind('mass_ratio', 'kg/kg'),
    Kind('absolute', 'kg/m^3'),
    Kind('dew_point', 'K'),
    Kind('partial_pressure', 'Pa'),
)

OXYGEN_KINDS = (
    Kind('molar_ratio', 'mol/mol'),
    Kind('mass_ratio', 'kg/kg'),
    Kind('partial_pressure', 'Pa'),
)


class RegulationLaw(ArchiveSection):
    """How the channel regulates its setpoint. Metadata only."""

    kind = Quantity(
        type=MEnum('open_loop', 'pid', 'on_off', 'external'),
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )
    kp = Quantity(
        type=float,
        description='Proportional gain.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
    )
    ki = Quantity(
        type=float,
        description='Integral gain.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
    )
    kd = Quantity(
        type=float,
        description='Derivative gain.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.NumberEditQuantity),
    )
    hysteresis = Quantity(
        type=str,
        description='Switching hysteresis of an on/off law, e.g. `1 K`.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )


class Channel(ArchiveSection):
    """
    One device, used for control and/or monitoring. Abstract: use a subclass.
    """

    # --- the per-type table, supplied by each subclass
    variable_table: ClassVar[dict[str, Variable]] = {}
    control_groups: ClassVar[tuple[frozenset[str], ...]] = ()
    accepted_states: ClassVar[frozenset[str]] = GENERIC_STATES
    always_reported: ClassVar[bool] = False

    name = Quantity(
        type=str,
        description='Human-readable name; may be changed at any time.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    key = Quantity(
        type=str,
        description=(
            'Required stable identifier. Protocol steps, the timeline and parsers '
            'refer to the channel by this key.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    monitor_every = Quantity(
        type=str,
        description='Monitoring interval, e.g. `60 s`. Omitted: not monitored.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    monitored = Quantity(
        type=str,
        shape=['*'],
        description='The monitored variables. Default: all monitorable ones.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    limits = Quantity(
        type=Any,
        description=(
            'Allowed range per variable as unit strings, `{variable: [min, max]}`; '
            'a plain `[min, max]` for single-variable channels.'
        ),
    )
    idle = Quantity(
        type=MEnum('uncontrolled', 'off'),
        default='uncontrolled',
        description='State between steps. `off` is accepted by irradiation only.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )
    variables = Quantity(
        type=str,
        shape=['*'],
        description='The variables of this channel type (derived).',
    )
    is_controlled = Quantity(
        type=bool,
        description='Some step sets a state other than `uncontrolled` (derived).',
    )
    is_monitored = Quantity(
        type=bool,
        description='`monitor_every` is set (derived).',
    )

    regulation = SubSection(section_def=RegulationLaw)
    instrument = SubSection(section_def=InstrumentReference)

    @classmethod
    def can_control(cls, variable: str) -> bool:
        return variable in cls.variable_table and cls.variable_table[variable].control

    @classmethod
    def can_monitor(cls, variable: str) -> bool:
        return variable in cls.variable_table and cls.variable_table[variable].monitor

    @classmethod
    def group_of(cls, variable: str) -> frozenset[str]:
        """The control group containing `variable`."""
        for group in cls.control_groups:
            if variable in group:
                return group
        raise KeyError(
            f'{cls.__name__} has no controllable variable {variable!r}, '
            f'expected one of {sorted(cls.controllable_variables())}'
        )

    @classmethod
    def controllable_variables(cls) -> tuple[str, ...]:
        return tuple(name for name in cls.variable_table if cls.can_control(name))

    @classmethod
    def monitorable_variables(cls) -> tuple[str, ...]:
        return tuple(name for name in cls.variable_table if cls.can_monitor(name))

    def m_update_from_dict(self, data: dict, **kwargs):
        # NOMAD reads YAML 1.1, where the bare value `off` is the boolean false.
        if data.get('idle') is False:
            data = {**data, 'idle': 'off'}
        return super().m_update_from_dict(data, **kwargs)

    def monitored_variables(self) -> tuple[str, ...]:
        """The variables actually logged: none unless `monitor_every` is set."""
        if not self.monitor_every:
            return ()
        if self.monitored:
            return tuple(self.monitored)
        return self.monitorable_variables()

    def normalize(self, archive: 'EntryArchive', logger: 'BoundLogger') -> None:
        super().normalize(archive, logger)
        # `is_controlled` depends on the protocol tree and is set by the protocol.
        self.variables = list(self.variable_table)
        self.is_monitored = bool(self.monitor_every)


class TemperatureChannel(Channel):
    """A heater, chuck or climate chamber setting the sample temperature."""

    variable_table = {'temperature': Variable('K', display='degC')}
    control_groups = (frozenset({'temperature'}),)
    always_reported = True


class IrradiationChannel(Channel):
    """A light source. `off` is deliberate dark; `uncontrolled` is lab light."""

    variable_table = {'irradiance': Variable('W/m^2', display='W/m^2')}
    control_groups = (frozenset({'irradiance'}),)
    accepted_states = GENERIC_STATES | {'off'}
    always_reported = True

    spectrum = Quantity(
        type=str,
        description='Spectrum of the source, e.g. `AM1.5G`.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )


class AtmosphereChannel(Channel):
    """
    The gas around the sample. Humidity and oxygen are set independently (e.g. by a
    gas mixer) and can each be given in several quantity kinds.
    """

    variable_table = {
        'humidity': Variable(HUMIDITY_KINDS),
        'oxygen': Variable(OXYGEN_KINDS),
        'total_pressure': Variable('Pa', display='mbar'),
    }
    control_groups = (
        frozenset({'humidity'}),
        frozenset({'oxygen'}),
        frozenset({'total_pressure'}),
    )
    always_reported = True

    balance_gas = Quantity(
        type=str,
        description='The balance gas, e.g. `N2`, `air` or `Ar`.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )


class ElectricalLoadChannel(Channel):
    """
    The electrical load on the cell. Voltage, current and resistance are tied by the
    cell's I-V curve, so they form one control group.
    """

    variable_table = {
        'voltage': Variable('V'),
        'current': Variable('A'),
        'resistance': Variable('ohm', monitor=False),
    }
    control_groups = (frozenset({'voltage', 'current', 'resistance'}),)
    accepted_states = GENERIC_STATES | {'track', 'sweep'}
    always_reported = True


class MechanicalChannel(Channel):
    """Mechanical stress on a flexible device."""

    variable_table = {
        'bend_radius': Variable('m', display='mm'),
        'strain': Variable('dimensionless', display='%'),
    }
    control_groups = (frozenset({'bend_radius', 'strain'}),)


class Channels(ArchiveSection):
    """All channels of a protocol, one repeating slot per channel type."""

    temperature = SubSection(section_def=TemperatureChannel, repeats=True)
    irradiation = SubSection(section_def=IrradiationChannel, repeats=True)
    atmosphere = SubSection(section_def=AtmosphereChannel, repeats=True)
    electrical_load = SubSection(section_def=ElectricalLoadChannel, repeats=True)
    mechanical = SubSection(section_def=MechanicalChannel, repeats=True)

    @classmethod
    def slot_types(cls) -> dict[str, type[Channel]]:
        """Slot name -> channel type, in declaration order."""
        return {
            name: sub_section.sub_section.section_cls
            for name, sub_section in cls.m_def.all_sub_sections.items()
        }

    def iter_channels(self) -> 'Iterator[Channel]':
        """All declared channels, slot by slot."""
        for slot in self.slot_types():
            yield from getattr(self, slot)


m_package.__init_metainfo__()
