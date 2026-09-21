"""A protocol draws its timeline (Design.md §29): values where the protocol states them,
text where it does not, and axis breaks that hide time without moving it."""

from math import inf

from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    IndefiniteRepeatingBlock,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import MPPTracking
from nomad_pv_stability_measurements.schema_packages.plan_timeline import axis_sections
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
from nomad_pv_stability_measurements.schema_packages.utils import AxisBreak

HOUR = 3600
SUN = 1000  # W/m²


def test_breaks_cut_the_axis_into_sections_at_their_true_times():
    breaks = [AxisBreak(3 * HOUR, 300 * HOUR, 'n=300 repetitions')]

    assert axis_sections(310 * HOUR, breaks) == (
        [(0, 3 * HOUR), (300 * HOUR, 310 * HOUR)],
        ['n=300 repetitions'],
    )
    # One that never ends closes the axis.
    assert axis_sections(3 * HOUR, [AxisBreak(3 * HOUR, inf, 'indefinitely')]) == (
        [(0, 3 * HOUR)],
        ['indefinitely'],
    )


def test_a_protocol_shows_its_timeline(normalized):
    light = HoldIrradiance(set_point=SUN * ureg('W/m^2'), duration=1 * ureg.hour)
    dark = HoldIrradiance(set_point=0 * ureg('W/m^2'), duration=1 * ureg.hour)
    protocol = normalized(
        StabilityProtocol(
            name='light–dark',
            instructions=[
                MPPTracking(),
                IndefiniteRepeatingBlock(sub_instructions=[light, dark]),
            ],
        )
    )

    [timeline] = protocol.figures
    layout = timeline.figure['layout']
    texts = [note['text'] for note in layout['annotations']]

    assert timeline.label == 'Timeline'
    assert layout['xaxis']['range'] == [0, 6]  # three cycles, in hours
    assert {'MPP', 'indefinitely'} <= set(texts)
    values = [
        y for trace in timeline.figure['data'] for y in trace['y'] if y is not None
    ]
    assert max(values) == SUN
