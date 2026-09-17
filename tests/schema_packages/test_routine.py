"""The monitor/control instructions, tested on bare dicts: `m_def` written out, numbers
in the declared unit (Design.md §15.1). Blocks are tests/schema_packages/test_general.py;
how an authored file gets here is tests/parsers."""

import os

import pytest
from nomad.client import normalize_all, parse
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    Instruction,
    InstructionBlock,
    SingleInstruction,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldCurrent,
    HoldIrradiance,
    HoldResistance,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import VOCTracking
from nomad_pv_stability_measurements.schema_packages.ramp_instructions import (
    RampTemperature,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    MonitorControlInstruction,
    RampInstruction,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
BLOCK = InstructionBlock


@pytest.mark.parametrize(
    ('written', 'derived', 'expected'),
    [
        ({'sample_every': 60}, 'sampling_rate', 1 / 60),
        ({'sampling_rate': 10}, 'sample_every', 0.1),
    ],
)
def test_both_sampling_figures_are_stored(normalized, written, derived, expected):
    # Whichever the archive holds, the other is calculated from it (13.5 a).
    instruction = normalized(HoldTemperature.m_from_dict(written))

    assert getattr(instruction, derived).magnitude == pytest.approx(expected)


def test_both_kinds_of_instruction_share_one_base():
    assert issubclass(MonitorControlInstruction, SingleInstruction)
    assert issubclass(BLOCK, Instruction)
    assert {'name', 'estimated_duration'} <= set(Instruction.m_def.all_quantities)


def test_only_monitor_control_instructions_carry_tags():
    tags = {'monitor', 'control', 'sample_every', 'sampling_rate'}

    assert tags <= set(MonitorControlInstruction.m_def.all_quantities)
    assert tags.isdisjoint(BLOCK.m_def.all_quantities)
    # What an instruction holds or moves sits on its kind, not on the base (§15.11).
    assert {'set_point', 'start_point'}.isdisjoint(
        MonitorControlInstruction.m_def.all_quantities
    )


def test_an_instruction_built_as_the_base_names_no_quantity(normalized, log):
    normalized(MonitorControlInstruction(name='stray'))

    [error] = log.errors
    assert 'stray is a bare `MonitorControlInstruction`' in error


def test_entry_loads_the_bare_archive_file():
    archive = parse(os.path.join(DATA_DIR, 'channels.archive.yaml'))[0]
    normalize_all(archive)
    *settings, soak = archive.data.instructions

    # What held for the whole run comes first, as instructions that never finish.
    assert [type(each) for each in settings] == [
        HoldTemperature,
        HoldIrradiance,
        HoldVoltage,
        HoldCurrent,
        HoldResistance,
    ]
    temperature, irradiance, voltage = settings[:3]
    assert temperature.estimated_duration is None
    assert (temperature.control, temperature.monitor) == (True, True)
    assert temperature.set_point.to(ureg.degC).magnitude == pytest.approx(65)
    assert irradiance.spectrum == 'AM1.5G'
    assert (voltage.control, voltage.set_point, voltage.monitor) == (None, None, True)

    assert isinstance(soak, BLOCK)
    assert [type(each) for each in soak.sub_instructions] == [
        HoldTemperature,
        HoldTemperature,
        HoldIrradiance,
        HoldVoltage,
        # The example's `open_circuit`, which reaches an instruction of its own (§15.13).
        VOCTracking,
    ]
    hot = soak.sub_instructions[0]
    assert hot.estimated_duration.to(ureg.hour).magnitude == pytest.approx(500)
    # One pass: 500 h + 100 h + 100 h + 24 h + 1 h.
    assert soak.estimated_duration.to(ureg.hour).magnitude == pytest.approx(725)
    # The settings never finish, and the protocol starts everything together.
    assert archive.data.estimated_duration is None


# A ramp: both ends, and the rate the duration says (§15.11).


def test_a_ramp_needs_both_its_ends(normalized, log):
    normalized(RampTemperature(name='warm up', start_point=298.15 * ureg.kelvin))

    [error] = log.errors
    assert 'warm up moves between two values but is missing an end' in error


def test_a_ramp_derives_its_rate_from_its_duration(normalized, log):
    ramp = normalized(
        RampTemperature(
            start_point=298.15 * ureg.kelvin,
            end_point=358.15 * ureg.kelvin,
            estimated_duration=3600 * ureg.second,
        )
    )

    # 60 K in an hour, whichever way round the ends were written.
    assert ramp.ramp_rate.to(ureg.kelvin / ureg.hour).magnitude == pytest.approx(60)
    assert (log.errors, log.warnings) == ([], [])


def test_a_ramp_derives_its_duration_from_its_rate(normalized, log):
    ramp = normalized(
        RampTemperature(
            start_point=358.15 * ureg.kelvin,
            end_point=298.15 * ureg.kelvin,
            ramp_rate=60 * ureg.kelvin / ureg.hour,
        )
    )

    # Cooling down: the rate is a magnitude, the direction is the ends (D16).
    assert ramp.estimated_duration.to(ureg.hour).magnitude == pytest.approx(1)
    assert (log.errors, log.warnings) == ([], [])


def test_a_rate_that_contradicts_the_duration_is_reported(normalized, log):
    ramp = normalized(
        RampTemperature(
            name='warm up',
            start_point=298.15 * ureg.kelvin,
            end_point=358.15 * ureg.kelvin,
            ramp_rate=60 * ureg.kelvin / ureg.hour,
            estimated_duration=7200 * ureg.second,
        )
    )

    # Reported, never repaired: both stand as authored (D13a).
    assert ramp.estimated_duration.to(ureg.hour).magnitude == pytest.approx(2)
    [error] = log.errors
    assert 'warm up writes a `ramp_rate`' in error


def test_a_ramp_with_neither_a_rate_nor_a_duration_never_finishes(normalized, log):
    ramp = normalized(
        RampTemperature(
            start_point=298.15 * ureg.kelvin, end_point=358.15 * ureg.kelvin
        )
    )

    # Like any other instruction without a duration (§23).
    assert (ramp.estimated_duration, ramp.ramp_rate) == (None, None)
    assert (log.errors, log.warnings) == ([], [])


# A ramp that repeats is a cycle, and one member of them states no path (§21.2).


def test_a_cycle_by_an_unstated_path_is_a_ramp_that_says_so(normalized, log):
    ramp = normalized(
        RampTemperature(
            start_point=296.15 * ureg.kelvin,
            end_point=338.15 * ureg.kelvin,
            end_of_ramp_behavior='cycle',
            estimated_duration=3600 * ureg.second,
        )
    )

    # No path, so no rate along it is derived from the duration.
    assert ramp.ramp_rate is None
    assert (log.errors, log.warnings) == ([], [])


def test_a_cycle_by_an_unstated_path_takes_no_rate(normalized, log):
    ramp = normalized(
        RampTemperature(
            name='thermal cycle',
            start_point=296.15 * ureg.kelvin,
            end_point=338.15 * ureg.kelvin,
            end_of_ramp_behavior='cycle',
            ramp_rate=60 * ureg.kelvin / ureg.hour,
        )
    )

    # Reported, never repaired, and no duration derived from it (D13a).
    assert ramp.estimated_duration is None
    [error] = log.errors
    assert 'thermal cycle cycles by a path the protocol does not state' in error


def test_a_cycle_still_needs_both_its_ends(normalized, log):
    normalized(
        RampTemperature(
            name='thermal cycle',
            start_point=296.15 * ureg.kelvin,
            end_of_ramp_behavior='cycle',
        )
    )

    [error] = log.errors
    assert 'thermal cycle moves between two values but is missing an end' in error


def test_an_instruction_built_as_a_bare_kind_names_no_quantity(normalized, log):
    normalized(RampInstruction(name='stray'))

    [error] = log.errors
    assert 'stray is a bare `RampInstruction`' in error
