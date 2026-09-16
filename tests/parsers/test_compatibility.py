"""The authored format stays readable (Design.md §13.1a, §15.2).

Every authored input the schema accepted before §13 is kept here, each with the meaning
it must keep, read from the loaded sections' own fields. `load` is the one place that
says how an authored dict reaches the schema.
"""

import os

import pytest
import yaml
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.translate import (
    translate,
    translate_section,
)
from nomad_pv_stability_measurements.schema_packages.activity_steps import (
    BendRadius,
    Current,
    Irradiance,
    OxygenFraction,
    Resistance,
    Strain,
    Temperature,
    Voltage,
    WaterVaporFraction,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedSubroutineStep,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
IRRADIANCE = ureg.watt / ureg.meter**2
BLOCK = PlannedSubroutineStep


@pytest.fixture
def load(normalized, log):
    """Authored steps, translated and loaded into a block, normalized; the steps they
    became. What went wrong is in the `log` fixture: the translator's problems and the
    schema's reports alike."""

    def run(*authored):
        translation = translate_section({'steps': list(authored)}, BLOCK)
        log.errors.extend(problem.message for problem in translation.problems)
        return normalized(BLOCK.m_from_dict(translation.archive)).steps

    return run


@pytest.fixture
def load_file(normalized, log):
    """A whole authored file, translated, loaded and normalized: every step first, then
    the protocol, whose own normalize needs an archive with metadata."""

    def run(name: str):
        with open(os.path.join(DATA_DIR, name)) as file:
            translation = translate(yaml.safe_load(file))
        log.errors.extend(problem.message for problem in translation.problems)
        protocol = StabilityProtocol.m_from_dict(translation.archive['data'])
        for step in protocol.steps:
            normalized(step)
        metadata = EntryMetadata(entry_name=name)
        protocol.normalize(EntryArchive(metadata=metadata, data=protocol), log)
        return protocol

    return run


def magnitude(value, unit):
    return value.to(unit).magnitude


def test_the_channels_file(load_file, log):
    *settings, soak = load_file('channels.stability.yaml').steps

    # The one thing the example writes that the schema has no place for (§15.2).
    [error] = log.errors
    assert '`open_circuit` is not part of the schema any more' in error

    # Settings: conditions for the whole run — a unit-ful value, the sun, and a load
    # logged as a whole, one step per variable.
    temperature, irradiance, *load = settings
    assert temperature.estimated_duration is None
    assert isinstance(temperature, Temperature)
    assert (temperature.control, temperature.monitor) == (True, True)
    assert magnitude(temperature.setpoint, ureg.degC) == pytest.approx(65)
    assert magnitude(temperature.sample_every, ureg.s) == pytest.approx(60)
    assert magnitude(irradiance.setpoint, IRRADIANCE) == pytest.approx(1000)
    assert irradiance.spectrum == 'AM1.5G'
    assert [type(step) for step in load] == [Voltage, Current, Resistance]
    for step in load:
        assert (step.monitor, step.control, step.setpoint) == (True, None, None)
        assert magnitude(step.sampling_rate, ureg.Hz) == pytest.approx(1)

    # The routine: a block after the settings, overriding them for its span.
    assert soak.name == 'soak'
    hot, drift, dark, held = soak.steps
    assert magnitude(hot.setpoint, ureg.degC) == pytest.approx(85)
    # `500 h` is hours, not Planck's constant (§6 step 2).
    assert magnitude(hot.estimated_duration, ureg.hour) == pytest.approx(500)
    assert magnitude(hot.sampling_rate, ureg.Hz) == pytest.approx(10)
    assert (type(drift), drift.control, drift.setpoint) == (Temperature, None, None)
    # Deliberately dark is a value, not a missing one (D8a).
    assert magnitude(dark.setpoint, IRRADIANCE) == pytest.approx(0)
    assert isinstance(held, Voltage)
    assert magnitude(held.setpoint, ureg.V) == pytest.approx(0.8)
    # The routine wrote no duration of its own: it lasts as long as its episodes
    # together, 500 h + 100 h + 100 h + 24 h (§15.4).
    assert magnitude(soak.estimated_duration, ureg.hour) == pytest.approx(724)


def test_the_tree_file(load_file, log):
    [root] = load_file('tree.stability.yaml').steps

    assert log.errors == []
    assert root.name == 'example'
    assert [block.name for block in root.steps] == ['A', 'fork', 'D']
    assert [block.name for block in root.steps[1].steps] == ['B', 'C']
    assert root.steps[1].execution_mode == 'parallel'
    assert all(isinstance(block, BLOCK) for block in root.steps)


def test_one_list_holds_both_kinds_of_step_without_m_def(load):
    temperature, phase = load(
        {'channel': 'temperature', 'hold': '65 °C'},
        {'name': 'phase', 'commands': [{'channel': 'irradiation'}]},
    )

    assert isinstance(temperature, Temperature)
    assert isinstance(phase, BLOCK)
    assert isinstance(phase.steps[0], Irradiance)


def test_an_explicit_m_def_and_plain_numbers_still_load(load, log):
    # What NOMAD itself wrote back before §13: qualified `m_def`, the `channel`, a
    # `hold`, and numbers in the declared unit.
    [step] = load(
        {
            'm_def': 'nomad_pv_stability_measurements.schema_packages.'
            'channel_commands.TemperatureChannelCommand',
            'channel': 'temperature',
            'hold': 358.15,
            'duration': 3600,
        }
    )

    assert log.errors == []
    assert isinstance(step, Temperature)
    assert magnitude(step.setpoint, ureg.degC) == pytest.approx(85)
    assert magnitude(step.estimated_duration, ureg.hour) == pytest.approx(1)


def test_a_setpoint_is_written_either_as_the_variable_or_as_hold(load, log):
    for authored in [
        {'channel': 'mechanical', 'strain': '2 %'},
        {'channel': 'mechanical', 'variable': 'strain', 'hold': '2 %'},
    ]:
        [step] = load(authored)

        assert isinstance(step, Strain)
        assert step.setpoint.magnitude == pytest.approx(0.02)
    assert log.errors == []


def test_a_single_variable_needs_no_variable_named(load, log):
    [step] = load({'channel': 'mechanical', 'bend_radius': '5 mm'})

    assert isinstance(step, BendRadius)
    assert magnitude(step.setpoint, ureg.mm) == pytest.approx(5)
    assert log.errors == []


def test_the_isos_l_2_form(load, log):
    [step] = load(
        {
            'channel': 'electrical_load',
            'variable': 'voltage',
            'hold': '0.8 V',
            'sampling_rate': '10 Hz',
        }
    )

    assert log.errors == []
    assert (type(step), step.control) == (Voltage, True)
    assert magnitude(step.setpoint, ureg.V) == pytest.approx(0.8)
    assert magnitude(step.sampling_rate, ureg.Hz) == pytest.approx(10)
    assert magnitude(step.sample_every, ureg.s) == pytest.approx(0.1)


def test_open_circuit_is_reported_and_its_step_left_out(load, log):
    for authored in [{'hold': 'open_circuit'}, {'open_circuit': True}]:
        assert load({'channel': 'electrical_load', **authored}) == []
    assert ['open_circuit' in error for error in log.errors] == [True, True]


def test_a_named_setpoint_becomes_the_value_it_stands_for(load):
    [step] = load({'channel': 'irradiation', 'hold': 'dark', 'spectrum': 'AM1.5G'})

    assert isinstance(step, Irradiance)
    assert magnitude(step.setpoint, IRRADIANCE) == pytest.approx(0)
    assert step.spectrum == 'AM1.5G'


def test_blank_text_asks_nothing(load, log):
    for blank in ['', ' ', '\t', '\n']:
        [step] = load({'channel': 'temperature', 'hold': blank})

        assert (type(step), step.control, step.setpoint) == (
            Temperature,
            None,
            None,
        )
    assert log.errors == []


def test_overlapping_steps_are_reported(load, log):
    load(
        {'channel': 'temperature', 'hold': '85 °C'},
        {'channel': 'temperature', 'monitor': True},
    )

    [error] = log.errors
    assert 'overlap' in error
    assert 'not merged' in error


# What the file gets wrong is reported, never raised, and the rest still loads (§7).


def test_an_unreadable_value_is_reported(load, log):
    [step] = load(
        {'channel': 'temperature', 'hold': '85 °C', 'duration': 'a fortnight'}
    )

    assert step.estimated_duration is None
    assert magnitude(step.setpoint, ureg.degC) == pytest.approx(85)
    [error] = log.errors
    assert 'duration' in error


def test_a_bare_number_written_as_text_is_ambiguous(load, log):
    [step] = load({'channel': 'temperature', 'duration': '500'})

    assert step.estimated_duration is None
    assert 'bare number' in log.errors[0]


def test_a_wrong_dimension_is_reported(load, log):
    [step] = load({'channel': 'temperature', 'duration': '10 Hz'})

    assert step.estimated_duration is None
    assert len(log.errors) == 1


def test_a_named_setpoint_belongs_to_one_step(load, log):
    [step] = load({'channel': 'temperature', 'hold': 'dark'})

    assert step.setpoint is None
    [error] = log.errors
    assert 'hold' in error


def test_a_named_setpoint_belongs_to_the_setpoint(load, log):
    [step] = load({'channel': 'irradiation', 'duration': 'dark'})

    assert step.estimated_duration is None
    assert 'not a number followed by a unit' in log.errors[0]


def test_a_hold_with_no_variable_to_go_to_is_reported(load, log):
    assert load({'channel': 'electrical_load', 'hold': '0.8 V'}) == []
    [error] = log.errors
    assert 'voltage, current, resistance' in error


def test_a_variable_the_channel_does_not_have_is_reported(load, log):
    [step] = load({'channel': 'mechanical', 'variable': 'voltage', 'strain': '2 %'})

    # Reported, never repaired: the setpoint stands as authored.
    assert step.setpoint.magnitude == pytest.approx(0.02)
    [error] = log.errors
    assert 'bend_radius, strain' in error


# The atmosphere, written as an absolute volume ratio (§15.7).


def test_the_atmosphere_channel_logs_both_its_variables(load, log):
    water, oxygen = load({'channel': 'atmosphere', 'monitor': True})

    assert (type(water), type(oxygen)) == (WaterVaporFraction, OxygenFraction)
    assert [step.monitor for step in (water, oxygen)] == [True, True]
    assert log.errors == []


def test_a_glovebox_figure_and_a_volume_percent_share_one_axis(load, log):
    [glovebox] = load({'channel': 'atmosphere', 'oxygen': '0.1 ppm'})
    [ambient] = load({'channel': 'atmosphere', 'oxygen': '21 vol%'})

    assert (type(glovebox), glovebox.control) == (OxygenFraction, True)
    assert glovebox.setpoint.magnitude == pytest.approx(1e-7)
    assert ambient.setpoint.magnitude == pytest.approx(0.21)
    assert log.errors == []


def test_water_vapour_is_written_either_as_the_variable_or_as_hold(load, log):
    for authored in [
        {'channel': 'atmosphere', 'water_vapor': '500 ppm'},
        {'channel': 'atmosphere', 'variable': 'water_vapor', 'hold': '500 ppm'},
    ]:
        [step] = load(authored)

        assert isinstance(step, WaterVaporFraction)
        assert step.setpoint.magnitude == pytest.approx(5e-4)
    assert log.errors == []


def test_humidity_is_reported_with_what_to_write_instead(load, log):
    # `85 %RH` says nothing without the temperature it was measured at, so it is never
    # translated into a ratio: the step is left out, as `open_circuit` is (§15.2).
    for authored in [
        {'channel': 'atmosphere', 'humidity': '85 %RH'},
        {'channel': 'atmosphere', 'variable': 'humidity', 'hold': '85 %RH'},
    ]:
        assert load(authored) == []
    assert ['water_vapor' in error for error in log.errors] == [True, True]


def test_a_relative_humidity_value_on_the_water_axis_is_refused(load, log):
    [step] = load({'channel': 'atmosphere', 'water_vapor': '85 %RH'})

    # Reported, never repaired: the step stays, without a setpoint nobody can read.
    assert (isinstance(step, WaterVaporFraction), step.setpoint) == (True, None)
    [error] = log.errors
    assert 'not a volume ratio' in error
