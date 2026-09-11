"""
The `StabilityProtocol` entry: channel settings plus the routine (Design.md §3,
§4.2, §4.3).

`channel_settings` holds one optional block per channel (Design.md §4.1),
commanding it for the whole run; a routine node commanding the same channel
overrides it for its own span. The routine tree itself — `Routine`,
`Subroutine`, and the two kinds of `RoutineCommand` — lives in `routine.py`.
"""

from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.basesections import BaseSection
from nomad.metainfo import SchemaPackage, SubSection

from nomad_pv_stability_measurements.schema_packages.routine import (
    Routine,
    TemperatureChannel,
)

m_package = SchemaPackage()


class ChannelSettings(ArchiveSection):
    """
    The baseline: one optional block per channel, holding for the whole run.

    A routine command on the same channel overrides it for that command's span.
    A channel with no block is unregulated and unlogged — which is also what it
    is wherever nothing says otherwise.
    """

    temperature = SubSection(section_def=TemperatureChannel)


class StabilityProtocol(BaseSection, EntryData):
    """A PV stability test protocol: channel settings and the routine that runs."""

    channel_settings = SubSection(section_def=ChannelSettings)
    routine = SubSection(section_def=Routine)


m_package.__init_metainfo__()
