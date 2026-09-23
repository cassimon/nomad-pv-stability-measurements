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


class StabilityMeasurementParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_pv_stability_measurements.parsers.measurement_parser import (
            StabilityMeasurementParser,
        )

        return StabilityMeasurementParser(**self.model_dump())


measurement_parser_entry_point = StabilityMeasurementParserEntryPoint(
    name='StabilityMeasurementParser',
    description='Reads a PV stability run, the file that says how a stability test '
    'went and the files of its steps, into a StabilityMeasurement entry. Recognizes '
    'which institution wrote it.',
    # Institutions name their run files in their own ways, so every file is offered
    # and each institution's `is_protocol_file` decides.
    mainfile_name_re=r'.*',
)
