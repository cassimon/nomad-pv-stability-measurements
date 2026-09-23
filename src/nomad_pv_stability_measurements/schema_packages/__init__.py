from nomad.config.models.plugins import SchemaPackageEntryPoint


class StabilityProtocolEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        # A measurement's and a sample's classes are in packages of their own;
        # importing them registers them with NOMAD.
        from nomad_pv_stability_measurements.schema_packages import (  # noqa: F401
            measurement,
            sample,
        )
        from nomad_pv_stability_measurements.schema_packages.protocol import m_package

        return m_package


schema_package_entry_point = StabilityProtocolEntryPoint(
    name='PVStabilityMeasurements',
    description='Schema for PV stability test protocols.',
)
