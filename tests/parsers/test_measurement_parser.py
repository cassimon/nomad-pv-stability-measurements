"""How a stability run is recognized, and which protocol entry it refers to."""

import re

import pytest
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.utils import generate_entry_id

from nomad_pv_stability_measurements.parsers import measurement_parser_entry_point
from nomad_pv_stability_measurements.parsers.measurement_parser import (
    PROTOCOL_KEY,
    embedded_protocol_reference,
    protocol_reference,
)

PARSER = measurement_parser_entry_point.load()


@pytest.mark.parametrize(
    ('name', 'content', 'recognized'),
    [
        ('ISOS-L-2.run.yaml', 'run:\n  institution: SIM\n', True),
        # An institution the parser does not know yet.
        ('ISOS-L-2.run.yaml', 'run:\n  institution: HZB\n', False),
        ('ISOS-L-2.stability.yaml', 'run:\n  institution: SIM\n', False),
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

    assert embedded_protocol_reference(archive) == f'../upload/archive/{entry_id}#/data'


def test_outside_an_upload_a_run_refers_to_no_protocol():
    assert protocol_reference({'protocol': 'x.stability.yaml'}, EntryArchive()) is None
