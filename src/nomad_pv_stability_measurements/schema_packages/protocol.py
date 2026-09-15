from nomad.datamodel.data import EntryData
from nomad.metainfo import SchemaPackage

# The protocol's steps name these classes; importing them registers them with NOMAD.
from nomad_pv_stability_measurements.schema_packages.general import PlannedProcess
from nomad_pv_stability_measurements.schema_packages.utils import normalize_steps

m_package = SchemaPackage()


class StabilityProtocol(PlannedProcess, EntryData):
    """A PV stability test protocol: the steps that run, in order.

    The first steps usually set what holds for the whole run: monitor/control steps
    without an `estimated_duration`. For increased reability,
    `.stability.yaml` distinguishes `channel_settings` and `routine`. However, in the schema,
    they are all just different steps, and the protocol's own steps run in sequence as assumed by the
    parent classes.
    """

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # The protocol's own steps run in sequence, like a sequential block's (§15.4).
        normalize_steps(self, 'sequential', logger)


m_package.__init_metainfo__()
