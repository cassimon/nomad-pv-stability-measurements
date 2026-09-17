"""Every row of ISOS Table 1, as the example uploads the plugin ships (Design.md §16).

Each protocol is asserted field by field — the class of every step, what it holds in its
own unit, and what it deliberately leaves empty — rather than only that the file parses.
What must hold for *all* of them is three parametrized passes: no translation problem,
nothing reported by `normalize()`, a bare archive that reads back as itself (§13.1a), and
no timing figure the standard never states (§16.2, Rule 1).

The files are read from the package, not from `tests/data/`: they are shipped
documentation, and a second copy would be a second thing to keep in step.
"""

from pathlib import Path

import pytest
import yaml
from nomad.datamodel import EntryArchive, EntryMetadata
from nomad.units import ureg

from nomad_pv_stability_measurements import example_uploads
from nomad_pv_stability_measurements.parsers.translate import translate
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldIrradiance,
    HoldTemperature,
    HoldWaterVaporFraction,
)
from nomad_pv_stability_measurements.schema_packages.mpp_steps import VOCTracking
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol

EXAMPLES = Path(example_uploads.__file__).parent / 'isos'
IRRADIANCE = ureg.watt / ureg.meter**2
#: Every shipped protocol, so a new file joins the shared passes the moment it lands.
SHIPPED = sorted(path.name for path in EXAMPLES.glob('*.stability.yaml'))
#: The pair every monitor/control step carries, and that no row of the table states.
SAMPLING = ('sample_every', 'sampling_rate')


def read(name: str) -> dict:
    with open(EXAMPLES / name) as file:
        return yaml.safe_load(file)


def magnitude(value, unit):
    return value.to(unit).magnitude


@pytest.fixture
def protocol(normalized, log):
    """One shipped file, translated, loaded and normalized — asserted clean on the way
    through, because a typo in an example upload is a bug in the documentation."""

    def run(name: str) -> StabilityProtocol:
        translation = translate(read(name))
        assert [(p.path, p.message) for p in translation.problems] == []
        loaded = StabilityProtocol.m_from_dict(translation.archive['data'])
        for step in loaded.steps:
            normalized(step)
        metadata = EntryMetadata(entry_name=name)
        loaded.normalize(EntryArchive(metadata=metadata, data=loaded), log)
        assert (log.errors, log.warnings) == ([], [])
        return loaded

    return run


# What holds for every file in the set.


@pytest.mark.parametrize('name', SHIPPED)
def test_a_shipped_protocol_translates_loads_and_normalizes(name, protocol):
    # The fixture carries the three assertions; this runs it over each file, and checks
    # the one invariant tying a file to its row of the table.
    assert protocol(name).standard == name.removesuffix('.stability.yaml')


@pytest.mark.parametrize('name', SHIPPED)
def test_a_shipped_protocol_round_trips(name):
    # The bare format is a subset of the authored one, so translating it again is a
    # no-op — which is what NOMAD does every time it writes an entry back (§13.1a).
    bare = translate(read(name)).archive
    again = translate(bare)

    assert (again.archive, again.problems) == (bare, [])


@pytest.mark.parametrize('name', SHIPPED)
def test_a_shipped_protocol_invents_no_sampling_interval(name, protocol):
    # Rule 1 (§16.2): ISOS Table 1 states a sampling interval for no row, so no file may
    # write one. An example upload is read as a template, and a plausible figure the
    # standard never states manufactures a requirement out of nothing.
    for step in protocol(name).m_all_contents(depth_first=True):
        for written in SAMPLING:
            assert getattr(step, written, None) is None


# ISOS-D — dark storage (Table 1, rows 1-3). Every condition is constant, so all three
# are `channel_settings` and nothing else: no routine, and no duration (§16.2, Rule 2).


def test_isos_d_1(protocol):
    isos = protocol('ISOS-D-1.stability.yaml')

    assert (isos.standard, isos.environment) == ('ISOS-D-1', 'indoor')
    assert isos.name == 'ISOS-D-1'  # the table's designation, and no invented title
    # Indoors, so no coordinates: the site is not part of this result (§15.12).
    assert isos.geo_location is None
    # The standard fixes no test duration, so the protocol has none to derive from.
    assert isos.estimated_duration is None
    dark, temperature, water, load = isos.steps

    # Dark on purpose, and counted: a value, not a missing one (D8a).
    assert isinstance(dark, HoldIrradiance)
    assert magnitude(dark.setpoint, IRRADIANCE) == pytest.approx(0)
    assert (dark.control, dark.monitor) == (True, None)

    # "Ambient" says one thing only — not regulated. No setpoint, and no claim that
    # anyone is logging it, which the table never asks for (§16.2, Rule 1).
    assert isinstance(temperature, HoldTemperature)
    assert (temperature.setpoint, temperature.control, temperature.monitor) == (
        None,
        False,
        None,
    )
    # A condition: without a duration it lasts as long as the run does (D13).
    assert temperature.estimated_duration is None

    assert isinstance(water, HoldWaterVaporFraction)
    assert (water.setpoint, water.control, water.monitor) == (None, False, None)

    # The cell sits at open circuit throughout, which is a constant like the others.
    assert (type(load), load.control) == (VOCTracking, True)
    assert load.estimated_duration is None


def test_isos_d_2(protocol):
    isos = protocol('ISOS-D-2.stability.yaml')

    assert (isos.standard, isos.environment) == ('ISOS-D-2', 'indoor')
    # The level this file does not take is named, so the other run is one line away.
    assert '85' in isos.notes
    assert isos.estimated_duration is None
    dark, temperature, water, load = isos.steps

    assert magnitude(dark.setpoint, IRRADIANCE) == pytest.approx(0)

    # An oven holds a temperature, so this one is controlled — the table states it.
    assert isinstance(temperature, HoldTemperature)
    assert magnitude(temperature.setpoint, ureg.degC) == pytest.approx(65)
    assert temperature.control is True

    # The air in the oven is whatever it is.
    assert isinstance(water, HoldWaterVaporFraction)
    assert (water.setpoint, water.control) == (None, False)

    assert (type(load), load.control) == (VOCTracking, True)


def test_isos_d_3(protocol):
    isos = protocol('ISOS-D-3.stability.yaml')

    assert (isos.standard, isos.environment) == ('ISOS-D-3', 'indoor')
    assert isos.estimated_duration is None
    dark, temperature, water, load = isos.steps

    assert magnitude(dark.setpoint, IRRADIANCE) == pytest.approx(0)
    assert magnitude(temperature.setpoint, ureg.degC) == pytest.approx(65)
    assert temperature.control is True

    # The chamber holds the humidity too. It is written the way the table prints it,
    # `{rh: 85 %, at: 65 °C}`, and stored as the absolute volume ratio that pair works
    # out to — a fifth of the atmosphere by volume (§15.16).
    assert isinstance(water, HoldWaterVaporFraction)
    assert water.setpoint.magnitude == pytest.approx(0.2109, rel=1e-3)
    assert water.control is True

    assert (type(load), load.control) == (VOCTracking, True)
