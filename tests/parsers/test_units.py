import pint
import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.units import (
    parse,
    parse_duration,
    parse_frequency,
    split_match_convert,
)


@pytest.mark.parametrize(
    ('text', 'seconds'),
    [
        ('60 s', 60),
        ('100 ms', 0.1),
        # The traps pint falls into unaided (Design.md §6): `h` is Planck's
        # constant, `min` is milli-inch, `d` is undefined — all three silent.
        ('24 h', 86400),
        ('500 h', 1800000),
        ('5 min', 300),
        ('2 d', 172800),
        # No space, and a written-out unit.
        ('60s', 60),
        ('1000 hours', 3600000),
    ],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text).to(ureg.second).magnitude == pytest.approx(seconds)


def test_parse_frequency():
    assert parse_frequency('10 Hz').to(ureg.hertz).magnitude == pytest.approx(10)
    assert parse_frequency('1 kHz').to(ureg.hertz).magnitude == pytest.approx(1000)


def test_a_bare_number_is_ambiguous():
    # D6: a number with no unit is an error, never a guess.
    with pytest.raises(ValueError, match='bare number'):
        parse_duration('60')


def test_a_wrong_dimension_fails_loudly():
    with pytest.raises(pint.errors.DimensionalityError, match='Cannot convert'):
        parse_duration('10 Hz')


def test_unreadable_text_fails():
    with pytest.raises(ValueError, match='not a number'):
        parse_duration('now and then')


def test_split_handles_human_characters():
    # A true minus and a non-breaking space, as pasted from a document.
    assert split_match_convert('−40 °C') == (-40.0, '°C')


def test_split_leaves_units_that_pint_already_reads():
    # Only an exact `h`/`min`/`d` is aliased, so `ms` is not read as minutes.
    assert split_match_convert('100 ms') == (100.0, 'ms')
    assert split_match_convert('10 Hz') == (10.0, 'Hz')


def test_a_sun_is_an_irradiance():
    # `sun` is undefined in this registry and `ureg.define()` is forbidden, so it rides
    # the same (factor, unit) alias table as the time tokens (§6 step 4).
    irradiance = ureg.watt / ureg.meter**2

    assert parse('1 sun', irradiance).magnitude == pytest.approx(1000)
    assert parse('0.5 sun', irradiance).magnitude == pytest.approx(500)
    # What pint already reads correctly is left alone.
    assert parse('100 mW/cm^2', irradiance).magnitude == pytest.approx(1000)


# Volume ratios (§15.7): one dimensionless axis for every spelling of a ratio.


@pytest.mark.parametrize(
    ('text', 'fraction'),
    [
        # What this registry already reads: `ppm` and `%`, both dimensionless.
        ('500 ppm', 5e-4),
        ('2 %', 0.02),
        ('21 %', 0.21),
        # What it does not: aliased as the two it does, never `ureg.define()` (§6 step 2).
        ('100 ppb', 1e-7),
        ('1000 ppmv', 1e-3),
        ('50 ppbv', 5e-8),
        ('21 vol%', 0.21),
        ('5 mol%', 0.05),
        # A ratio written as the division it is.
        ('0.001 mol/mol', 0.001),
    ],
)
def test_parse_volume_ratio(text, fraction):
    assert parse(text, ureg.dimensionless).magnitude == pytest.approx(fraction)


@pytest.mark.parametrize('text', ['85 %RH', '85 %rh', '30 RH'])
def test_relative_humidity_is_refused_with_what_to_write(text):
    # It depends on the temperature, so it is not a value of the atmosphere alone.
    with pytest.raises(ValueError, match='not a volume ratio'):
        parse(text, ureg.dimensionless)

    with pytest.raises(ValueError, match='500 ppm'):
        parse(text, ureg.dimensionless)


@pytest.mark.parametrize('text', ['10 wt%', '5 ppmw', '5 ppbw'])
def test_a_mass_ratio_is_refused_rather_than_read_as_a_volume_ratio(text):
    with pytest.raises(ValueError, match='mass ratio'):
        parse(text, ureg.dimensionless)
