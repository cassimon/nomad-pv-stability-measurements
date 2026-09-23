"""The sample a stability test was run on."""

from nomad.datamodel import EntryArchive
from nomad.datamodel.metainfo.basesections.v2 import SystemReference
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.measurement import (
    StabilityMeasurement,
)
from nomad_pv_stability_measurements.schema_packages.sample import SolarCellSample


def test_a_sample_holds_what_the_run_files_state_of_the_device(normalized, log):
    area = 0.09 * ureg('cm^2')
    sample = normalized(
        SolarCellSample(
            name='AI14-1A',
            cell_area=area,
            typology='Cell',
            number_of_cells=1,
        )
    )

    assert sample.cell_area.to('cm^2') == area
    assert log.errors == [] and log.warnings == []


def test_a_run_refers_to_the_sample_it_was_run_on():
    sample = SolarCellSample(name='AI14-1A')
    run = StabilityMeasurement(
        samples=[SystemReference(name='AI14-1A', reference=sample)]
    )

    assert run.samples[0].reference.name == 'AI14-1A'


def test_a_sample_is_an_entry_of_its_own():
    archive = EntryArchive(data=SolarCellSample(name='AI14-1A'))

    assert EntryArchive.m_from_dict(archive.m_to_dict()).data.name == 'AI14-1A'
