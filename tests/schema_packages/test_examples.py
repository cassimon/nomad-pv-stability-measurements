"""The two worked examples of Design.md §8, processed by NOMAD."""

from nomad_pv_stability_measurements.schema_packages.channels import (
    AtmosphereChannel,
    ElectricalLoadChannel,
    IrradiationChannel,
    TemperatureChannel,
)
from nomad_pv_stability_measurements.schema_packages.protocol import (
    StabilityProtocol,
    State,
)
from nomad_pv_stability_measurements.schema_packages.states import Sweep


def test_isos_l2(load_example):
    archive = load_example('isos_l2.archive.yaml')
    data = archive.data

    assert isinstance(data, StabilityProtocol)
    assert data.isos_specification == 'ISOS-L-2'
    assert archive.metadata.entry_name == data.name  # set by BaseSection

    channels = data.channels
    (chuck,) = channels.temperature
    assert isinstance(chuck, TemperatureChannel)
    assert chuck.limits == ['20 °C', '90 °C']
    assert chuck.regulation.kind == 'pid'
    assert isinstance(channels.irradiation[0], IrradiationChannel)
    assert channels.irradiation[0].spectrum == 'AM1.5G'
    assert isinstance(channels.electrical_load[0], ElectricalLoadChannel)
    assert channels.atmosphere == []  # implicit: never written into the channels
    assert [c.key for c in channels.iter_channels()] == ['chuck_T', 'sun', 'bias']

    root = data.protocol
    assert (root.name, root.mode) == ('light soak', 'parallel')
    assert root.state is None
    hold_t, hold_sun, daily = root.steps
    assert (hold_t.channel, hold_t.state) == ('chuck_T', State('hold', '65 °C'))
    assert (hold_sun.channel, hold_sun.state) == ('sun', State('hold', '1 sun'))

    assert daily.subprotocol == 'daily cycle'
    assert daily.repetitions == '42'
    assert daily.mode == 'sequential'
    mpp, jv = daily.steps
    assert mpp.state == State('track', 'mpp')
    assert mpp.duration == '24 h'
    assert jv.variable == 'voltage'
    assert isinstance(jv.state.value, Sweep)
    assert (jv.sweep.from_, jv.sweep.to) == ('-0.2 V', '1.3 V')
    assert (jv.sweep.rate, jv.sweep.direction) == ('50 mV/s', 'both')


def test_isos_d3(load_example):
    data = load_example('isos_d3.archive.yaml').data

    assert data.horizon == '1000 h'
    (air,) = data.channels.atmosphere
    assert isinstance(air, AtmosphereChannel)
    assert air.balance_gas == 'air'
    assert data.channels.electrical_load == []

    oven_t, humidity, dark = data.protocol.steps
    assert oven_t.state == State('hold', '85 °C')
    assert (humidity.variable, humidity.state) == ('humidity', State('hold', '85 %RH'))
    assert (dark.channel, dark.state) == ('oven_dark', State('off', True))


def test_channels_are_normalized(load_example):
    channels = load_example('isos_d3.archive.yaml').data.channels

    (oven_t,) = channels.temperature
    assert oven_t.variables == ['temperature']
    assert oven_t.is_monitored is True
    (dark,) = channels.irradiation
    assert dark.variables == ['irradiance']
    assert dark.is_monitored is False
    assert channels.atmosphere[0].variables == ['humidity', 'oxygen', 'total_pressure']


def test_examples_round_trip(load_example):
    for filename in ('isos_l2.archive.yaml', 'isos_d3.archive.yaml'):
        data = load_example(filename).data
        serialized = data.m_to_dict()
        serialized.pop('m_def')  # written because `data` is typed EntryData
        again = StabilityProtocol.m_from_dict(serialized)
        assert again.m_to_dict() == serialized
