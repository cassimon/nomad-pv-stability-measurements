from collections.abc import Iterable
from pathlib import Path
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

from nomad_pv_stability_measurements.parsers.options import expand
from nomad_pv_stability_measurements.parsers.translate import translate
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol

SUFFIX = '.stability.yaml'


def read(mainfile: str):
    with open(mainfile, encoding='utf-8') as file:
        return yaml.safe_load(file)


def stem(mainfile: str) -> str:
    """`ISOS-L-2.stability.yaml` as `ISOS-L-2`."""
    name = Path(mainfile).name
    return name[: -len(SUFFIX)] if name.endswith(SUFFIX) else name.split('.')[0]


class StabilityYamlParser(MatchingParser):
    """An authored `.stability.yaml`, translated into the bare archive (Design.md §13).

    Only glue: the translator reads the file, the schema loads what it produced, and
    NOMAD's own normalize pass checks the meaning afterwards. A file with `options` is
    one entry per variant, each a child of the file's own entry, which keeps no protocol
    of its own (§24).
    """

    creates_children = True

    def is_mainfile(
        self,
        filename: str,
        mime: str,
        buffer: bytes,
        decoded_buffer: str,
        compression: str | None = None,
    ) -> bool | Iterable[str]:
        matched = super().is_mainfile(
            filename, mime, buffer, decoded_buffer, compression
        )
        if not matched:
            return matched
        try:
            document = read(filename)
        except (OSError, yaml.YAMLError):
            return matched  # parsing reports it
        expansion = expand(document)
        if not expansion.has_options:
            return matched
        return {variant.key(stem(filename)) for variant in expansion.variants}

    def parse(
        self,
        mainfile: str,
        archive: 'EntryArchive',
        logger: 'BoundLogger',
        child_archives: dict[str, 'EntryArchive'] = None,
    ) -> None:
        document = read(mainfile)
        expansion = expand(document)
        for problem in expansion.problems:
            logger.error(problem.message, path=problem.path)
        if not expansion.has_options:
            load_protocol(expansion.variants[0].document, archive, logger)
            return
        for variant in expansion.variants:
            key = variant.key(stem(mainfile))
            child = (child_archives or {}).get(key)
            if child is None:
                logger.error('no entry was made for this variant.', variant=key)
                continue
            child.metadata.entry_name = key
            load_protocol(variant.document, child, logger.bind(variant=key))


def load_protocol(document, archive: 'EntryArchive', logger: 'BoundLogger') -> None:
    """Fills `archive` with the protocol of `document`, what a `*.stability.yaml` file
    holds without options, and logs what cannot be read."""
    translation = translate(document)
    for problem in translation.problems:
        logger.error(problem.message, path=problem.path)
    if 'data' in translation.archive:
        archive.data = StabilityProtocol.m_from_dict(translation.archive['data'])
