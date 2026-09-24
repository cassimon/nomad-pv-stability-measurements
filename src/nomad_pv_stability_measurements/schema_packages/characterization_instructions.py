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

#: How many measurements are drawn where the plan repeats them without saying how often:
#: evenly over the stretch they are taken in. Only for the drawing, which says so.
MARKS_FOR_PLOTTING = 4


class CharacterizationInstruction(SingleInstruction):
    """A measurement of the cell taken during a test, rather than a condition held: at
    the start of the instruction, or once every `interval` over its duration. An
    interval `not_stated` measures periodically, as often as whoever runs the test
    chooses. How long one measurement takes is rarely known, so it is no part of the
    plan: the duration is the stretch the measurements are taken over, usually the
    whole block they run beside.

    Each kind of measurement is a subclass, naming itself in `technique`. Each
    measurement is drawn as a mark at its moment, on the row of what it interrupts, and
    the figure's legend says what the mark stands for.
    """

    #: What the measurement is, in words: `J–V scan`. It names the instruction, and
    #: its marks in the legend.
    technique = ''

    interval = SubSection(
        section_def=Period,
        description='The time from one measurement to the next, and what kind of time '
        'it is: fixed, typical, or not stated where the test only says the '
        'measurements repeat.',
    )

    def describe(self) -> str:
        """`J–V scan every 10 min`, and what the kind of measurement adds."""
        return self.technique + self.describe_interval() + self.describe_settings()

    def describe_interval(self) -> str:
        """` every 10 min`, ` every ≈ 1 h` where it is only typical, ` periodically`
        where it is not stated; nothing for one measurement."""
        interval = self.interval
        if interval is None:
            return ''
        if interval.kind == NOT_STATED:
            return ' periodically'
        if interval.value is None:
            return ''
        typically = '≈ ' if interval.kind == TYPICAL else ''
        return f' every {typically}{shown(interval.value.to(ureg.second))}'

    def describe_settings(self) -> str:
        """What follows the interval: how it is measured. Nothing, unless the kind of
        measurement says."""
        return ''

    def time_series_for_plotting(self, start: float, stop: float):
        """Each measurement a mark at the moment it is taken, not a stretch: one at the
        start, or one every `interval`."""
        series = super().time_series_for_plotting(start, stop)
        for piece in series.pieces:
            piece.text = None
            piece.mark_kind = self.technique
            piece.marks, piece.assumption = self.marks_for_plotting(
                piece.start, piece.end
            )
        return series

    def marks_for_plotting(self, start: float, end: float):
        """`(times, assumption)`: when the measurements are taken between `start` and
        `end`, in seconds, and what the drawing assumes. Where the interval is not
        stated, a few are drawn evenly, and the drawing says so; where nothing ends the
        drawing yet, only the first, since only the extent is needed."""
        interval = self.interval
        if interval is None or end == inf:
            return np.array([start]), None
        if interval.kind == NOT_STATED or interval.value is None:
            times = np.linspace(start, end, MARKS_FOR_PLOTTING, endpoint=False)
            return times, f'interval not stated: drawn {MARKS_FOR_PLOTTING} times'
        return np.arange(start, end, interval.value.to('s').magnitude), None

    def row_for_plotting(self) -> str:
        """The electrical load's: most measurements of a cell take its terminals,
        whatever else holds them, so they are drawn over what the load does. One that
        leaves the terminals alone, an image say, names its own row."""
        return 'electrical load'

    def role_for_plotting(self) -> str:
        """Monitored: a measurement regulates no condition."""
        return 'monitored'

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if not self.technique:
            logger.error(
                f'{self.name or "<unnamed>"} is a bare `{type(self).__name__}`, which '
                f'names no measurement: use one of its kinds, as `JVScan`.'
            )


class JVScan(CharacterizationInstruction):
    """J–V scans: the voltage swept as set, the current recorded. A standard writes
    them as "J–V every x"."""

    technique = 'J–V scan'

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

    def describe_settings(self) -> str:
        """` at 1000 W/m² (xenon lamp, AM1.5G)`: the light it is measured under."""
        said = ''
        if self.irradiance is not None:
            said += f' at {shown(self.irradiance)}'
        if self.light_source is not None:
            said += f' ({self.light_source.describe()})'
        return said


m_package.__init_metainfo__()
