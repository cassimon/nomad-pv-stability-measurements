from nomad.config.models.plugins import ParserEntryPoint


class StabilityYamlParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_pv_stability_measurements.parsers.parser import StabilityYamlParser

        return StabilityYamlParser(**self.model_dump())


parser_entry_point = StabilityYamlParserEntryPoint(
    name='StabilityYamlParser',
    description='Reads an authored PV stability protocol (`*.stability.yaml`) into a '
    'StabilityProtocol entry.',
    mainfile_name_re=r'.*\.stability\.ya?ml$',
)
