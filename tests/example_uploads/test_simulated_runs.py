"""Every simulated run in the example uploads loads through NOMAD, and follows a
protocol entry that is in the same upload: a protocol file's, or one its own run file
describes."""

from pathlib import Path

import pytest
import yaml
from nomad.client import normalize_all, parse

from nomad_pv_stability_measurements.example_uploads import (
    custom_protocols_example_upload_entry_point,
    protocols_in_run_files_example_upload_entry_point,
    simulated_runs_example_upload_entry_point,
)
from nomad_pv_stability_measurements.parsers import parser_entry_point
from nomad_pv_stability_measurements.parsers.parser import stem
from nomad_pv_stability_measurements.schema_packages.characterization_instructions import (
    JVScan,
)
from nomad_pv_stability_measurements.schema_packages.general import (
    CountingRepeatingBlock,
    TimedRepeatingBlock,
)
from nomad_pv_stability_measurements.schema_packages.measurement import (
    StabilityMeasurement,
    StabilitySeriesStep,
)
from nomad_pv_stability_measurements.schema_packages.protocol import (
    StabilityProtocol,
)

#: Each upload, and how many runs it holds: one per protocol file.
UPLOADS = [
    (simulated_runs_example_upload_entry_point, 20),
    (custom_protocols_example_upload_entry_point, 3),
    (protocols_in_run_files_example_upload_entry_point, 2),
]
PROTOCOL_PARSER = parser_entry_point.load()


def built(entry_point, path: Path) -> Path:
    """The upload's files, as NOMAD copies them from the package."""
    entry_point.model_copy(
        update={'plugin_package': 'nomad_pv_stability_measurements'}
    ).load(str(path))
    return path


def protocol_entries(path: Path) -> set[str | None]:
    """The entry keys the protocol parser makes of the file at `path`: `None` for a
    file without options, whose protocol is the file's own entry."""
    content = path.read_text(encoding='utf-8')
    matched = PROTOCOL_PARSER.is_mainfile(
        str(path), 'text/plain', content.encode(), content
    )
    return {None} if matched is True else set(matched)


@pytest.mark.parametrize(('entry_point', 'runs'), UPLOADS)
def test_every_run_loads_and_follows_a_protocol_in_its_upload(
    entry_point, runs, tmp_path, log
):
    upload = built(entry_point, tmp_path)
    run_files = sorted(upload.glob('*/*.run.yaml'))

    assert len(run_files) == runs
    for run_file in run_files:
        archive, *described = parse(str(run_file), logger=log)
        for each in (archive, *described):
            normalize_all(each, logger=log)
        run = yaml.safe_load(run_file.read_text(encoding='utf-8'))['run']

        assert isinstance(archive.data, StabilityMeasurement), run_file.name
        assert any(isinstance(s, StabilitySeriesStep) for s in archive.data.steps)
        if 'protocol' in run:
            variant = run['variant']
            key = None if variant == stem(run['protocol']) else variant
            assert key in protocol_entries(upload / run['protocol']), run_file.name
        else:
            [protocol] = described
            assert isinstance(protocol.data, StabilityProtocol), run_file.name
    assert log.errors == []


def test_a_protocol_in_phases_is_recorded_one_series_per_phase(tmp_path):
    upload = built(custom_protocols_example_upload_entry_point, tmp_path)

    [archive] = parse(str(upload / 'stepped-stress' / 'stepped-stress.run.yaml'))
    series = [s for s in archive.data.steps if isinstance(s, StabilitySeriesStep)]

    assert [step.name for step in series] == [
        'burn-in',
        'temperature cycles under light',
        'recovery in the dark',
    ]


def test_the_custom_protocols_load_repeat_and_measure_between_phases(tmp_path, log):
    upload = built(custom_protocols_example_upload_entry_point, tmp_path)
    blocks = set()

    for path in sorted(upload.glob('*.stability.yaml')):
        [archive] = parse(str(path), logger=log)
        normalize_all(archive, logger=log)
        assert isinstance(archive.data, StabilityProtocol), path.name
        blocks |= {type(each) for each in archive.data.m_all_contents()}

    assert log.errors == []
    assert {CountingRepeatingBlock, TimedRepeatingBlock, JVScan} <= blocks
