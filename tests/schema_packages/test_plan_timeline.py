"""A protocol draws its timeline (Design.md §29): values where the protocol states them,
text where it does not, and axis breaks that hide time without moving it."""

from math import inf

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    IndefiniteRepeatingBlock,
)
from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldIrradiance,
    HoldTemperature,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import MPPTracking
from nomad_pv_stability_measurements.schema_packages.plan_timeline import (
    ASSUMPTION_COLOR,
    OVERHANG,
    axis_sections,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
from nomad_pv_stability_measurements.schema_packages.ramp_instructions import (
    RampTemperature,
)
from nomad_pv_stability_measurements.schema_packages.utils import AxisBreak

HOUR = 3600
K = ureg.kelvin
SUN = 1000  # W/m²
#: °: a row label reads bottom to top.
UPRIGHT = -90


def row_labels(layout) -> list[dict]:
    """The row labels, top to bottom: turned on their side, left of the rows."""
    labels = [
        note for note in layout['annotations'] if note.get('textangle') == UPRIGHT
    ]
    return sorted(labels, key=lambda note: -note['y'])


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

    timeline, iteration = protocol.figures
    layout = timeline.figure['layout']
    texts = [note['text'] for note in layout['annotations']]

    assert timeline.label == 'Timeline'
    # Three cycles, in hours, and a little further: it goes on, and `⋯` says so.
    assert layout['xaxis']['range'] == pytest.approx([0, 6 * (1 + OVERHANG)])
    assert {'MPP', '<b>⋯</b>'} <= set(texts)
    assert 'indefinitely' not in texts
    assert layout['title']['text'] == '<b>light–dark</b>'
    values = [
        y for trace in timeline.figure['data'] for y in trace['y'] if y is not None
    ]
    assert max(values) == SUN
    # The routine's own figure: one light–dark cycle.
    assert iteration.figure['layout']['xaxis']['range'] == [0, 2]
    # Irradiance on top, the load at the bottom; 0 W/m² a little above the axis's
    # start, so a line there is drawn whole.
    assert [note['text'] for note in row_labels(layout)] == [
        'irradiance<br>(W/m²)',
        'electrical load',
    ]
    assert -0.1 * SUN < layout['yaxis']['range'][0] < 0


def test_a_block_whose_iteration_never_ends_gets_no_figure_of_its_own(normalized):
    cycling = IndefiniteRepeatingBlock(sub_instructions=[MPPTracking()])
    protocol = normalized(StabilityProtocol(instructions=[cycling]))

    assert [figure.label for figure in protocol.figures] == ['Timeline']


def test_bounds_are_a_band_and_a_protocol_without_end_goes_on(normalized):
    protocol = normalized(
        StabilityProtocol(
            instructions=[
                HoldBetweenIrradiance(
                    lower_bound=800 * ureg('W/m^2'), upper_bound=SUN * ureg('W/m^2')
                )
            ]
        )
    )

    [timeline] = protocol.figures
    fill, lower, upper = (t for t in timeline.figure['data'] if t['y'][0] is not None)
    texts = [note['text'] for note in timeline.figure['layout']['annotations']]

    assert (lower['y'], upper['y']) == ([800, 800], [SUN, SUN])
    assert (fill['fill'], min(fill['y']), max(fill['y'])) == ('toself', 800, SUN)
    assert '<b>⋯</b>' in texts


def test_a_set_point_is_drawn_with_its_tolerance_around_it(normalized):
    room = HoldTemperature(set_point=296.15 * ureg.kelvin, set_point_tolerance=4 * K)
    protocol = normalized(StabilityProtocol(instructions=[room]))

    [timeline] = protocol.figures
    area, value = (t for t in timeline.figure['data'] if t['y'][0] is not None)

    assert area['fill'] == 'toself'
    assert (min(area['y']), max(area['y'])) == pytest.approx((19, 27))  # °C
    assert set(value['y']) == {23}


def test_a_pace_the_protocol_does_not_state_is_drawn_dashed_and_said_in_red(
    normalized,
):
    cycling = RampTemperature(
        start_point=296.15 * K, end_point=338.15 * K, end_of_ramp_behavior='cycle'
    )
    protocol = normalized(StabilityProtocol(instructions=[cycling]))

    [timeline] = protocol.figures
    [ramp] = (t for t in timeline.figure['data'] if t['y'][0] is not None)
    [said] = (
        note
        for note in timeline.figure['layout']['annotations']
        if note['font'].get('color') == ASSUMPTION_COLOR
    )

    assert ramp['line']['dash'] == 'dash'
    assert said['text'] == 'path and rate not specified: drawn linear at 100 K/h'
    # A few cycles of it: 42 K up and down at 100 K/h, three times.
    assert timeline.figure['layout']['xaxis']['range'][1] > 3 * 2 * 0.42
