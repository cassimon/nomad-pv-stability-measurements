"""A protocol draws its timeline (Design.md §29): values where the protocol states them,
text where it does not, and axis breaks that hide time without moving it."""

from math import inf

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.characterization_instructions import (
    JVScan,
)
from nomad_pv_stability_measurements.schema_packages.general import (
    CountingRepeatingBlock,
    Duration,
    IndefiniteRepeatingBlock,
    InstructionBlock,
    Period,
)
from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldCurrent,
    HoldIrradiance,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.plan_timeline import (
    ASSUMPTION_COLOR,
    OVERHANG,
    axis_sections,
    mark_symbols,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
from nomad_pv_stability_measurements.schema_packages.ramp_instructions import (
    RampTemperature,
)
from nomad_pv_stability_measurements.schema_packages.utils import AxisBreak, PlotPiece

HOUR = 3600
K = ureg.kelvin
SUN = 1000  # W/m²
#: °: a row label reads bottom to top.
UPRIGHT = -90


def whole_block() -> Duration:
    return Duration(kind='whole_block')


def red_notes(layout) -> list[str]:
    return [
        note['text']
        for note in layout['annotations']
        if note['font'].get('color') == ASSUMPTION_COLOR
    ]


def drawn(figure) -> list[dict]:
    """The traces that draw a value or a band: not the empty ones that frame a row,
    nor the areas that only answer hovering."""
    return [
        trace
        for trace in figure['data']
        if trace['y'][0] is not None and trace.get('hoveron') != 'fills'
    ]


def legend(layout) -> str:
    """The legend's text: the roles' colours, then the marks' symbols."""
    return next(
        note['text'] for note in layout['annotations'] if 'controlled' in note['text']
    )


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
    light = HoldIrradiance(
        value=SUN * ureg('W/m^2'),
        duration=Duration(kind='fixed', value=1 * ureg.hour),
    )
    dark = HoldIrradiance(
        value=0 * ureg('W/m^2'),
        duration=Duration(kind='fixed', value=1 * ureg.hour),
    )
    protocol = normalized(
        StabilityProtocol(
            name='light–dark',
            instructions=[
                MPPTracking(duration=Duration(kind='whole_block')),
                IndefiniteRepeatingBlock(sub_instructions=[light, dark]),
            ],
        )
    )

    [timeline] = protocol.figures
    [iteration] = protocol.instructions[1].figures
    layout = timeline.figure['layout']
    texts = [note['text'] for note in layout['annotations']]

    assert timeline.label == 'Timeline'
    # Three cycles, in hours, and a little further: it goes on, and `⋯` says so.
    assert layout['xaxis']['range'] == pytest.approx([0, 6 * (1 + OVERHANG)])
    assert {'MPP', '<b>⋯</b>'} <= set(texts)
    assert 'indefinitely' not in texts
    assert layout['title']['text'] == '<b>light–dark</b>'
    values = [y for trace in drawn(timeline.figure) for y in trace['y']]
    assert max(values) == SUN
    # The routine's own figure, where it is opened: one light–dark cycle.
    assert iteration.figure['layout']['xaxis']['range'] == [0, 2]
    # Irradiance on top, the load at the bottom; 0 W/m² a little above the axis's
    # start, so a line there is drawn whole.
    assert [note['text'] for note in row_labels(layout)] == [
        'irradiance<br>(W/m²)',
        'electrical load',
    ]
    assert -0.1 * SUN < layout['yaxis']['range'][0] < 0


def test_a_block_whose_iteration_never_ends_gets_no_figure_of_its_own(normalized):
    cycling = IndefiniteRepeatingBlock(
        sub_instructions=[MPPTracking(duration=Duration(kind='open_ended'))]
    )
    protocol = normalized(StabilityProtocol(instructions=[cycling]))

    assert [figure.label for figure in protocol.figures] == ['Timeline']
    assert not cycling.figures


def test_bounds_are_a_band_and_a_protocol_without_end_goes_on(normalized):
    protocol = normalized(
        StabilityProtocol(
            instructions=[
                HoldBetweenIrradiance(
                    lower_bound=800 * ureg('W/m^2'),
                    upper_bound=SUN * ureg('W/m^2'),
                    duration=whole_block(),
                )
            ]
        )
    )

    [timeline] = protocol.figures
    fill, lower, upper = drawn(timeline.figure)
    texts = [note['text'] for note in timeline.figure['layout']['annotations']]

    assert (lower['y'], upper['y']) == ([800, 800], [SUN, SUN])
    assert (fill['fill'], min(fill['y']), max(fill['y'])) == ('toself', 800, SUN)
    assert '<b>⋯</b>' in texts


def test_a_value_is_drawn_with_its_tolerance_around_it(normalized):
    room = HoldTemperature(
        value=296.15 * ureg.kelvin,
        tolerance=4 * K,
        duration=whole_block(),
    )
    protocol = normalized(StabilityProtocol(instructions=[room]))

    [timeline] = protocol.figures
    area, value = drawn(timeline.figure)

    assert area['fill'] == 'toself'
    assert (min(area['y']), max(area['y'])) == pytest.approx((19, 27))  # °C
    assert set(value['y']) == {23}


def test_a_pace_the_protocol_does_not_state_is_drawn_dashed_and_said_in_red(
    normalized,
):
    cycling = RampTemperature(
        start_point=296.15 * K,
        end_point=338.15 * K,
        end_of_ramp_behavior='cycle',
        duration=whole_block(),
    )
    protocol = normalized(StabilityProtocol(instructions=[cycling]))

    [timeline] = protocol.figures
    [ramp] = drawn(timeline.figure)
    [said] = (
        note
        for note in timeline.figure['layout']['annotations']
        if note['font'].get('color') == ASSUMPTION_COLOR
    )

    assert ramp['line']['dash'] == 'dash'
    assert said['text'] == 'path and rate not specified: drawn linear at 100 K/h'
    # A few cycles of it: 42 K up and down at 100 K/h, three times.
    assert timeline.figure['layout']['xaxis']['range'][1] > 3 * 2 * 0.42


@pytest.mark.parametrize(
    ('kind', 'about', 'said'),
    [('fixed', '', []), ('typical', '≈ ', ['typically 1 h', 'typically 1 h'])],
)
def test_a_typical_length_is_drawn_as_its_length_and_said_in_red_and_in_the_title(
    normalized, kind, about, said
):
    light = HoldIrradiance(
        value=SUN * ureg('W/m^2'), duration=Duration(kind=kind, value=1 * ureg.hour)
    )
    routine = CountingRepeatingBlock(repeat_n=2, sub_instructions=[light])
    protocol = normalized(StabilityProtocol(name='soak', instructions=[routine]))

    [timeline] = protocol.figures
    [iteration] = routine.figures
    layout = timeline.figure['layout']
    lines = drawn(timeline.figure)

    assert layout['title']['text'] == f'<b>soak · {about}2 h</b>'
    assert iteration.figure['layout']['title']['text'].endswith(f' · {about}1 h</b>')
    # Once per iteration drawn; the line is solid: its values are stated.
    assert red_notes(layout) == said
    assert [line['x'] for line in lines] == [[0, 1], [1, 2]]
    assert all('dash' not in line.get('line', {}) for line in lines)


def one_hour() -> Duration:
    return Duration(kind='fixed', value=1 * ureg.hour)


def one_after_another(*instructions) -> StabilityProtocol:
    return StabilityProtocol(
        instructions=[
            InstructionBlock(
                sub_instruction_execution_mode='sequential',
                sub_instructions=list(instructions),
            )
        ]
    )


def test_every_piece_tells_all_of_itself_where_hovered_even_if_too_narrow_to_write(
    normalized,
):
    brief = HoldCurrent(
        value=0.02 * ureg.ampere,
        control=True,
        duration=Duration(kind='fixed', value=1 * ureg.minute),
    )
    protocol = normalized(
        one_after_another(
            HoldVoltage(
                value=0.8 * ureg.volt,
                control=True,
                duration=Duration(kind='fixed', value=1000 * ureg.hour),
            ),
            brief,
        )
    )
    figure = protocol.figures[0].figure
    written = [note['text'] for note in figure['layout']['annotations']]
    hovered = [t['name'] for t in figure['data'] if t.get('hoveron') == 'fills']

    assert 'Hold current 0.02 A for 1 min' not in written
    assert 'Hold current 0.02 A for 1 min<br>from 1000 h for 1 min' in hovered
    assert 'Hold voltage 0.8 V for 1000 h<br>from 0 s for 1000 h' in hovered


def test_the_electrical_load_is_one_row_whichever_quantity_is_set(normalized):
    protocol = normalized(
        one_after_another(
            VOCTracking(duration=one_hour()),
            HoldVoltage(value=0.8 * ureg.volt, duration=one_hour()),
        )
    )
    layout = protocol.figures[0].figure['layout']

    # The terminals are one port, in one state at a time.
    assert [note['text'] for note in row_labels(layout)] == ['electrical load<br>(V)']


def test_jv_scans_are_marks_over_what_holds_the_load(normalized):
    protocol = normalized(
        StabilityProtocol(
            instructions=[
                MPPTracking(control=True, duration=one_hour()),
                JVScan(
                    duration=whole_block(),
                    interval=Period(kind='fixed', value=30 * ureg.minute),
                ),
            ]
        )
    )
    figure = protocol.figures[0].figure
    [marks] = [trace for trace in figure['data'] if trace['mode'] == 'markers']
    [bar] = figure['layout']['shapes']

    # No row of their own: the scans stand on the load's row, at their moments.
    assert [note['text'] for note in row_labels(figure['layout'])] == [
        'electrical load'
    ]
    assert marks['x'] == [0, 0.5]
    assert marks['yaxis'] == bar['yref'].removesuffix(' domain')
    assert 'at 30 min' in marks['hovertext'][1]
    # The legend says what the diamonds stand for.
    assert '◆</span> J–V scan' in legend(figure['layout'])


def test_each_kind_of_mark_has_its_own_symbol():
    def moment(kind: str) -> PlotPiece:
        return PlotPiece('electrical load', kind, 0, 1, marks=[0], mark_kind=kind)

    symbols = mark_symbols([moment('EQE'), moment('J–V scan'), moment('PL image')])

    # A J–V scan is always a diamond; any other kind takes a symbol still free.
    assert {kind: plotly for kind, (plotly, _) in symbols.items()} == {
        'J–V scan': 'diamond',
        'EQE': 'circle',
        'PL image': 'triangle-up',
    }


def test_values_in_different_units_on_one_row_are_written_not_drawn(normalized):
    protocol = normalized(
        one_after_another(
            VOCTracking(duration=one_hour()),
            HoldVoltage(value=0.8 * ureg.volt, control=True, duration=one_hour()),
            HoldCurrent(value=0.02 * ureg.ampere, control=True, duration=one_hour()),
        )
    )
    figure = protocol.figures[0].figure
    texts = [note['text'] for note in figure['layout']['annotations']]

    # A volt and an ampere share no axis: each is a bar with its label.
    assert not drawn(figure)
    assert {'Hold voltage 0.8 V for 1 h', 'Hold current 0.02 A for 1 h'} <= set(texts)
    assert 'open circuit' in texts  # what had no value keeps its own text
    assert [note['text'] for note in row_labels(figure['layout'])] == [
        'electrical load'
    ]


def test_what_follows_the_load_is_monitored_on_a_thin_row_under_it(normalized):
    protocol = normalized(
        one_after_another(
            HoldVoltage(
                value=0.8 * ureg.volt, control=True, monitor=True, duration=one_hour()
            ),
            VOCTracking(duration=one_hour()),
        )
    )
    series = protocol.time_series_for_plotting()
    monitored = [piece for piece in series.pieces if piece.role == 'monitored']

    # Only while `monitor` is set; a row without a label of its own.
    assert [(piece.row, piece.text, piece.end) for piece in monitored] == [
        ('electrical load, monitored', 'monitored: current', HOUR)
    ]
    layout = protocol.figures[0].figure['layout']
    assert [note['text'] for note in row_labels(layout)] == ['electrical load<br>(V)']


def test_bars_side_by_side_stay_apart_and_a_row_shares_its_text_size(normalized):
    protocol = normalized(
        one_after_another(
            VOCTracking(monitor=True, duration=one_hour()),
            HoldVoltage(reference_point='V_MPP', monitor=True, duration=one_hour()),
        )
    )
    layout = protocol.figures[0].figure['layout']
    bars = sorted(
        (shape['yref'], shape['x0'], shape['x1']) for shape in layout['shapes']
    )
    sizes = {
        note['font']['size']
        for note in layout['annotations']
        if note['text'].startswith(('open circuit', 'V<sub>MPP</sub>', 'monitored:'))
    }

    # Each bar of a row ends before the next one starts.
    for (row, _, end), (next_row, start, _) in zip(bars, bars[1:]):
        assert row != next_row or end < start
    # The electrical load and its monitored row write at one size.
    assert len(sizes) == 1
