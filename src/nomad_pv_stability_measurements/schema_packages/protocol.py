from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.basesections import BaseSection
from nomad.metainfo import SchemaPackage, SubSection

from nomad_pv_stability_measurements.schema_packages.channel_commands import (
    IrradiationChannelCommand,
    TemperatureChannelCommand,
)
from nomad_pv_stability_measurements.schema_packages.routine import Routine

m_package = SchemaPackage()


class ChannelSettings(ArchiveSection):
    """
    The baseline: one optional block per channel, holding for the whole run.

    A routine command on the same channel overrides it for that command's span.
    A channel with no block is unregulated and unlogged — which is also what it
    is wherever nothing says otherwise.
    """

    temperature = SubSection(section_def=TemperatureChannelCommand)
    irradiation = SubSection(section_def=IrradiationChannelCommand)


class StabilityProtocol(BaseSection, EntryData):
    """A PV stability test protocol: channel settings and the routine that runs."""

    channel_settings = SubSection(section_def=ChannelSettings)
    routine = SubSection(section_def=Routine)


m_package.__init_metainfo__()
