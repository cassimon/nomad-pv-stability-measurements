"""Where light comes from: the sun or a lamp, and what each has to say about itself."""

from datetime import datetime, timezone

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.characterization_instructions import (
    JVScan,
)
from nomad_pv_stability_measurements.schema_packages.general import Period
from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.light_sources import (
    LED,
    ArtificialLightSource,
    GeoLocation,
    MetalHalideLamp,
    NaturalLightSource,
    SulfurPlasmaLamp,
    XenonLamp,
)

W_PER_M2 = ureg('W/m^2')
DAY = datetime(2026, 6, 21, tzinfo=timezone.utc)


def test_coordinates_the_wrong_way_round_are_reported(normalized, log):
    normalized(
        GeoLocation(latitude=-104.99 * ureg.degree, longitude=39.74 * ureg.degree)
    )

    [error] = log.errors
    assert 'wrong way round' in error


@pytest.mark.parametrize(
    ('fields', 'reported'),
    [
        ({'tilt': 200 * ureg.degree}, '`tilt`'),
        ({'azimuth': -10 * ureg.degree}, '`azimuth`'),
        (
            {'exposure_start': DAY, 'exposure_end': DAY.replace(month=5)},
            'before `exposure_start`',
        ),
    ],
)
def test_the_sun_s_geometry_is_checked(normalized, log, fields, reported):
    normalized(NaturalLightSource(**fields))

    [error] = log.errors
    assert reported in error


@pytest.mark.parametrize(
    ('cls', 'filters'),
    [
        (XenonLamp, True),
        (MetalHalideLamp, True),
        (SulfurPlasmaLamp, False),
        (LED, False),
    ],
)
def test_only_a_lamp_whose_light_holds_uv_takes_a_uv_filter(cls, filters):
    # "Metal halide and xenon arc lamps have UV light in their spectra, so any
    # filtering used must be reported" (Khenkin et al. 2020, p.43).
    assert ('uv_filter' in cls.m_def.all_quantities) is filters


@pytest.mark.parametrize(
    ('source', 'said'),
    [
        (NaturalLightSource(), 'sunlight'),
        (ArtificialLightSource(), 'artificial light'),
        (ArtificialLightSource(solar_simulator=True), 'solar simulator'),
        (MetalHalideLamp(), 'metal halide lamp'),
        (LED(), 'LED'),
        (
            LED(solar_simulator=True, simulator_classification='AAA'),
            'LED solar simulator AAA',
        ),
        (
            XenonLamp(solar_simulator=True, simulator_classification='AAA'),
            'xenon lamp solar simulator AAA',
        ),
    ],
)
def test_a_source_says_what_it_is(source, said):
    assert source.describe() == said


def test_a_simulator_class_without_a_solar_simulator_is_questioned(normalized, log):
    normalized(XenonLamp(simulator_classification='AAA'))

    [warning] = log.warnings
    assert 'is the source a solar simulator?' in warning


def test_an_irradiance_names_its_source(normalized):
    lamp = HoldBetweenIrradiance(
        lower_bound=800 * W_PER_M2,
        upper_bound=1000 * W_PER_M2,
        control=True,
        light_source=ArtificialLightSource(solar_simulator=True),
    )

    assert normalized(lamp).label == (
        'Hold irradiance between 800 W/m² and 1000 W/m² (solar simulator)'
    )


@pytest.mark.parametrize(
    ('monitor', 'role', 'written'),
    [(True, 'monitored', 'sunlight, monitored'), (None, 'specified', 'sunlight')],
)
def test_naming_the_source_states_something_about_the_light(monitor, role, written):
    sun = HoldIrradiance(monitor=monitor, light_source=NaturalLightSource())

    assert (sun.role_for_plotting(), sun.annotation_for_plotting()) == (role, written)


def test_a_j_v_scan_names_the_light_it_is_measured_under():
    scans = JVScan(
        interval=Period(kind='fixed', value=10 * ureg.minute),
        irradiance=1000 * W_PER_M2,
        light_source=XenonLamp(solar_simulator=True, simulator_classification='AAA'),
    )

    assert scans.describe() == 'J–V scan every 10 min (xenon lamp solar simulator AAA)'
