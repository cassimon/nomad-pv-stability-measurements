from nomad.config.models.plugins import SchemaPackageEntryPoint


class StabilityProtocolEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_pv_stability_measurements.schema_packages.protocol import m_package

        return m_package


schema_package_entry_point = StabilityProtocolEntryPoint(
    name='PVStabilityMeasurements',
    description='Schema for PV stability test protocols.',
)


class StabilityMeasurementEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_pv_stability_measurements.schema_packages.measurement_plan import (
            m_package,
        )

        return m_package


measurement_schema_package_entry_point = StabilityMeasurementEntryPoint(
    name='PVStabilityMeasurementPlans',
    description='Schema for PV stability protocols run as measurements: flat steps with '
    'the time series of every controlled or monitored quantity.',
)
