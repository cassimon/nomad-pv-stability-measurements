"""
The protocol tree, its search summary and the `StabilityProtocol` entry
(Design.md §4.2, §4.3).

A protocol is one recursive node type. A node that names a `channel` puts (one
variable of) it into a state for the node's span; a node with `steps` runs them
according to its `mode`.
"""

from typing import NamedTuple

from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import (
    ELNAnnotation,
    ELNComponentEnum,
    SectionDisplayAnnotation,
)
from nomad.datamodel.metainfo.basesections import BaseSection
from nomad.datamodel.metainfo.plot import PlotSection
from nomad.metainfo import (
    MEnum,
    Quantity,
    SchemaPackage,
    Section,
    SectionProxy,
    SubSection,
)

from nomad_pv_stability_measurements.schema_packages.channels import Channels
from nomad_pv_stability_measurements.schema_packages.states import (
    STATE_SLOTS,
    Cycle,
    Ramp,
    Sweep,
    Tabulated,
)
from nomad_pv_stability_measurements.schema_packages.timeline import ProtocolTimeline

m_package = SchemaPackage()


class State(NamedTuple):
    """The one state slot set on a protocol node, and its value."""

    slot: str
    value: bool | str | Ramp | Cycle | Tabulated | Sweep


def _is_set(value) -> bool:
    # `off: false` / `uncontrolled: false` say nothing, like an omitted slot.
    return value is not None and value is not False and value != ''


def _string(description: str, **kwargs) -> Quantity:
    return Quantity(
        type=str,
        description=description,
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
        **kwargs,
    )


def _flag(description: str) -> Quantity:
    return Quantity(
        type=bool,
        description=description,
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity),
    )


class Protocol(ArchiveSection):
    """
    A node of the protocol tree. A step opens with `channel` (it acts) or
    `subprotocol` (it contains `steps`); the root has neither and uses `name`.
    At most one state slot is set per node, and a `channel` node needs exactly one.
    """

    m_def = Section(
        # Keep the state slots together: quantities otherwise serialize before
        # all sub-sections, which would split them.
        a_display=SectionDisplayAnnotation(
            order=[
                'channel',
                'subprotocol',
                'variable',
                'name',
                'mode',
                'duration',
                'repetitions',
                'stop_when',
                *STATE_SLOTS,
                'duration_s',
                'steps',
            ]
        ),
    )

    channel = _string('Key of the channel this step acts on.')
    subprotocol = _string('Name of the block of `steps` this step contains.')
    variable = _string(
        'The channel variable the state targets. Required when the channel has more '
        'than one controllable variable.'
    )
    name = _string(
        'Authored on the root; derived on other nodes (`daily cycle`, '
        '`bias: track mpp`).'
    )
    mode = Quantity(
        type=MEnum('sequential', 'parallel'),
        default='sequential',
        description='How `steps` run. Children of a parallel node write disjoint '
        'control groups.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )
    duration = _string(
        "The node's span, e.g. `24 h` -- or a time cap if it would run longer."
    )
    repetitions = _string('An integer >= 1 or `forever`. Omitted: 1.')
    stop_when = _string(
        'A condition ending the node, e.g. `pce_relative < 80 %`. Recorded, not '
        'simulated.'
    )

    # --- scalar state slots
    uncontrolled = _flag('Release the variable or channel.')
    off = _flag('Irradiation only: deliberately dark.')
    hold = _string('A constant setpoint, e.g. `65 °C`.')
    track = Quantity(
        type=MEnum('mpp', 'voc', 'jsc'),
        description='Electrical load only: track an operating point.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    duration_s = Quantity(
        type=float,
        unit='second',
        description="The node's actual span (derived).",
    )

    # --- section state slots
    ramp = SubSection(section_def=Ramp)
    cycle = SubSection(section_def=Cycle)
    tabulated = SubSection(section_def=Tabulated)
    sweep = SubSection(section_def=Sweep)

    steps = SubSection(section_def=SectionProxy('Protocol'), repeats=True)

    def m_update_from_dict(self, data: dict, **kwargs):
        # NOMAD reads YAML 1.1, where the bare key `off` is the boolean false.
        if any(key is False for key in data):
            data = {
                'off' if key is False else key: value for key, value in data.items()
            }
        return super().m_update_from_dict(data, **kwargs)

    @property
    def state_slots(self) -> tuple[str, ...]:
        """Names of all state slots set on this node, in `STATE_SLOTS` order."""
        return tuple(slot for slot in STATE_SLOTS if _is_set(getattr(self, slot)))

    @property
    def state(self) -> State | None:
        """
        The node's state, or None for a pure container. Raises ValueError if more
        than one slot is set -- check `state_slots` first when validating.
        """
        slots = self.state_slots
        if not slots:
            return None
        if len(slots) > 1:
            raise ValueError(f'more than one state slot set: {", ".join(slots)}')
        return State(slots[0], getattr(self, slots[0]))


class ProtocolSummary(ArchiveSection):
    """
    Flat, searchable facts about a protocol (derived, read-only). Only scalar
    quantities are indexed for search, so lists are stored as comma-joined strings.
    """

    total_duration = Quantity(type=float, unit='hour')
    truncated = Quantity(type=bool)
    estimated = Quantity(type=bool)

    temperature_controlled = Quantity(type=bool)
    temperature_monitored = Quantity(type=bool)
    irradiation_controlled = Quantity(type=bool)
    irradiation_monitored = Quantity(type=bool)
    humidity_controlled = Quantity(type=bool)
    humidity_monitored = Quantity(type=bool)
    oxygen_controlled = Quantity(type=bool)
    oxygen_monitored = Quantity(type=bool)
    electrical_load_controlled = Quantity(type=bool)
    electrical_load_monitored = Quantity(type=bool)

    temperature_min = Quantity(
        type=float,
        unit='kelvin',
        description='Time-weighted over setpoints; empty if uncontrolled.',
        a_display={'unit': 'degC'},
    )
    temperature_max = Quantity(
        type=float,
        unit='kelvin',
        description='Time-weighted over setpoints; empty if uncontrolled.',
        a_display={'unit': 'degC'},
    )
    temperature_mean = Quantity(
        type=float,
        unit='kelvin',
        description='Time-weighted over setpoints; empty if uncontrolled.',
        a_display={'unit': 'degC'},
    )
    irradiance_mean = Quantity(
        type=float,
        unit='W/m^2',
        description='Time-weighted; `off` counts as 0.',
    )
    humidity_kind = Quantity(
        type=str,
        description='The humidity kind (`relative` ...), or `mixed`.',
    )
    humidity_mean = Quantity(
        type=float,
        description='In the canonical unit of `humidity_kind`; empty if mixed.',
    )
    atmosphere_label = Quantity(
        type=str,
        description='The balance gas, or `ambient` if uncontrolled.',
    )
    load_condition_label = Quantity(type=str, description='E.g. `track mpp + sweep`.')
    channels_used = Quantity(type=str, description='E.g. `bias, chuck_T, sun`.')
    states_used = Quantity(type=str, description='E.g. `hold, sweep, track`.')
    is_cyclic = Quantity(type=bool, description='Any cycle state or repetitions > 1.')
    n_jv_sweeps = Quantity(type=int, description='Sweeps up to `total_duration`.')


class StabilityProtocol(BaseSection, EntryData, PlotSection):
    """
    A PV stability test protocol: the channels it uses and a tree of steps. The
    timeline, summary and figures are derived from them.
    """

    version = _string('Version of this protocol.')
    isos_specification = _string('The ISOS protocol followed, e.g. `ISOS-L-2`.')
    isos_deviations = _string('How this protocol deviates from the ISOS one.')
    horizon = _string(
        'Where to cut an unbounded protocol, e.g. `1000 h`. Required only if the '
        'tree is unbounded.'
    )

    channels = SubSection(section_def=Channels)
    protocol = SubSection(section_def=Protocol, description='The root node.')
    timeline = SubSection(section_def=ProtocolTimeline, description='Derived.')
    summary = SubSection(section_def=ProtocolSummary, description='Derived.')


m_package.__init_metainfo__()
