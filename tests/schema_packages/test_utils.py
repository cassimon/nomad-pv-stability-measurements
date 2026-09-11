from nomad_pv_stability_measurements.schema_packages.routine import ChannelCommand
from nomad_pv_stability_measurements.schema_packages.utils import with_m_def


def test_with_m_def_names_the_given_class():
    entry = with_m_def({'channel': 'temperature'}, ChannelCommand)

    assert entry['m_def'] == f'{ChannelCommand.__module__}.ChannelCommand'
    assert entry['channel'] == 'temperature'


def test_with_m_def_leaves_an_authored_m_def_alone():
    # e.g. a round-tripped archive already names its own class.
    entry = {'channel': 'temperature', 'm_def': 'some.other.Class'}

    assert with_m_def(entry, ChannelCommand) is entry


def test_with_m_def_leaves_a_built_section_alone():
    # Not every entry is a dict — one already built (e.g. via the Python API)
    # passes straight through.
    section = ChannelCommand(channel='temperature')

    assert with_m_def(section, ChannelCommand) is section
