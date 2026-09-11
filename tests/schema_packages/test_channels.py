import pytest
import yaml

from nomad_pv_stability_measurements.schema_packages.channels import (
    DEFAULT_KIND,
    HUMIDITY_KINDS,
    OXYGEN_KINDS,
    AtmosphereChannel,
    Channel,
    Channels,
    ElectricalLoadChannel,
    IrradiationChannel,
    Kind,
    MechanicalChannel,
    TemperatureChannel,
    Variable,
)
from nomad_pv_stability_measurements.schema_packages.states import GENERIC_STATES

CHANNEL_TYPES = [
    TemperatureChannel,
    IrradiationChannel,
    AtmosphereChannel,
    ElectricalLoadChannel,
    MechanicalChannel,
]


# --- Variable and Kind -----------------------------------------------------------


def test_variable_unit_shorthand_is_one_default_kind():
    variable = Variable('K', display='degC')
    assert variable.kinds == (Kind(DEFAULT_KIND, 'K'),)
    assert variable.kind_names == (DEFAULT_KIND,)
    assert variable.display == 'degC'


def test_variable_defaults_to_controllable_and_monitorable():
    variable = Variable('V')
    assert variable.control and variable.monitor


def test_variable_keeps_explicit_kinds():
    variable = Variable(HUMIDITY_KINDS)
    assert variable.kinds is HUMIDITY_KINDS
    assert variable.kind('dew_point') == Kind('dew_point', 'K')


def test_variable_unknown_kind_names_the_options():
    with pytest.raises(KeyError, match='relative'):
        Variable(HUMIDITY_KINDS).kind('volumetric')


def test_variable_needs_a_kind():
    with pytest.raises(ValueError):
        Variable(())


def test_variable_is_immutable():
    with pytest.raises(AttributeError):
        Variable('K').display = 'degF'


@pytest.mark.parametrize(
    'kinds, expected',
    [
        (
            HUMIDITY_KINDS,
            {
                'relative': 'dimensionless',
                'molar_ratio': 'mol/mol',
                'mass_ratio': 'kg/kg',
                'absolute': 'kg/m^3',
                'dew_point': 'K',
                'partial_pressure': 'Pa',
            },
        ),
        (
            OXYGEN_KINDS,
            {
                'molar_ratio': 'mol/mol',
                'mass_ratio': 'kg/kg',
                'partial_pressure': 'Pa',
            },
        ),
    ],
    ids=['humidity', 'oxygen'],
)
def test_kind_tables(kinds, expected):
    assert {kind.name: kind.unit for kind in kinds} == expected


# --- the per-type tables ---------------------------------------------------------


@pytest.mark.parametrize(
    'channel_type, variables, groups, extra_states, always_reported',
    [
        (TemperatureChannel, ['temperature'], [{'temperature'}], set(), True),
        (IrradiationChannel, ['irradiance'], [{'irradiance'}], {'off'}, True),
        (
            AtmosphereChannel,
            ['humidity', 'oxygen', 'total_pressure'],
            [{'humidity'}, {'oxygen'}, {'total_pressure'}],
            set(),
            True,
        ),
        (
            ElectricalLoadChannel,
            ['voltage', 'current', 'resistance'],
            [{'voltage', 'current', 'resistance'}],
            {'track', 'sweep'},
            True,
        ),
        (
            MechanicalChannel,
            ['bend_radius', 'strain'],
            [{'bend_radius', 'strain'}],
            set(),
            False,
        ),
    ],
)
def test_channel_table(channel_type, variables, groups, extra_states, always_reported):
    assert list(channel_type.variable_table) == variables
    assert [set(group) for group in channel_type.control_groups] == groups
    assert channel_type.accepted_states == GENERIC_STATES | extra_states
    assert channel_type.always_reported is always_reported


@pytest.mark.parametrize(
    'channel_type, variable, canonical, display',
    [
        (TemperatureChannel, 'temperature', 'K', 'degC'),
        (IrradiationChannel, 'irradiance', 'W/m^2', 'W/m^2'),
        (AtmosphereChannel, 'total_pressure', 'Pa', 'mbar'),
        (ElectricalLoadChannel, 'voltage', 'V', None),
        (ElectricalLoadChannel, 'current', 'A', None),
        (ElectricalLoadChannel, 'resistance', 'ohm', None),
        (MechanicalChannel, 'bend_radius', 'm', 'mm'),
        (MechanicalChannel, 'strain', 'dimensionless', '%'),
    ],
)
def test_single_kind_variable_units(channel_type, variable, canonical, display):
    spec = channel_type.variable_table[variable]
    assert spec.kinds == (Kind(DEFAULT_KIND, canonical),)
    assert spec.display == display


def test_atmosphere_variables_are_multi_kind():
    table = AtmosphereChannel.variable_table
    assert table['humidity'].kinds == HUMIDITY_KINDS
    assert table['oxygen'].kinds == OXYGEN_KINDS


@pytest.mark.parametrize('channel_type', CHANNEL_TYPES)
def test_control_groups_partition_the_controllable_variables(channel_type):
    grouped = [name for group in channel_type.control_groups for name in group]
    assert len(grouped) == len(set(grouped)), 'a variable is in two groups'
    assert set(grouped) == set(channel_type.controllable_variables())


@pytest.mark.parametrize('channel_type', CHANNEL_TYPES)
def test_accepts_every_generic_state(channel_type):
    assert channel_type.accepted_states >= GENERIC_STATES


def test_off_is_irradiation_only():
    accepting_off = [t for t in CHANNEL_TYPES if 'off' in t.accepted_states]
    assert accepting_off == [IrradiationChannel]


def test_the_four_isos_axes_are_always_reported():
    assert {t for t in CHANNEL_TYPES if t.always_reported} == {
        TemperatureChannel,
        IrradiationChannel,
        AtmosphereChannel,
        ElectricalLoadChannel,
    }


def test_base_channel_has_an_empty_table():
    assert Channel.variable_table == {}
    assert Channel.control_groups == ()
    assert not Channel.always_reported


# --- base-class interface --------------------------------------------------------


def test_resistance_is_control_only():
    assert ElectricalLoadChannel.can_control('resistance')
    assert not ElectricalLoadChannel.can_monitor('resistance')
    assert ElectricalLoadChannel.monitorable_variables() == ('voltage', 'current')


def test_unknown_variable_can_neither_be_controlled_nor_monitored():
    assert not TemperatureChannel.can_control('humidity')
    assert not TemperatureChannel.can_monitor('humidity')


def test_voltage_and_current_share_a_control_group():
    group = ElectricalLoadChannel.group_of('voltage')
    assert group == ElectricalLoadChannel.group_of('current')
    assert group == {'voltage', 'current', 'resistance'}


def test_humidity_and_oxygen_are_independent():
    assert AtmosphereChannel.group_of('humidity') == {'humidity'}
    assert AtmosphereChannel.group_of('oxygen') == {'oxygen'}


def test_group_of_unknown_variable_names_the_options():
    with pytest.raises(KeyError, match="'humidity'.*'temperature'"):
        TemperatureChannel.group_of('humidity')


def test_interface_works_on_instances():
    channel = AtmosphereChannel(key='chamber')
    assert channel.can_control('humidity')
    assert channel.group_of('oxygen') == {'oxygen'}


def test_not_monitored_without_interval():
    channel = AtmosphereChannel(key='chamber', monitored=['humidity'])
    assert channel.monitored_variables() == ()


def test_monitors_all_monitorable_variables_by_default():
    channel = ElectricalLoadChannel(key='bias', monitor_every='60 s')
    assert channel.monitored_variables() == ('voltage', 'current')


def test_monitors_the_listed_variables():
    channel = AtmosphereChannel(
        key='chamber', monitor_every='10 min', monitored=['humidity']
    )
    assert channel.monitored_variables() == ('humidity',)


# --- metainfo --------------------------------------------------------------------


def test_idle_defaults_to_uncontrolled():
    assert TemperatureChannel(key='chuck_T').idle == 'uncontrolled'


def test_idle_rejects_unknown_states():
    with pytest.raises(ValueError):
        TemperatureChannel(key='chuck_T', idle='hold')


def test_idle_off_survives_yaml_1_1():
    """PyYAML reads the bare value `off` as False."""
    data = yaml.safe_load('{key: sun, idle: off}')
    assert data['idle'] is False
    assert IrradiationChannel.m_from_dict(data).idle == 'off'


@pytest.mark.parametrize(
    'limits',
    [
        ['20 °C', '90 °C'],
        {'humidity': ['10 %RH', '90 %RH'], 'oxygen': ['0 ppm', '1 ppm']},
    ],
    ids=['single-variable', 'per-variable'],
)
def test_limits_accept_both_forms(limits):
    channel = Channel.m_from_dict({'key': 'c', 'limits': limits})
    assert channel.limits == limits
    assert Channel.m_from_dict(channel.m_to_dict()).limits == limits


def test_channel_extra_fields_from_dict():
    sun = IrradiationChannel.m_from_dict({'key': 'sun', 'spectrum': 'AM1.5G'})
    air = AtmosphereChannel.m_from_dict({'key': 'air', 'balance_gas': 'N2'})
    assert sun.spectrum == 'AM1.5G'
    assert air.balance_gas == 'N2'


def test_regulation_and_instrument():
    channel = TemperatureChannel.m_from_dict(
        {
            'key': 'chuck_T',
            'regulation': {'kind': 'pid', 'kp': 2.0, 'ki': 0.1},
            'instrument': {'name': 'Peltier stage'},
        }
    )
    assert channel.regulation.kind == 'pid'
    assert (channel.regulation.kp, channel.regulation.ki) == (2.0, 0.1)
    assert channel.regulation.kd is None
    assert channel.instrument.name == 'Peltier stage'


def test_regulation_kind_is_an_enum():
    with pytest.raises(ValueError):
        TemperatureChannel.m_from_dict({'regulation': {'kind': 'fuzzy'}})


@pytest.mark.parametrize('name', ['variables', 'is_controlled', 'is_monitored'])
def test_derived_quantities_are_not_editable(name):
    assert Channel.m_def.all_quantities[name].m_get_annotations('eln') is None


def test_normalize_derives_variables_and_monitoring(logger):
    monitored = AtmosphereChannel(key='chamber', monitor_every='10 min')
    unmonitored = TemperatureChannel(key='chuck_T')
    for _ in range(2):  # idempotent
        monitored.normalize(None, logger)
        unmonitored.normalize(None, logger)

    assert monitored.variables == ['humidity', 'oxygen', 'total_pressure']
    assert monitored.is_monitored is True
    assert unmonitored.variables == ['temperature']
    assert unmonitored.is_monitored is False
    assert monitored.is_controlled is None  # set from the protocol tree


# --- container -------------------------------------------------------------------


def test_container_has_one_slot_per_channel_type():
    assert Channels.slot_types() == {
        'temperature': TemperatureChannel,
        'irradiation': IrradiationChannel,
        'atmosphere': AtmosphereChannel,
        'electrical_load': ElectricalLoadChannel,
        'mechanical': MechanicalChannel,
    }


def test_container_loads_typed_channels_without_m_def():
    channels = Channels.m_from_dict(
        {
            'temperature': [{'key': 'chuck_T'}, {'key': 'ambient_T'}],
            'electrical_load': [{'key': 'bias'}],
        }
    )
    assert [type(c) for c in channels.temperature] == [TemperatureChannel] * 2
    assert isinstance(channels.electrical_load[0], ElectricalLoadChannel)
    assert channels.atmosphere == []


def test_iter_channels_goes_slot_by_slot():
    channels = Channels.m_from_dict(
        {
            'electrical_load': [{'key': 'bias'}],
            'temperature': [{'key': 'chuck_T'}, {'key': 'ambient_T'}],
            'irradiation': [{'key': 'sun'}],
        }
    )
    assert [c.key for c in channels.iter_channels()] == [
        'chuck_T',
        'ambient_T',
        'sun',
        'bias',
    ]
