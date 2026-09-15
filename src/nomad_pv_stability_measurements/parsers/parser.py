from typing import (
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from nomad.datamodel.datamodel import (
        EntryArchive,
    )
    from structlog.stdlib import (
        BoundLogger,
    )

import yaml
from nomad.parsing.parser import MatchingParser

from nomad_pv_stability_measurements.parsers.translate import translate
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol


class StabilityYamlParser(MatchingParser):
    """An authored `.stability.yaml`, translated into the bare archive (Design.md §13).

    Only glue: the translator reads the file, the schema loads what it produced, and
    NOMAD's own normalize pass checks the meaning afterwards.
    """

    def parse(
        self,
        mainfile: str,
        archive: 'EntryArchive',
        logger: 'BoundLogger',
        child_archives: dict[str, 'EntryArchive'] = None,
    ) -> None:
        with open(mainfile, encoding='utf-8') as file:
            translation = translate(yaml.safe_load(file))
        for problem in translation.problems:
            logger.error(problem.message, path=problem.path)
        if 'data' in translation.archive:
            archive.data = StabilityProtocol.m_from_dict(translation.archive['data'])
