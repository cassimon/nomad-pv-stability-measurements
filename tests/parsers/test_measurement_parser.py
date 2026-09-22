"""How a stability run is recognized, and which protocol entry it refers to."""

import pytest
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.utils import generate_entry_id

from nomad_pv_stability_measurements.parsers import measurement_parser_entry_point
from nomad_pv_stability_measurements.parsers.measurement_parser import (
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


def test_outside_an_upload_a_run_refers_to_no_protocol():
    assert protocol_reference({'protocol': 'x.stability.yaml'}, EntryArchive()) is None
