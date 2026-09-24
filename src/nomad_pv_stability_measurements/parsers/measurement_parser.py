"""A stability run: the file that says how a stability test went, and its step files.

Institutions write their runs in formats of their own. Each has a module
`file_reading_<INSTITUTION>.py` with the interface of `file_reading_TEMPLATE.py`. The
parser asks each module in `INSTITUTIONS` whether a file is its run file, and reads the
run with the functions of the first that says yes.

A run's `plan` is the protocol it was given: the protocol file its run file names, in
the same upload, or the test the run file describes itself. Then the file makes two
entries: the run, and a child entry keyed `PROTOCOL_KEY` for the protocol it describes.
Where a run was given none, the institution may work one out from the run's files; it
becomes a child entry keyed `DERIVED_PROTOCOL_KEY`, which the run refers to as its
`derived_plan`, never as its `plan`.

A device's whole history is its **collection**: all its runs, and the measurements
taken outside any run. It follows no protocol; its runs follow their own. The one file
that stands for it, as the institution's `read_collection` says, also makes the
collection (`COLLECTION_KEY`) and the device's sample (`SAMPLE_KEY`). Where that file
is no run file, the collection is its own entry.
Entry ids follow from the file and the key, so every entry can refer to another before
it is processed.

To read a new institution's runs: write its module from the template and add it to
`INSTITUTIONS`. The parser is offered every file of an upload, so each module's
`is_protocol_file` and `read_collection` should look at the name before the content.
"""

import os
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from nomad.parsing.parser import MatchingParser
from nomad.utils import generate_entry_id

from nomad_pv_stability_measurements.file_reading import (
    file_reading_SIM,
    file_reading_UNITOV,
)
from nomad_pv_stability_measurements.parsers.parser import load_protocol, stem
from nomad_pv_stability_measurements.schema_packages.measurement import (
    StabilityMeasurement,
)
from nomad_pv_stability_measurements.schema_packages.sample import SolarCellSample

if TYPE_CHECKING:
    from nomad.datamodel.datamodel import EntryArchive
    from structlog.stdlib import BoundLogger

#: The file reading module of every institution whose runs are read, asked in order.
INSTITUTIONS: tuple[ModuleType, ...] = (file_reading_SIM, file_reading_UNITOV)
#: The key of the child entry for a protocol a run file describes itself.
PROTOCOL_KEY = 'protocol'
#: The key of the child entry for a protocol worked out from a run's files.
DERIVED_PROTOCOL_KEY = 'derived protocol'
#: The keys of the child entries of the file that stands for a device's collection.
COLLECTION_KEY = 'collection'
SAMPLE_KEY = 'sample'


def institution_of(path: str | Path, content: str) -> ModuleType | None:
    """The file reading module of the institution whose run file this is, if any."""
    for module in INSTITUTIONS:
        if module.is_protocol_file(path, content):
            return module
    return None


def collection_of(path: str | Path) -> tuple[ModuleType | None, dict | None]:
    """The institution and the collection of the file at `path`, if it stands for
    one. A reader that fails counts as no collection here; reading the file reports
    it."""
    for module in INSTITUTIONS:
        try:
            collection = module.read_collection(path)
        except Exception:  # an institution's reader may raise anything
            continue
        if collection is not None:
            return module, collection
    return None, None


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


def child_reference(archive: 'EntryArchive', key: str) -> str | None:
    """The child entry keyed `key` of the file whose entry `archive` is. `None`
    outside an upload."""
    metadata = archive.metadata
    if metadata is None or metadata.upload_id is None:
        return None
    entry_id = generate_entry_id(metadata.upload_id, metadata.mainfile, key)
    return f'../upload/archive/{entry_id}#/data'


def entry_reference(
    archive: 'EntryArchive', mainfile: str | Path, path: str | Path, key: str | None
) -> str | None:
    """The entry the file at `path` makes under `key`, in the upload of `archive`,
    whose own file is at `mainfile`. `None` outside an upload."""
    metadata = archive.metadata
    if metadata is None or metadata.upload_id is None or metadata.mainfile is None:
        return None
    mainfile = str(mainfile)
    if not mainfile.endswith(metadata.mainfile):
        return None
    root = mainfile[: -len(metadata.mainfile)] or '.'
    relative = Path(os.path.relpath(path, root)).as_posix()
    entry_id = generate_entry_id(metadata.upload_id, relative, key)
    return f'../upload/archive/{entry_id}#/data'


class StabilityMeasurementParser(MatchingParser):
    """A stability run of any institution in `INSTITUTIONS`, read into a
    `StabilityMeasurement` whose `plan` is the protocol it was given, or whose
    `derived_plan` is one worked out from its files, and a device's collection, where
    the file stands for one."""

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
        _, collection = collection_of(filename)
        keys = []
        if collection is not None:
            keys.append(SAMPLE_KEY)
        if institution is None:
            return keys or False
        if collection is not None:
            keys.append(COLLECTION_KEY)
        for key, read in (
            (PROTOCOL_KEY, institution.read_embedded_protocol),
            (DERIVED_PROTOCOL_KEY, institution.derive_protocol),
        ):
            try:
                if read(filename) is not None:
                    keys.append(key)
            except Exception:  # parsing the file reports it
                pass
        return sorted(keys) or True

    def parse(
        self,
        mainfile: str,
        archive: 'EntryArchive',
        logger: 'BoundLogger',
        child_archives: dict[str, 'EntryArchive'] = None,
    ) -> None:
        children = child_archives or {}
        content = Path(mainfile).read_text(encoding='utf-8', errors='replace')
        institution = institution_of(mainfile, content)
        if institution is not None:
            archive.data = self.run(institution, mainfile, archive, children, logger)
            collection_archive = children.get(COLLECTION_KEY)
        else:
            collection_archive = archive
        found = collection_of(mainfile)
        if found[1] is None:
            if institution is None:
                logger.error('no institution recognizes this file as its run file.')
            return
        if collection_archive is None:
            logger.error('no entry was made for the collection this file stands for.')
            return
        collection_archive.data = self.collection(
            found, mainfile, archive, children, logger
        )

    def run(
        self,
        institution: ModuleType,
        mainfile: str,
        archive: 'EntryArchive',
        children: dict[str, 'EntryArchive'],
        logger: 'BoundLogger',
    ) -> StabilityMeasurement:
        """The run the file at `mainfile` stands for."""
        measurement = StabilityMeasurement()
        problems = measurement.read_files(
            mainfile,
            read_protocol=_referring(institution.read_protocol, archive, mainfile),
            read_stability_series=institution.read_stability_series,
            read_jv_file=institution.read_jv_file,
        )
        for problem in problems:
            logger.error(problem, institution=institution.INSTITUTION)
        embedded = _protocol(institution, 'read_embedded_protocol', mainfile, logger)
        if embedded is None:
            measurement.plan = protocol_reference(
                institution.read_protocol(mainfile)['run'], archive
            )
        else:
            _load_protocol(embedded, children, PROTOCOL_KEY, logger)
            measurement.plan = child_reference(archive, PROTOCOL_KEY)
        derived = _protocol(institution, 'derive_protocol', mainfile, logger)
        if derived is not None:
            _load_protocol(derived, children, DERIVED_PROTOCOL_KEY, logger)
            measurement.derived_plan = child_reference(archive, DERIVED_PROTOCOL_KEY)
        return measurement

    def collection(
        self,
        found: tuple[ModuleType, dict],
        mainfile: str,
        archive: 'EntryArchive',
        children: dict[str, 'EntryArchive'],
        logger: 'BoundLogger',
    ) -> StabilityMeasurement:
        """The collection the file at `mainfile` stands for: its own steps, its runs
        as `sub_activities`, and one figure of all their steps; with its sample as a
        child entry. `found` is the institution and the collection, as
        `collection_of` finds them."""
        institution, collection = found
        sample = dict(collection.get('sample') or {})
        _load_sample(sample, children.get(SAMPLE_KEY), logger)
        measurement = StabilityMeasurement()
        reference = {'name', 'lab_id'}
        run = {
            'name': collection.get('name'),
            'samples': [
                {key: sample[key] for key in reference & set(sample)}
                | {'file': mainfile}
            ],
        }
        problems = measurement.read_files(
            mainfile,
            read_protocol=_referring(
                lambda _: {'run': run, 'steps': collection.get('steps', [])},
                archive,
                mainfile,
            ),
            read_stability_series=institution.read_stability_series,
            read_jv_file=institution.read_jv_file,
        )
        for problem in problems:
            logger.error(problem, institution=institution.INSTITUTION)
        runs = collection.get('runs', [])
        references = [entry_reference(archive, mainfile, each, None) for each in runs]
        if all(references):
            measurement.sub_activities = references
        steps = list(measurement.steps)
        for path in runs:
            steps += _steps_of_run(institution, path)
        placed = [step for step in steps if step.start_time is not None]
        if placed:
            measurement.datetime = min(step.start_time for step in placed)
        measurement.figures = measurement.figures_for_plotting(logger, steps)
        return measurement


def _referring(read_protocol, archive: 'EntryArchive', mainfile: str):
    """`read_protocol`, with each sample that names the `file` whose entry holds it
    referring to that entry instead."""

    def read(path):
        protocol = read_protocol(path)
        run = dict(protocol.get('run') or {})
        samples = []
        for each in run.get('samples', []):
            sample = dict(each)
            if 'file' in sample:
                reference = entry_reference(
                    archive, mainfile, sample.pop('file'), SAMPLE_KEY
                )
                if reference is not None:
                    sample['reference'] = reference
            samples.append(sample)
        if samples:
            run['samples'] = samples
        return {**protocol, 'run': run}

    return read


def _steps_of_run(institution: ModuleType, path: str) -> list:
    """The steps of the run at `path`, each named after the run too, for the figure
    of a collection. What cannot be read is reported by the run's own entry."""
    run = StabilityMeasurement()
    try:
        run.read_files(
            path,
            read_protocol=institution.read_protocol,
            read_stability_series=institution.read_stability_series,
            read_jv_file=institution.read_jv_file,
        )
    except Exception:  # the run's own entry reports it
        return []
    for step in run.steps:
        step.name = f'{run.name} · {step.name}'
    return list(run.steps)


def _protocol(
    institution: ModuleType, reader: str, mainfile: str, logger: 'BoundLogger'
) -> dict | None:
    """The protocol the institution's `reader`, `read_embedded_protocol` or
    `derive_protocol`, finds for the run file at `mainfile`; `None` where it fails,
    reported."""
    try:
        return getattr(institution, reader)(mainfile)
    except Exception as error:  # an institution's reader may raise anything
        logger.error(
            f'the protocol of the run cannot be read by `{reader}`: {error}',
            institution=institution.INSTITUTION,
        )
        return None


def _load_protocol(
    document: dict,
    children: dict[str, 'EntryArchive'],
    key: str,
    logger: 'BoundLogger',
) -> None:
    child = children.get(key)
    if child is None:
        logger.error(f'no entry was made for the {key} of the run.')
        return
    child.metadata.entry_name = (document.get('data') or {}).get('name')
    load_protocol(document, child, logger.bind(entry=key))


def _load_sample(
    sample: dict, child: 'EntryArchive | None', logger: 'BoundLogger'
) -> None:
    if child is None:
        logger.error('no entry was made for the sample of the collection.')
        return
    known = SolarCellSample.m_def.all_quantities
    for key in sorted(set(sample) - set(known)):
        logger.error(f'the sample has a `{key}`, which a sample has no place for.')
    child.data = SolarCellSample(**{key: sample[key] for key in known if key in sample})
    child.metadata.entry_name = sample.get('name')
