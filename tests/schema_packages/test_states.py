import pytest

from nomad_pv_stability_measurements.schema_packages.protocol import Protocol
from nomad_pv_stability_measurements.schema_packages.states import (
    GENERIC_STATES,
    STATE_SLOTS,
    Cycle,
    Ramp,
    Sweep,
    Tabulated,
)


@pytest.mark.parametrize('state_type', [Ramp, Sweep])
def test_from_is_read_through_its_alias(state_type):
    state = state_type.m_from_dict({'from': '-0.2 V', 'to': '1.3 V'})
    assert state.from_ == '-0.2 V'
    assert state.to == '1.3 V'


@pytest.mark.parametrize('state_type', [Ramp, Sweep])
def test_from_serializes_as_from_underscore_and_round_trips(state_type):
    serialized = state_type.m_from_dict({'from': '65 °C', 'to': '25 °C'}).m_to_dict()
    assert serialized == {'from_': '65 °C', 'to': '25 °C'}
    assert state_type.m_from_dict(serialized).from_ == '65 °C'


def test_ramp_rate_is_optional():
    ramp = Ramp.m_from_dict({'from': '65 °C', 'to': '25 °C'})
    assert ramp.rate is None
    assert Ramp.m_from_dict({'from': '65 °C', 'to': '25 °C', 'rate': '0.4 K/h'}).rate


def test_sweep_fields_and_default_direction():
    sweep = Sweep.m_from_dict({'from': '-0.2 V', 'to': '1.3 V', 'rate': '50 mV/s'})
    assert sweep.rate == '50 mV/s'
    assert sweep.direction == 'forward'
    assert Sweep(direction='both').direction == 'both'


def test_cycle_fields():
    cycle = Cycle.m_from_dict(
        {
            'waveform': 'square',
            'low': '25 °C',
            'high': '85 °C',
            'period': '24 h',
            'duty_cycle': 0.25,
        }
    )
    assert (cycle.low, cycle.high, cycle.period, cycle.duty_cycle) == (
        '25 °C',
        '85 °C',
        '24 h',
        0.25,
    )


def test_tabulated_fields_and_default_interpolation():
    tabulated = Tabulated.m_from_dict(
        {'time': ['0 h', '1 h', '3 h'], 'value': ['25 °C', '85 °C', '85 °C']}
    )
    assert tabulated.time == ['0 h', '1 h', '3 h']
    assert tabulated.value == ['25 °C', '85 °C', '85 °C']
    assert tabulated.interpolation == 'linear'


@pytest.mark.parametrize(
    'state_type, field, bad_value',
    [
        (Cycle, 'waveform', 'sawtooth'),
        (Tabulated, 'interpolation', 'cubic'),
        (Sweep, 'direction', 'sideways'),
    ],
)
def test_enums_reject_unknown_values(state_type, field, bad_value):
    with pytest.raises(ValueError):
        state_type.m_from_dict({field: bad_value})


def test_state_slots_are_exactly_the_protocol_slots():
    properties = Protocol.m_def.all_properties
    assert all(slot in properties for slot in STATE_SLOTS)
    assert len(set(STATE_SLOTS)) == len(STATE_SLOTS)


def test_section_slots_use_the_state_sections():
    sub_sections = Protocol.m_def.all_sub_sections
    assert {
        name: sub_sections[name].sub_section.section_cls
        for name in ('ramp', 'cycle', 'tabulated', 'sweep')
    } == {'ramp': Ramp, 'cycle': Cycle, 'tabulated': Tabulated, 'sweep': Sweep}


def test_generic_states_are_state_slots():
    assert GENERIC_STATES <= set(STATE_SLOTS)
    assert not GENERIC_STATES & {'off', 'track', 'sweep'}
