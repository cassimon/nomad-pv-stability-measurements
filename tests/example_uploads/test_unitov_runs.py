"""The runs measured at UNITOV load through NOMAD as an upload: each run with the
protocol derived from its files, and each cell as a sample and a collection of its
history, every reference pointing to an entry of the same upload."""

from collections import Counter
from pathlib import Path

from nomad.client import normalize_all
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.parsing.parsers import match_parser
from nomad.utils import generate_entry_id

from nomad_pv_stability_measurements.example_uploads import (
    unitov_runs_example_upload_entry_point,
)
from nomad_pv_stability_measurements.schema_packages.measurement import (
    StabilityMeasurement,
)

UPLOAD_ID = 'unitov'
#: The runs of the upload, and the cells they were run on.
RUNS, CELLS = 17, 6


def built(path: Path) -> Path:
    """The upload's files, as NOMAD copies them from the package."""
    unitov_runs_example_upload_entry_point.model_copy(
        update={'plugin_package': 'nomad_pv_stability_measurements'}
    ).load(str(path))
    return path


def processed(upload: Path, log) -> dict[str, EntryArchive]:
    """Every entry of the upload by its id, each file matched, parsed and normalized
    as NOMAD does it."""
    entries = {}
    for path in sorted(each for each in upload.rglob('*') if each.is_file()):
        parser, keys = match_parser(str(path))
        if parser is None:
            continue
        mainfile = path.relative_to(upload).as_posix()

        def made(key=None):
            return EntryArchive(
                metadata=EntryMetadata(
                    upload_id=UPLOAD_ID,
                    mainfile=mainfile,
                    mainfile_key=key,
                    entry_id=generate_entry_id(UPLOAD_ID, mainfile, key),
                )
            )

        archive, children = made(), {key: made(key) for key in keys or []}
        parser.parse(str(path), archive, log, children)
        for each in (archive, *children.values()):
            normalize_all(each, logger=log)
            entries[each.metadata.entry_id] = each
    return entries


def referred(data) -> list[str]:
    """The entries `data` refers to: its plans, its samples and its parts."""
    plans = (getattr(data, name, None) for name in ('plan', 'derived_plan'))
    references = [each for each in plans if each is not None]
    references += [each.reference for each in getattr(data, 'samples', None) or []]
    references += list(getattr(data, 'sub_activities', None) or [])
    return [
        each.m_proxy_value.split('/archive/')[1].split('#')[0] for each in references
    ]


def test_every_run_and_cell_loads_and_refers_only_into_its_upload(tmp_path, log):
    entries = processed(built(tmp_path), log)

    kinds = Counter(type(each.data).__name__ for each in entries.values())
    measurements = [
        each.data
        for each in entries.values()
        if isinstance(each.data, StabilityMeasurement)
    ]
    collections = [each for each in measurements if each.sub_activities]
    assert log.errors == []
    # Each run with the protocol derived for it, and each cell's collection.
    assert kinds == {
        'StabilityMeasurement': RUNS + CELLS,
        'StabilityProtocol': RUNS,
        'SolarCellSample': CELLS,
    }
    assert sum(len(each.sub_activities) for each in collections) == RUNS
    runs = [each for each in measurements if not each.sub_activities]
    # No UNITOV file names a protocol, so none is given; a collection has none at all.
    assert all(each.plan is None and each.samples for each in measurements)
    assert all(each.derived_plan is not None for each in runs)
    assert all(each.derived_plan is None for each in collections)
    for each in entries.values():
        assert set(referred(each.data)) <= set(entries), each.metadata.mainfile
