"""The monitor/control instructions: one class per quantity and kind, and the values a
standard names (Design.md §15.11, §17, §20.3, §22)."""

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.base_instructions import (
    HoldBelowInstruction,
    HoldBetweenInstruction,
    HoldInstruction,
    MonitorControlInstruction,
    RampInstruction,
)
from nomad_pv_stability_measurements.schema_packages.characterization_instructions import (
    CharacterizationInstruction,
    JVScan,
)
from nomad_pv_stability_measurements.schema_packages.general import Duration, Period
from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBelowRelativeHumidity,
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    BalanceGas,
    HoldAbsoluteHumidity,
    HoldCurrent,
    HoldIrradiance,
    HoldPressure,
    HoldRelativeHumidity,
    HoldResistance,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.ramp_instructions import (
    RampCurrent,
    RampRelativeHumidity,
    RampResistance,
    RampTemperature,
    RampVoltage,
)
from nomad_pv_stability_measurements.schema_packages.standard_values import (
    Dark,
    RoomTemperature,
)

K = ureg.kelvin


def fixed(value) -> Duration:
    return Duration(kind='fixed', value=value)


def open_ended() -> Duration:
    return Duration(kind='open_ended')


@pytest.mark.parametrize(
    ('cls', 'field', 'unit'),
    [
        (HoldTemperature, 'value', 'K'),
        (HoldTemperature, 'tolerance', 'K'),
        (HoldIrradiance, 'value', 'W/m^2'),
        (HoldVoltage, 'value', 'V'),
        (HoldCurrent, 'value', 'A'),
        (HoldResistance, 'value', 'ohm'),
        (HoldPressure, 'value', 'Pa'),
        # The atmosphere as a volume ratio, the relative humidity as the fraction (§20.6).
        (HoldAbsoluteHumidity, 'value', 'dimensionless'),
        (HoldRelativeHumidity, 'value', 'dimensionless'),
        (HoldBelowRelativeHumidity, 'upper_bound', 'dimensionless'),
        (HoldBetweenIrradiance, 'lower_bound', 'W/m^2'),
        (RampTemperature, 'ramp_rate', 'K/s'),
    ],
)
def test_each_class_declares_the_unit_of_its_quantity(cls, field, unit):
    declared = cls.m_def.all_quantities[field].unit

    assert (1 * declared).to(unit).magnitude == pytest.approx(1)


def test_every_quantity_that_can_be_held_can_also_be_ramped():
    holds = {
        cls.__name__.removeprefix('Hold') for cls in HoldInstruction.__subclasses__()
    }
    ramps = {
        cls.__name__.removeprefix('Ramp') for cls in RampInstruction.__subclasses__()
    }

    assert holds == ramps


@pytest.mark.parametrize('cls', [MPPTracking, VOCTracking, BalanceGas])
def test_what_the_cell_decides_or_names_takes_no_value(cls):
    assert 'value' not in cls.m_def.all_quantities


@pytest.mark.parametrize(
    ('cls', 'points'),
    [
        (HoldVoltage, ['V_MPP', 'near V_MPP', 'V_oc', '-V_oc']),
        (HoldCurrent, ['J_SC', '-J_MPP']),
    ],
)
def test_a_bias_may_be_a_point_of_the_device_and_only_a_known_one(cls, points):
    for point in points:
        assert cls(reference_point=point).reference_point == point
    with pytest.raises(ValueError):
        cls(reference_point='E_g/q')


@pytest.mark.parametrize(
    ('written', 'derived', 'expected'),
    [
        ({'sample_every': 60 * ureg.second}, 'sampling_rate', 1 / 60),
        ({'sampling_rate': 10 * ureg.hertz}, 'sample_every', 0.1),
    ],
)
def test_either_sampling_figure_gives_the_other(normalized, written, derived, expected):
    instruction = normalized(HoldTemperature(**written))

    assert getattr(instruction, derived).magnitude == pytest.approx(expected)


@pytest.mark.parametrize(
    'cls',
    [
        MonitorControlInstruction,
        HoldInstruction,
        HoldBelowInstruction,
        HoldBetweenInstruction,
        RampInstruction,
    ],
)
def test_a_base_that_names_no_quantity_is_reported(normalized, log, cls):
    normalized(cls(name='stray', duration=open_ended()))

    [error] = log.errors
    assert f'stray is a bare `{cls.__name__}`' in error


# A ramp (§15.11, §21.2).


@pytest.mark.parametrize(
    ('written', 'field', 'expected'),
    [
        ({'duration': fixed(3600 * ureg.second)}, 'ramp_rate', 60 / 3600),
        ({'ramp_rate': 60 * K / ureg.hour}, 'duration', 3600),
    ],
)
def test_a_ramp_derives_its_rate_or_its_duration(
    normalized, log, written, field, expected
):
    ramp = normalized(
        RampTemperature(start_point=358.15 * K, end_point=298.15 * K, **written)
    )

    # The rate is a magnitude; the direction is the ends.
    derived = getattr(ramp, field)
    if field == 'duration':
        assert derived.kind == 'derived'
        derived = derived.value
    assert derived.magnitude == pytest.approx(expected)
    assert log.errors == []


def test_a_rate_that_contradicts_the_duration_is_reported_not_repaired(normalized, log):
    ramp = normalized(
        RampTemperature(
            start_point=298.15 * K,
            end_point=358.15 * K,
            ramp_rate=60 * K / ureg.hour,
            duration=fixed(7200 * ureg.second),
        )
    )

    assert ramp.duration.value.magnitude == pytest.approx(7200)
    [error] = log.errors
    assert '`ramp_rate`' in error


def test_a_cycle_states_no_path_so_it_takes_no_rate(normalized, log):
    ramp = normalized(
        RampTemperature(
            start_point=296.15 * K,
            end_point=338.15 * K,
            end_of_ramp_behavior='cycle',
            ramp_rate=60 * K / ureg.hour,
            duration=open_ended(),
        )
    )

    assert ramp.duration.kind == 'open_ended'
    [error] = log.errors
    assert 'does not state' in error


@pytest.mark.parametrize(
    ('section', 'reported'),
    [
        (
            RampTemperature(start_point=298.15 * K, duration=open_ended()),
            'missing an end',
        ),
        (
            HoldBetweenIrradiance(
                upper_bound=1000 * ureg('W/m^2'), duration=open_ended()
            ),
            'missing one',
        ),
        (
            HoldBetweenIrradiance(
                lower_bound=1000 * ureg('W/m^2'),
                upper_bound=800 * ureg('W/m^2'),
                duration=open_ended(),
            ),
            'above its `upper_bound`',
        ),
    ],
)
def test_ends_and_bounds_must_both_be_there_and_in_order(
    normalized, log, section, reported
):
    normalized(section)

    [error] = log.errors
    assert reported in error


# Values a standard names (§17.2).


def test_room_temperature_is_23_plus_minus_4_celsius():
    room = RoomTemperature()

    assert room.value.to(ureg.degC).magnitude == pytest.approx(23)
    assert room.tolerance.to(K).magnitude == pytest.approx(4)


def test_dark_is_exactly_no_light():
    dark = Dark()

    assert dark.value.magnitude == 0
    assert dark.tolerance is None


@pytest.mark.parametrize(
    ('instruction', 'label'),
    [
        (
            HoldTemperature(control=True, value=338.15 * K),
            'Hold temperature 65 °C',
        ),
        (
            HoldRelativeHumidity(control=False, monitor=True),
            'Monitor relative humidity',
        ),
        (
            HoldIrradiance(value=0 * ureg('W/m^2'), duration=fixed(4800 * ureg.s)),
            'Irradiance 0 W/m² for 80 min',
        ),
        (
            HoldTemperature(value=296.15 * K, monitor=True),
            'Monitor temperature 23 °C',
        ),
        (
            HoldVoltage(reference_point='near V_MPP', control=True),
            'Hold voltage at near V_MPP',
        ),
        (
            HoldBelowRelativeHumidity(upper_bound=0.55 * ureg.dimensionless),
            'Relative humidity below 55 %',
        ),
        (
            HoldBetweenIrradiance(
                lower_bound=800 * ureg('W/m^2'),
                upper_bound=1000 * ureg('W/m^2'),
                control=True,
            ),
            'Hold irradiance between 800 W/m² and 1000 W/m²',
        ),
        (
            RampTemperature(
                control=True,
                start_point=296.15 * K,
                end_point=338.15 * K,
                end_of_ramp_behavior='triangle',
            ),
            'Ramp temperature 23 °C → 65 °C (triangle)',
        ),
        (MPPTracking(control=True), 'MPP tracking'),
        (BalanceGas(gas='N2'), 'Balance gas N2'),
    ],
)
def test_an_instruction_is_listed_by_what_it_does(normalized, instruction, label):
    assert normalized(instruction).label == label


def test_a_hold_is_drawn_at_its_value_for_as_long_as_it_is_drawn():
    times, values = HoldTemperature(value=338.15 * K).set_values_for_plotting(
        12 * ureg.hour
    )

    assert times.to('hour').magnitude == pytest.approx([0, 12])
    assert values.to(ureg.degC).magnitude == pytest.approx([65, 65])


@pytest.mark.parametrize(
    'behavior, hours, celsius',
    [
        ('hold', [0, 1, 3], [25, 65, 65]),
        ('sawtooth', [0, 1, 1, 2, 2, 3], [25, 65, 25, 65, 25, 65]),
        ('triangle', [0, 1, 2, 3], [25, 65, 25, 65]),
    ],
)
def test_a_ramp_is_drawn_through_its_corners(behavior, hours, celsius):
    ramp = RampTemperature(
        start_point=298.15 * K,
        end_point=338.15 * K,
        ramp_rate=40 * K / ureg.hour,
        end_of_ramp_behavior=behavior,
    )

    times, values = ramp.set_values_for_plotting(3 * ureg.hour)

    assert times.to('hour').magnitude == pytest.approx(hours)
    assert values.to(ureg.degC).magnitude == pytest.approx(celsius)


@pytest.mark.parametrize(
    'instruction, text',
    [
        (MPPTracking(), 'MPP'),
        (VOCTracking(), 'open circuit'),
        (HoldVoltage(reference_point='near V_MPP'), 'near V_MPP'),
        (HoldRelativeHumidity(monitor=True, control=False), 'monitored'),
        (HoldIrradiance(control=True, monitor=True), 'not specified'),
        (
            HoldBetweenIrradiance(
                lower_bound=800 * ureg('W/m^2'), upper_bound=1000 * ureg('W/m^2')
            ),
            '800 W/m²–1000 W/m²',
        ),
        # No plausible pace is known for humidity: only its range is.
        (
            RampRelativeHumidity(
                start_point=0.3, end_point=0.85, end_of_ramp_behavior='cycle'
            ),
            '30 % → 85 % (cycle), path not stated',
        ),
    ],
)
def test_what_the_protocol_gives_no_value_is_written_as_text(instruction, text):
    assert instruction.set_values_for_plotting(1 * ureg.hour) is None
    assert instruction.annotation_for_plotting() == text


def test_an_instruction_is_drawn_on_its_quantity_row_from_when_it_starts():
    hold = HoldTemperature(value=338.15 * K, duration=fixed(12 * ureg.hour))

    [piece] = hold.time_series_for_plotting(start=7200, stop=10**6).pieces

    assert piece.row == 'temperature'
    assert (piece.start, piece.end) == (7200, 7200 + 12 * 3600)
    assert piece.times.tolist() == [7200, 7200 + 12 * 3600]
    assert not piece.endless


def test_an_instruction_that_never_finishes_is_drawn_until_the_drawing_stops():
    stop = 3600
    [piece] = MPPTracking().time_series_for_plotting(start=0, stop=stop).pieces

    assert (piece.row, piece.text) == ('electrical load', 'MPP')
    assert piece.end == stop
    assert piece.endless


@pytest.mark.parametrize(
    'instruction, role',
    [
        # "controlled elevated temperatures of 65 or 85 °C" (Khenkin et al. 2020)
        (HoldTemperature(value=338.15 * K, control=True), 'controlled'),
        (MPPTracking(control=True), 'controlled'),
        (HoldVoltage(reference_point='near V_MPP', control=True), 'controlled'),
        # Controlled at a value the protocol leaves open: still controlled.
        (HoldIrradiance(control=True, monitor=True), 'controlled'),
        # "monitored but not explicitly controlled", with or without a value
        (HoldRelativeHumidity(monitor=True), 'monitored'),
        (HoldTemperature(value=296.15 * K, monitor=True), 'monitored'),
        # "open-circuit (disconnected)", and a light source "None": stated, nothing more
        (VOCTracking(), 'specified'),
        (HoldIrradiance(value=0 * ureg('W/m^2')), 'specified'),
        (HoldTemperature(value=296.15 * K), 'specified'),
        (HoldTemperature(), 'unspecified'),
    ],
)
def test_an_instruction_is_coloured_by_the_most_the_protocol_asks_of_it(
    instruction, role
):
    assert instruction.role_for_plotting() == role


@pytest.mark.parametrize(
    'behavior, assumption',
    [
        ('triangle', 'rate not specified: drawn at 100 K/h'),
        ('cycle', 'path and rate not specified: drawn linear at 100 K/h'),
    ],
)
def test_a_temperature_ramp_without_a_pace_is_drawn_at_a_plausible_one(
    behavior, assumption
):
    """IEC 61215's fastest thermal cycling, and said so: ISOS leaves the pace open."""
    ramp = RampTemperature(
        start_point=296.15 * K, end_point=346.15 * K, end_of_ramp_behavior=behavior
    )

    times, values = ramp.set_values_for_plotting(1 * ureg.hour)

    assert times.to('hour').magnitude == pytest.approx([0, 0.5, 1])
    assert values.to(ureg.degC).magnitude == pytest.approx([23, 73, 23])
    assert ramp.assumption_for_plotting() == assumption
    assert ramp.bounds_for_plotting() is None


def test_a_ramp_without_a_pace_or_a_plausible_one_is_drawn_as_its_range():
    ramp = RampRelativeHumidity(
        start_point=0.85, end_point=0.3, end_of_ramp_behavior='triangle'
    )

    assert ramp.set_values_for_plotting(1 * ureg.hour) is None
    assert ramp.bounds_for_plotting() == (pytest.approx(0.3), pytest.approx(0.85))
    assert ramp.annotation_for_plotting() == '85 % → 30 % (triangle), rate not stated'


@pytest.mark.parametrize(
    ('cls', 'controlled', 'monitored'),
    [
        # The cell's terminals are one port: what is set, and what the device answers.
        (HoldVoltage, ('voltage',), ('current',)),
        (RampVoltage, ('voltage',), ('current',)),
        (HoldCurrent, ('current',), ('voltage',)),
        (RampCurrent, ('current',), ('voltage',)),
        (HoldResistance, ('resistance',), ('voltage', 'current')),
        (RampResistance, ('resistance',), ('voltage', 'current')),
        (MPPTracking, ('voltage',), ('current',)),
        (VOCTracking, ('current',), ('voltage',)),
        # Independent quantities: control and monitor act on the quantity itself.
        (HoldTemperature, ('temperature',), ('temperature',)),
        (RampRelativeHumidity, ('relative humidity',), ('relative humidity',)),
    ],
)
def test_control_regulates_what_is_set_and_monitor_logs_what_follows(
    cls, controlled, monitored
):
    instruction = cls(control=True, monitor=True)

    assert instruction.controlled_quantities() == controlled
    assert instruction.monitored_quantities() == monitored


def test_jv_scans_are_marks_at_their_moments_on_the_electrical_load(normalized, log):
    every = Period(kind='fixed', value=10 * ureg.minute)
    scans = normalized(JVScan(duration=fixed(1 * ureg.hour), interval=every))

    [piece] = scans.time_series_for_plotting(0, 7200).pieces
    assert scans.label == 'J–V scan every 10 min'
    # A scan takes the cell's terminals, whatever else holds them.
    assert (piece.row, piece.role) == ('electrical load', 'monitored')
    assert piece.marks.tolist() == [0, 600, 1200, 1800, 2400, 3000]
    assert log.errors == []


@pytest.mark.parametrize(
    ('interval', 'label'),
    [
        (None, 'J–V scan'),
        (Period(kind='typical', value=1 * ureg.hour), 'J–V scan every ≈ 1 h'),
        # "a periodicity that depends on the characteristic degradation timescale of
        # each given device" (Khenkin et al. 2020, p.43)
        (Period(kind='not_stated'), 'J–V scan periodically'),
    ],
)
def test_jv_scans_say_how_their_interval_is_known(normalized, interval, label):
    scans = normalized(JVScan(duration=fixed(1 * ureg.hour), interval=interval))

    assert scans.label == label


@pytest.mark.parametrize(
    ('interval', 'marks', 'assumed'),
    [
        (None, [0], None),
        (Period(kind='not_stated'), [0, 900, 1800, 2700], 'interval not stated'),
    ],
)
def test_one_scan_is_one_mark_and_scans_without_an_interval_are_drawn_as_assumed(
    interval, marks, assumed
):
    scans = JVScan(duration=Duration(kind='whole_block'), interval=interval)

    [piece] = scans.time_series_for_plotting(0, 3600).pieces
    assert piece.marks.tolist() == marks
    assert (piece.assumption or '').startswith(assumed or '')
    assert bool(piece.assumption) == bool(assumed)


def test_a_bare_characterization_names_no_measurement_and_is_reported(normalized, log):
    normalized(CharacterizationInstruction(duration=fixed(1 * ureg.hour)))

    [message] = log.errors
    assert 'names no measurement' in message


@pytest.mark.parametrize(
    ('interval', 'reported'),
    [
        (Period(kind='fixed', value=0 * ureg.minute), 'must be positive'),
        (Period(kind='typical'), 'but no value'),
        (Period(kind='not_stated', value=1 * ureg.hour), 'takes no value'),
    ],
)
def test_an_interval_s_value_suits_its_kind(normalized, log, interval, reported):
    normalized(JVScan(duration=fixed(1 * ureg.hour), interval=interval))

    [message] = log.errors
    assert '`interval`' in message
    assert reported in message
