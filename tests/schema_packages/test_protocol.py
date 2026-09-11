import pytest
import yaml
from nomad.datamodel.data import EntryData
from nomad.datamodel.metainfo.basesections import BaseSection
from nomad.datamodel.metainfo.plot import PlotSection

from nomad_pv_stability_measurements.schema_packages.channels import Channels
from nomad_pv_stability_measurements.schema_packages.protocol import (
    Protocol,
    ProtocolSummary,
    StabilityProtocol,
    State,
)
from nomad_pv_stability_measurements.schema_packages.states import (
    STATE_SLOTS,
    Cycle,
    Ramp,
    Sweep,
    Tabulated,
)
from nomad_pv_stability_measurements.schema_packages.timeline import ProtocolTimeline

# --- the recursive node ----------------------------------------------------------


def test_steps_nest_without_limit():
    node = {'channel': 'chuck_T', 'hold': '65 °C'}
    for depth in range(5):
        node = {'subprotocol': f'level {depth}', 'steps': [node]}
    root = Protocol.m_from_dict({'name': 'deep', 'steps': [node]})

    leaf = root
    for _ in range(6):
        (leaf,) = leaf.steps
        assert isinstance(leaf, Protocol)
    assert leaf.hold == '65 °C'


def test_mode_defaults_to_sequential():
    assert Protocol().mode == 'sequential'
    assert Protocol(mode='parallel').mode == 'parallel'


def test_mode_rejects_unknown_values():
    with pytest.raises(ValueError):
        Protocol(mode='interleaved')


@pytest.mark.parametrize(
    'authored, stored', [(42, '42'), ('42', '42'), ('forever', 'forever')]
)
def test_repetitions_accepts_integers_and_forever(authored, stored):
    assert Protocol.m_from_dict({'repetitions': authored}).repetitions == stored


def test_track_is_an_enum():
    assert Protocol(track='voc').track == 'voc'
    with pytest.raises(ValueError):
        Protocol(track='isc')


def test_duration_s_is_seconds():
    node = Protocol(duration_s=3600)
    assert str(node.duration_s.units) == 'second'
    assert node.duration_s.to('hour').magnitude == 1


def test_round_trip_keeps_the_tree():
    authored = {
        'name': 'light soak',
        'mode': 'parallel',
        'steps': [
            {'channel': 'chuck_T', 'hold': '65 °C'},
            {
                'subprotocol': 'daily cycle',
                'repetitions': '42',
                'stop_when': 'pce_relative < 80 %',
                'steps': [
                    {'channel': 'bias', 'track': 'mpp', 'duration': '24 h'},
                    {
                        'channel': 'bias',
                        'variable': 'voltage',
                        'sweep': {'from': '-0.2 V', 'to': '1.3 V', 'rate': '50 mV/s'},
                    },
                ],
            },
        ],
    }
    root = Protocol.m_from_dict(authored)
    again = Protocol.m_from_dict(root.m_to_dict())
    assert again.m_to_dict() == root.m_to_dict()
    assert again.steps[1].stop_when == 'pce_relative < 80 %'
    assert again.steps[1].steps[1].sweep.from_ == '-0.2 V'


# --- the state accessor ----------------------------------------------------------

SCALAR_STATES = [
    ('uncontrolled', True),
    ('off', True),
    ('hold', '65 °C'),
    ('track', 'mpp'),
]
SECTION_STATES = [
    ('ramp', {'from': '65 °C', 'to': '25 °C'}, Ramp),
    ('cycle', {'waveform': 'sine', 'low': '25 °C', 'high': '85 °C'}, Cycle),
    ('tabulated', {'time': ['0 h'], 'value': ['25 °C']}, Tabulated),
    ('sweep', {'from': '0 V', 'to': '1 V', 'rate': '10 mV/s'}, Sweep),
]


@pytest.mark.parametrize('slot, value', SCALAR_STATES)
def test_scalar_state(slot, value):
    node = Protocol.m_from_dict({'channel': 'c', slot: value})
    assert node.state_slots == (slot,)
    assert node.state == State(slot, value)


@pytest.mark.parametrize('slot, value, section_type', SECTION_STATES)
def test_section_state(slot, value, section_type):
    node = Protocol.m_from_dict({'channel': 'c', slot: value})
    assert node.state_slots == (slot,)
    assert node.state.slot == slot
    assert isinstance(node.state.value, section_type)
    assert node.state.value is getattr(node, slot)


def test_every_slot_is_covered_by_the_tests_above():
    covered = [s[0] for s in SCALAR_STATES] + [s[0] for s in SECTION_STATES]
    assert sorted(covered) == sorted(STATE_SLOTS)


def test_container_has_no_state():
    node = Protocol.m_from_dict({'subprotocol': 'block', 'steps': [{}]})
    assert node.state_slots == ()
    assert node.state is None


@pytest.mark.parametrize('slot', ['uncontrolled', 'off'])
def test_false_flag_is_not_a_state(slot):
    node = Protocol.m_from_dict({'channel': 'sun', slot: False})
    assert node.state_slots == ()
    assert node.state is None


@pytest.mark.parametrize('flag', [True, False])
def test_off_key_survives_yaml_1_1(flag):
    """PyYAML reads the bare key `off` as False: `off: true` is `{False: True}`."""
    data = yaml.safe_load(f'{{channel: sun, off: {str(flag).lower()}}}')
    assert data[False] is flag
    node = Protocol.m_from_dict(data)
    assert node.off is flag
    assert node.state == (State('off', True) if flag else None)


def test_empty_hold_is_not_a_state():
    assert Protocol(hold='').state is None


def test_several_slots_are_reported_and_refused():
    node = Protocol.m_from_dict(
        {'channel': 'c', 'hold': '65 °C', 'ramp': {'from': '1 K', 'to': '2 K'}}
    )
    assert node.state_slots == ('hold', 'ramp')
    with pytest.raises(ValueError, match='hold, ramp'):
        node.state  # noqa: B018


def test_state_follows_edits():
    node = Protocol(channel='chuck_T', hold='65 °C')
    node.hold = None
    node.ramp = Ramp(from_='65 °C', to='25 °C')
    assert node.state.slot == 'ramp'


# --- ELN ------------------------------------------------------------------------


def test_eln_order_lists_every_property_once():
    order = Protocol.m_def.m_get_annotations('display').order
    assert len(order) == len(set(order))
    assert set(order) == set(Protocol.m_def.all_properties)


def test_eln_order_keeps_state_slots_together():
    order = Protocol.m_def.m_get_annotations('display').order
    start = order.index(STATE_SLOTS[0])
    assert order[start : start + len(STATE_SLOTS)] == list(STATE_SLOTS)


def test_derived_node_fields_are_not_editable():
    assert Protocol.m_def.all_quantities['duration_s'].m_get_annotations('eln') is None


# --- summary ---------------------------------------------------------------------


def test_summary_quantities_are_scalar_for_search():
    """Only scalar quantities are indexed as search quantities (Design.md §4.3)."""
    quantities = ProtocolSummary.m_def.all_quantities.values()
    assert [q.name for q in quantities if q.shape] == []


def test_summary_is_read_only():
    quantities = ProtocolSummary.m_def.all_quantities.values()
    assert [q.name for q in quantities if q.m_get_annotations('eln')] == []


def test_summary_has_controlled_and_monitored_flag_per_axis():
    names = set(ProtocolSummary.m_def.all_quantities)
    for axis in ('temperature', 'irradiation', 'humidity', 'oxygen', 'electrical_load'):
        assert {f'{axis}_controlled', f'{axis}_monitored'} <= names


@pytest.mark.parametrize(
    'name, unit',
    [
        ('total_duration', 'hour'),
        ('temperature_min', 'kelvin'),
        ('temperature_max', 'kelvin'),
        ('temperature_mean', 'kelvin'),
        ('irradiance_mean', 'watt / meter ** 2'),
    ],
)
def test_summary_units(name, unit):
    assert str(ProtocolSummary.m_def.all_quantities[name].unit) == unit


def test_summary_temperatures_display_in_celsius():
    for name in ('temperature_min', 'temperature_max', 'temperature_mean'):
        quantity = ProtocolSummary.m_def.all_quantities[name]
        assert quantity.m_get_annotations('display')['unit'] == 'degC'


def test_summary_accepts_values():
    summary = ProtocolSummary(
        total_duration=1008,
        temperature_mean=338.15,
        humidity_kind='mixed',
        channels_used='bias, chuck_T, sun',
        n_jv_sweeps=42,
        is_cyclic=True,
    )
    assert summary.total_duration.to('second').magnitude == 1008 * 3600
    assert summary.temperature_mean.to('degC').magnitude == pytest.approx(65)
    assert (summary.humidity_mean, summary.n_jv_sweeps) == (None, 42)


# --- the entry -------------------------------------------------------------------


def test_entry_bases():
    assert issubclass(StabilityProtocol, BaseSection)
    assert issubclass(StabilityProtocol, EntryData)
    assert issubclass(StabilityProtocol, PlotSection)


def test_entry_quantities_follow_the_inherited_ones():
    names = list(StabilityProtocol.m_def.all_quantities)
    assert names[:4] == ['name', 'datetime', 'lab_id', 'description']
    assert names.index('version') > names.index('description')
    assert {'version', 'isos_specification', 'isos_deviations', 'horizon'} <= set(names)


@pytest.mark.parametrize(
    'name, section_type',
    [
        ('channels', Channels),
        ('protocol', Protocol),
        ('timeline', ProtocolTimeline),
        ('summary', ProtocolSummary),
    ],
)
def test_entry_sub_sections(name, section_type):
    sub_section = StabilityProtocol.m_def.all_sub_sections[name]
    assert sub_section.sub_section.section_cls is section_type
    assert not sub_section.repeats


def test_entry_keeps_the_inherited_figures():
    assert StabilityProtocol.m_def.all_sub_sections['figures'].repeats
