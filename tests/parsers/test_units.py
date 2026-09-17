"""How authored text is read as a quantity (Design.md §6, §15.7, §15.16, §17.4)."""

import pint
import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.units import (
    parse,
    parse_difference,
    volume_ratio_of_relative_humidity,
)

SECOND = ureg.second
IRRADIANCE = ureg.watt / ureg.meter**2


@pytest.mark.parametrize(
    ('text', 'expected', 'value'),
    [
        # The traps pint falls into unaided: `h` is Planck's constant, `min` is
        # milli-inch, `d` is undefined.
        ('500 h', SECOND, 1800000),
        ('5 min', SECOND, 300),
        ('2 d', SECOND, 172800),
        ('100 ms', SECOND, 0.1),
        ('2 K/min', ureg.kelvin / SECOND, 2 / 60),
        ('1 sun', IRRADIANCE, 1000),
        ('100 mW/cm^2', IRRADIANCE, 1000),
        ('−40 °C', ureg.kelvin, 233.15),  # a true minus, as pasted from a document
    ],
)
def test_text_is_read_into_the_declared_unit(text, expected, value):
    assert parse(text, expected).magnitude == pytest.approx(value)


@pytest.mark.parametrize(
    ('text', 'fraction'),
    [('500 ppm', 5e-4), ('100 ppb', 1e-7), ('21 vol%', 0.21), ('5 mol%', 0.05)],
)
def test_every_spelling_of_a_volume_ratio_is_one_fraction(text, fraction):
    assert parse(text, ureg.dimensionless).magnitude == pytest.approx(fraction)


@pytest.mark.parametrize(
    ('text', 'expected', 'error', 'match'),
    [
        # A number without a unit is never a guess (D6).
        ('60', SECOND, ValueError, 'bare number'),
        ('10 Hz', SECOND, pint.errors.DimensionalityError, 'Cannot convert'),
        ('85 %RH', ureg.dimensionless, ValueError, 'not a volume ratio'),
        ('10 wt%', ureg.dimensionless, ValueError, 'mass ratio'),
    ],
)
def test_what_cannot_be_read_as_meant_is_refused(text, expected, error, match):
    with pytest.raises(error, match=match):
        parse(text, expected)


@pytest.mark.parametrize(
    ('relative', 'celsius', 'ratio'), [(0.85, 65, 0.2109), (0.85, 25, 0.0265)]
)
def test_a_relative_humidity_is_a_volume_ratio_only_at_its_temperature(
    relative, celsius, ratio
):
    read = volume_ratio_of_relative_humidity(relative, celsius + 273.15)

    assert read == pytest.approx(ratio, rel=1e-3)


def test_a_difference_is_in_kelvin_never_in_an_offset_unit():
    assert parse_difference('4 K', ureg.kelvin).magnitude == pytest.approx(4)
    with pytest.raises(ValueError, match='write the difference in kelvin'):
        parse_difference('4 °C', ureg.kelvin)
