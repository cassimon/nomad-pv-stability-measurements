from nomad.config.models.plugins import ParserEntryPoint


class StabilityYamlParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_pv_stability_measurements.parsers.isos_simulation import (
            StabilityYamlSimulatingParser,
        )

        return StabilityYamlSimulatingParser(**self.model_dump())


parser_entry_point = StabilityYamlParserEntryPoint(
    name='StabilityYamlParser',
    description='Reads an authored PV stability protocol (`*.stability.yaml`) into a '
    'StabilityProtocol entry; a protocol after an ISOS standard also gets a simulated '
    'run of it, as an entry of its own.',
    mainfile_name_re=r'.*\.stability\.ya?ml$',
)


class StabilitySimulationParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_pv_stability_measurements.parsers.simulation_parser import (
            StabilitySimulationParser,
        )

        return StabilitySimulationParser(**self.model_dump())


simulation_parser_entry_point = StabilitySimulationParserEntryPoint(
    name='StabilitySimulationParser',
    description='Simulates a run of a stability plan (`*.simulation.yaml`) into a '
    'StabilityMeasurement entry holding the set values of what the plan controls.',
    mainfile_name_re=r'.*\.simulation\.ya?ml$',
)
