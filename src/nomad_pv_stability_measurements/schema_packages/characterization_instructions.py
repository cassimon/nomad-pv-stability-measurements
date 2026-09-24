"""Instructions that characterize the cell during a test, rather than hold a condition."""

from math import inf

import numpy as np
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    NOT_STATED,
    TYPICAL,
    Period,
    SingleInstruction,
)
from nomad_pv_stability_measurements.schema_packages.light_sources import LightSource
from nomad_pv_stability_measurements.schema_packages.utils import shown

m_package = SchemaPackage()

#: How many scans are drawn where the plan repeats them without saying how often:
#: evenly over the stretch they are taken in. Only for the drawing, which says so.
MARKS_FOR_PLOTTING = 4


class JVScan(SingleInstruction):
    """J–V scans taken over the instruction's duration, one every `interval`: the
    voltage swept as set, the current recorded. Without an `interval`, one scan at the
    start. An interval `not_stated` scans periodically, as often as whoever runs the
    test chooses.

    A standard writes it as "J–V every x". How long one scan takes is rarely known, so
    it is no part of the plan: the duration is the stretch the scans are taken over,
    usually the whole block they run beside.
    """

    interval = SubSection(
        section_def=Period,
        description='The time from one scan to the next, and what kind of time it is: '
        'fixed, typical, or not stated where the test only says the scans repeat.',
    )
    voltage_start = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage a forward scan starts from, the lower end of the range.',
    )
    voltage_stop = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage a forward scan ends at, the upper end of the range.',
    )
    voltage_step = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage between two points of a scan.',
    )
    scan_rate = Quantity(
        type=np.float64,
        unit='V/s',
        description='How fast the voltage is swept.',
    )
    scan_order = Quantity(
        type=MEnum(
            'forward', 'reverse', 'forward then reverse', 'reverse then forward'
        ),
        description='Which scans each J–V takes, in the order taken.',
    )
    irradiance = Quantity(
        type=np.float64,
        unit='W/m^2',
        description='The light the scans are measured under; 1000 W/m² is one sun.',
    )
    light_source = SubSection(
        section_def=LightSource,
        description='Where the light the scans are measured under comes from: often '
        'another source than the one the cell ages under.',
    )

    def describe(self) -> str:
        """`J–V scan every 10 min at 1000 W/m² (xenon lamp, AM1.5G)`: how often, and
        the light it is measured under."""
        said = 'J–V scan' + self.describe_interval()
        if self.irradiance is not None:
            said += f' at {shown(self.irradiance)}'
        if self.light_source is not None:
            said += f' ({self.light_source.describe()})'
        return said

    def describe_interval(self) -> str:
        """` every 10 min`, ` every ≈ 1 h` where it is only typical, ` periodically`
        where it is not stated; nothing for one scan."""
        interval = self.interval
        if interval is None:
            return ''
        if interval.kind == NOT_STATED:
            return ' periodically'
        if interval.value is None:
            return ''
        typically = '≈ ' if interval.kind == TYPICAL else ''
        return f' every {typically}{shown(interval.value.to(ureg.second))}'

    def time_series_for_plotting(self, start: float, stop: float):
        """Each scan a mark at the moment it is taken, not a stretch: one at the start,
        or one every `interval`."""
        series = super().time_series_for_plotting(start, stop)
        for piece in series.pieces:
            piece.text = None
            piece.marks, piece.assumption = self.marks_for_plotting(
                piece.start, piece.end
            )
        return series

    def marks_for_plotting(self, start: float, end: float):
        """`(times, assumption)`: when the scans are taken between `start` and `end`, in
        seconds, and what the drawing assumes. Where the interval is not stated, a few
        are drawn evenly, and the drawing says so; where nothing ends the drawing yet,
        only the first, since only the extent is needed."""
        interval = self.interval
        if interval is None or end == inf:
            return np.array([start]), None
        if interval.kind == NOT_STATED or interval.value is None:
            times = np.linspace(start, end, MARKS_FOR_PLOTTING, endpoint=False)
            return times, f'interval not stated: drawn {MARKS_FOR_PLOTTING} times'
        return np.arange(start, end, interval.value.to('s').magnitude), None

    def row_for_plotting(self) -> str:
        """The electrical load's: a scan takes the cell's terminals, whatever else
        holds them, so it is drawn over what the load does."""
        return 'electrical load'

    def role_for_plotting(self) -> str:
        """Monitored: a scan measures the cell, and regulates no condition."""
        return 'monitored'


m_package.__init_metainfo__()
