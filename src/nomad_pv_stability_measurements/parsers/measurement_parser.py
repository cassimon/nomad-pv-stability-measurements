"""A stability run: the file that says how a stability test went, and its step files.

Institutions write their runs in formats of their own. Each has a module
`file_reading_<INSTITUTION>.py` with the interface of `file_reading_TEMPLATE.py`. The
parser asks each module in `INSTITUTIONS` whether a file is its run file, and reads the
run with the functions of the first that says yes.

A run file names the protocol file the run followed, in the same upload, or describes
the test itself. Then the file makes two entries: the run, and a child entry keyed
`PROTOCOL_KEY` for the protocol it describes, which the run refers to.

To read a new institution's runs: write its module from the template, add it to
`INSTITUTIONS`, and widen the entry point's `mainfile_name_re` if its run files are
named otherwise than `*.run.yaml`.
"""

from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from nomad.parsing.parser import MatchingParser
from nomad.utils import generate_entry_id

from nomad_pv_stability_measurements.file_reading import file_reading_SIM
from nomad_pv_stability_measurements.parsers.parser import load_protocol, stem
from nomad_pv_stability_measurements.schema_packages.measurement import (
    StabilityMeasurement,
)

if TYPE_CHECKING:
    from nomad.datamodel.datamodel import EntryArchive
    from structlog.stdlib import BoundLogger

#: The file reading module of every institution whose runs are read, asked in order.
INSTITUTIONS: tuple[ModuleType, ...] = (file_reading_SIM,)
#: The key of the child entry for a protocol a run file describes itself.
PROTOCOL_KEY = 'protocol'


def institution_of(path: str | Path, content: str) -> ModuleType | None:
    """The file reading module of the institution whose run file this is, if any."""
    for module in INSTITUTIONS:
        if module.is_protocol_file(path, content):
            return module
    return None


def protocol_reference(run: dict, archive: 'EntryArchive') -> str | None:
    """The protocol entry a run followed, in the same upload: the file the run names
    as `protocol`, from the upload's root, and of a file with options, the entry of
    the `variant`. `None` outside an upload, or where the run names no protocol."""
    upload_id = archive.metadata.upload_id if archive.metadata else None
    protocol = run.get('protocol')
    if upload_id is None or protocol is None:
        return None
    # A file without options is one entry, named after the file.
    variant = run.get('variant')
    key = None if variant in (None, stem(protocol)) else variant
    return f'../upload/archive/{generate_entry_id(upload_id, protocol, key)}#/data'


def embedded_protocol_reference(archive: 'EntryArchive') -> str | None:
    """The child entry of the run file itself that holds the protocol it describes.
    `None` outside an upload."""
    metadata = archive.metadata
    if metadata is None or metadata.upload_id is None:
        return None
    entry_id = generate_entry_id(metadata.upload_id, metadata.mainfile, PROTOCOL_KEY)
    return f'../upload/archive/{entry_id}#/data'


class StabilityMeasurementParser(MatchingParser):
    """A stability run of any institution in `INSTITUTIONS`, read into a
    `StabilityMeasurement` whose `plan` is the protocol it followed."""

    creates_children = True

    def is_mainfile(
        self,
        filename: str,
        mime: str,
        buffer: bytes,
        decoded_buffer: str,
        compression: str | None = None,
    ) -> bool | Iterable[str]:
        if not super().is_mainfile(filename, mime, buffer, decoded_buffer, compression):
            return False
        institution = institution_of(filename, decoded_buffer or '')
        if institution is None:
            return False
        try:
            embedded = institution.read_embedded_protocol(filename)
        except Exception:  # parsing the file reports it
            return True
        return True if embedded is None else [PROTOCOL_KEY]

    def parse(
        self,
        mainfile: str,
        archive: 'EntryArchive',
        logger: 'BoundLogger',
        child_archives: dict[str, 'EntryArchive'] = None,
    ) -> None:
        content = Path(mainfile).read_text(encoding='utf-8', errors='replace')
        institution = institution_of(mainfile, content)
        if institution is None:
            logger.error('no institution recognizes this file as its run file.')
            return
        measurement = StabilityMeasurement()
        problems = measurement.read_files(
            mainfile,
            read_protocol=institution.read_protocol,
            read_stability_series=institution.read_stability_series,
            read_jv_file=institution.read_jv_file,
        )
        for problem in problems:
            logger.error(problem, institution=institution.INSTITUTION)
        embedded = _embedded_protocol(institution, mainfile, logger)
        if embedded is None:
            measurement.plan = protocol_reference(
                institution.read_protocol(mainfile)['run'], archive
            )
        else:
            _load_embedded(embedded, (child_archives or {}).get(PROTOCOL_KEY), logger)
            measurement.plan = embedded_protocol_reference(archive)
        archive.data = measurement


def _embedded_protocol(
    institution: ModuleType, mainfile: str, logger: 'BoundLogger'
) -> dict | None:
    try:
        return institution.read_embedded_protocol(mainfile)
    except Exception as error:  # an institution's reader may raise anything
        logger.error(
            f'the protocol the run file describes cannot be read: {error}',
            institution=institution.INSTITUTION,
        )
        return None


def _load_embedded(
    document: dict, child: 'EntryArchive | None', logger: 'BoundLogger'
) -> None:
    if child is None:
        logger.error('no entry was made for the protocol the run file describes.')
        return
    child.metadata.entry_name = (document.get('data') or {}).get('name')
    load_protocol(document, child, logger.bind(entry=PROTOCOL_KEY))
