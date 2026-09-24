"""How a stability run is recognized, and which protocol entry it refers to."""

import re
import shutil
from pathlib import Path

import pytest
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.utils import generate_entry_id

import nomad_pv_stability_measurements
from nomad_pv_stability_measurements.parsers import measurement_parser_entry_point
from nomad_pv_stability_measurements.parsers.measurement_parser import (
    COLLECTION_KEY,
    DERIVED_PROTOCOL_KEY,
    PROTOCOL_KEY,
    SAMPLE_KEY,
    child_reference,
    protocol_reference,
)

PARSER = measurement_parser_entry_point.load()
DEVICE = (
    Path(nomad_pv_stability_measurements.__file__).parent
    / 'example_uploads/institutes/UNITOV/example_batch/AI14/AI14_1A'
)


def matched(path: Path):
    content = path.read_bytes()
    return PARSER.is_mainfile(
        str(path), 'text/plain', content, content.decode('latin-1')
    )


@pytest.mark.parametrize(
    ('name', 'content', 'recognized'),
    [
        ('ISOS-L-2.run.yaml', 'run:\n  institution: SIM\n', True),
        # An institution the parser does not know yet.
        ('ISOS-L-2.run.yaml', 'run:\n  institution: HZB\n', False),
        ('ISOS-L-2.stability.yaml', 'run:\n  institution: SIM\n', False),
        (
            'AI14/0000_2025-11-20_17.23.47_Stability (Tracking)_AI14-1A.txt',
            '## Header ##\r\nTest\tStability (Tracking)\r\n',
            True,
        ),
    ],
)
def test_the_parser_takes_the_run_files_of_institutions_it_knows(
    name, content, recognized
):
    matched = PARSER.is_mainfile(name, 'text/plain', content.encode(), content)

    assert bool(matched) is recognized


def test_every_file_is_offered_and_the_institutions_decide():
    # Institutions name their run files in their own ways.
    name_re = re.compile(measurement_parser_entry_point.mainfile_name_re)

    assert name_re.fullmatch('A/0000_2025-11-20_Stability (Tracking)_A-1.txt')


@pytest.mark.parametrize(
    ('run', 'key'),
    [
        (
            {
                'protocol': 'isos/ISOS-L-2.stability.yaml',
                'variant': 'ISOS-L-2 (65 °C, MPP)',
            },
            'ISOS-L-2 (65 °C, MPP)',
        ),
        # A file without options is a single entry, with no key.
        ({'protocol': 'isos/ISOS-D-1.stability.yaml', 'variant': 'ISOS-D-1'}, None),
    ],
)
def test_a_run_refers_to_the_protocol_entry_it_followed(run, key):
    archive = EntryArchive(metadata=EntryMetadata(upload_id='upload'))
    entry_id = generate_entry_id('upload', run['protocol'], key)

    assert protocol_reference(run, archive) == f'../upload/archive/{entry_id}#/data'


def test_a_run_file_describing_its_test_also_makes_the_protocol_entry(tmp_path):
    path = tmp_path / 'x.run.yaml'
    content = (
        'run:\n  institution: SIM\n'
        'test conditions:\n'
        '  name: Damp heat\n'
        '  phases: [{name: soak, duration: 1000 h, temperature: 85 °C}]\n'
    )
    path.write_text(content, encoding='utf-8')

    matched = PARSER.is_mainfile(str(path), 'text/plain', content.encode(), content)

    assert list(matched) == [PROTOCOL_KEY]


def test_a_run_describing_its_test_refers_to_the_protocol_entry_of_its_own_file():
    archive = EntryArchive(
        metadata=EntryMetadata(upload_id='upload', mainfile='a/x.run.yaml')
    )
    entry_id = generate_entry_id('upload', 'a/x.run.yaml', PROTOCOL_KEY)

    assert (
        child_reference(archive, PROTOCOL_KEY) == f'../upload/archive/{entry_id}#/data'
    )


def test_outside_an_upload_a_run_refers_to_no_protocol():
    assert protocol_reference({'protocol': 'x.stability.yaml'}, EntryArchive()) is None


@pytest.mark.parametrize(
    ('run', 'keys'),
    [
        # The device's first run stands for its collection too.
        ('21.28.49', [COLLECTION_KEY, DERIVED_PROTOCOL_KEY, SAMPLE_KEY]),
        ('17.23.47', [DERIVED_PROTOCOL_KEY]),
    ],
)
def test_the_first_run_of_a_device_also_makes_its_collection_and_sample(run, keys):
    [tracking] = (DEVICE / run).glob('*(Tracking)*')

    assert list(matched(tracking)) == keys


def test_a_device_without_runs_is_its_collection_with_its_sample_and_no_plan(
    tmp_path, log
):
    [jv] = (DEVICE / '17.23.47').glob('0001_*(JV)*')
    scan = tmp_path / 'AI14' / 'AI14_1A' / '09.00.00' / jv.name
    scan.parent.mkdir(parents=True)
    shutil.copy(jv, scan)
    mainfile = scan.relative_to(tmp_path).as_posix()
    keys = matched(scan)
    archive = EntryArchive(metadata=EntryMetadata(upload_id='u', mainfile=mainfile))
    children = {
        key: EntryArchive(metadata=EntryMetadata(upload_id='u', mainfile=mainfile))
        for key in keys
    }

    PARSER.parse(str(scan), archive, log, children)

    assert list(keys) == [SAMPLE_KEY]
    assert log.errors == []
    collection = archive.data
    assert [step.name for step in collection.steps] == ['J–V 1, 09.00.00']
    # A device's history follows no protocol, and none is made up for it.
    assert collection.plan is None and collection.derived_plan is None
    assert children[SAMPLE_KEY].data.name == 'AI14-1A'


def test_a_run_given_no_protocol_refers_to_the_one_derived_as_its_derived_plan(log):
    [tracking] = (DEVICE / '17.23.47').glob('*(Tracking)*')
    mainfile = tracking.relative_to(DEVICE.parent).as_posix()
    keys = matched(tracking)
    archive = EntryArchive(metadata=EntryMetadata(upload_id='u', mainfile=mainfile))
    children = {
        key: EntryArchive(metadata=EntryMetadata(upload_id='u', mainfile=mainfile))
        for key in keys
    }

    PARSER.parse(str(tracking), archive, log, children)

    assert log.errors == []
    run = archive.data
    derived = generate_entry_id('u', mainfile, DERIVED_PROTOCOL_KEY)
    # Worked out from the files, so never taken for the protocol the run was given.
    assert run.plan is None
    assert run.derived_plan.m_proxy_value == f'../upload/archive/{derived}#/data'
    assert children[DERIVED_PROTOCOL_KEY].data.instructions
