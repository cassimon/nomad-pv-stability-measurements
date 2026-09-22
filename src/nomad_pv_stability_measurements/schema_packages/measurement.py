"""What a stability test recorded, one step at a time.

A `StabilityMeasurement` is a stability test as it ran, read from the files it left:
who ran it, when, on what, and its steps in the order they ran. A step that records
conditions and output over time is a `StabilitySeriesStep`; a J–V sweep is a
`JVSweepStep`.
"""

import numpy as np
from nomad.datamodel.metainfo.basesections.v2 import (
    ActivityStep,
    InstrumentReference,
    SystemReference,
)
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import MEnum, Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.protocol import (
    StabilityActivity,
)
from nomad_pv_stability_measurements.schema_packages.step_figures import (
    ELECTRICAL_ROWS,
    ROWS,
    jv_figure_for_plotting,
    over_time_figure_for_plotting,
)

m_package = SchemaPackage()


class StabilitySeriesStep(PlotSection, ActivityStep):
    """A step that records conditions and output over time, all sampled together.

    One array per quantity, one value per sample, each as long as `time`. Only what
    was recorded is filled in: a test in the dark has no `irradiance`, one without
    MPP tracking no `voltage`, `current_density` or `power_density`. It shows what the
    electrical load read over time, where it read anything.
    """

    time = Quantity(
        type=np.float64,
        shape=['*'],
        unit='s',
        description='When each sample was taken, counted from the start of the step.',
    )
    temperature = Quantity(
        type=np.float64,
        shape=['*'],
        unit='K',
        description='The temperature of the sample at each sample time.',
    )
    irradiance = Quantity(
        type=np.float64,
        shape=['*'],
        unit='W/m^2',
        description='The light on the sample at each sample time.',
    )
    relative_humidity = Quantity(
        type=np.float64,
        shape=['*'],
        unit='dimensionless',
        description='The relative humidity around the sample at each sample time, as '
        'a fraction: 0.85 is 85 %.',
    )
    voltage = Quantity(
        type=np.float64,
        shape=['*'],
        unit='V',
        description="The voltage at the cell's terminals at each sample time.",
    )
    current_density = Quantity(
        type=np.float64,
        shape=['*'],
        unit='A/m^2',
        description='The current through the cell per area at each sample time; '
        'positive where the cell delivers power.',
    )
    power_density = Quantity(
        type=np.float64,
        shape=['*'],
        unit='W/m^2',
        description='The power the cell delivers per area at each sample time.',
    )

    #: The quantities recorded at each sample time, beside `time` itself.
    recorded = (
        'temperature',
        'irradiance',
        'relative_humidity',
        'voltage',
        'current_density',
        'power_density',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        filled = [name for name in self.recorded if getattr(self, name) is not None]
        if self.time is None:
            if filled:
                logger.error(
                    f'{", ".join(f"`{name}`" for name in filled)} recorded without '
                    '`time`: each sample needs the time it was taken.'
                )
            return
        samples = len(self.time)
        for name in filled:
            if len(getattr(self, name)) != samples:
                logger.error(
                    f'`{name}` has {len(getattr(self, name))} values but `time` has '
                    f'{samples}: each sample needs one value of each quantity.'
                )
        if np.any(np.diff(self.time.magnitude) < 0):
            logger.error(
                '`time` goes backwards: samples are listed as they were taken.'
            )
        self.figures = self.figures_for_plotting()

    def figures_for_plotting(self) -> list[PlotlyFigure]:
        """The electrical output over time; nothing where the load read nothing."""
        recorded = self.recorded_for_plotting(ELECTRICAL_ROWS)
        if not recorded:
            return []
        hours = self.time.to('hour').magnitude.tolist()
        figure = over_time_figure_for_plotting(
            [(self.name, hours, recorded)], self.name or ''
        )
        return [
            PlotlyFigure(label='Electrical output', index=0, open=True, figure=figure)
        ]

    def recorded_for_plotting(self, names) -> dict:
        """Of the quantities `names`, those recorded with one value per sample, by
        name: what can be drawn against `time`."""
        if self.time is None:
            return {}
        return {
            name: getattr(self, name)
            for name in names
            if getattr(self, name) is not None
            and len(getattr(self, name)) == len(self.time)
        }


class JVSweepStep(PlotSection, ActivityStep):
    """A step that sweeps the voltage across the cell and records the current density.

    One row per point: `voltage`, `current_density` and `direction` are equally long.
    A reverse and a forward sweep are listed together, `direction` telling them apart,
    and are shown as one curve each.
    """

    voltage = Quantity(
        type=np.float64,
        shape=['*'],
        unit='V',
        description='The voltage applied at each point of the sweep.',
    )
    current_density = Quantity(
        type=np.float64,
        shape=['*'],
        unit='A/m^2',
        description='The current through the cell per area at each point; positive '
        'where the cell delivers power.',
    )
    direction = Quantity(
        type=MEnum('forward', 'reverse'),
        shape=['*'],
        description='Which way the voltage was swept at each point: `forward` from '
        'short circuit towards open circuit, `reverse` back.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        lengths = {
            name: len(getattr(self, name))
            for name in ('voltage', 'current_density', 'direction')
            if getattr(self, name) is not None
        }
        if len(set(lengths.values())) > 1:
            logger.error(
                'the sweep has '
                + ', '.join(f'{count} `{name}`' for name, count in lengths.items())
                + ': each point needs one of each.'
            )
            return
        if self.voltage is not None and self.current_density is not None:
            figure = jv_figure_for_plotting(
                self.voltage, self.current_density, self.direction, self.name or ''
            )
            self.figures = [
                PlotlyFigure(label='J–V', index=0, open=True, figure=figure)
            ]


class StabilityMeasurement(PlotSection, StabilityActivity):
    """A stability test as it ran, read from the files an institution writes.

    Each institution writes its runs in a format of its own. `read_files` is handed
    the functions that read that format, and never opens a file itself. It shows the
    whole test over time: every series where it ran, every J–V sweep where it was
    taken.
    """

    operator = Quantity(
        type=str,
        description='Who ran the test.',
    )

    #: Where each entry of a run file's `run` goes.
    fields_of_run = {
        'name': 'name',
        'start': 'datetime',
        'end': 'datetime_end',
        'location': 'location',
        'standard': 'method',
        'operator': 'operator',
        'notes': 'description',
    }

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.figures = self.figures_for_plotting(logger)

    def figures_for_plotting(self, logger) -> list[PlotlyFigure]:
        """Everything the series recorded, on one time axis in hours since the test
        started, with a dashed line where each J–V sweep was taken; nothing where no
        series recorded anything. A step with no `start_time` has no place on the axis
        and is left out, with a warning."""
        placed = [step for step in self.steps if step.start_time is not None]
        for step in self.steps:
            if step.start_time is None and isinstance(
                step, StabilitySeriesStep | JVSweepStep
            ):
                logger.warning(
                    f'step `{step.name}` has no `start_time`, so the overview over '
                    'time leaves it out.'
                )
        if not placed:
            return []
        start = self.datetime or min(step.start_time for step in placed)

        def since_start(step) -> float:
            return (step.start_time - start).total_seconds() / 3600

        pieces = [
            (
                step.name,
                (since_start(step) + step.time.to('hour').magnitude).tolist(),
                step.recorded_for_plotting(ROWS),
            )
            for step in placed
            if isinstance(step, StabilitySeriesStep)
        ]
        pieces = [piece for piece in pieces if piece[2]]
        if not pieces:
            return []
        marks = [
            (since_start(step), 'J–V')
            for step in placed
            if isinstance(step, JVSweepStep)
        ]
        figure = over_time_figure_for_plotting(pieces, self.name or '', marks)
        return [PlotlyFigure(label='Over time', index=0, open=True, figure=figure)]

    def read_files(
        self, path, read_protocol, read_stability_series, read_jv_file
    ) -> list[str]:
        """Fill this measurement in from the run file at `path` and the step files
        it names, each read by the function given for it.

        `read_protocol(path)` returns `{'run': {...}, 'steps': [...]}`; each step
        names its `kind`, `stability_series` or `jv`, and the `file` the matching
        function reads into one array per column. Returns what had no place here, one
        message each, so that nothing is left out unsaid.
        """
        protocol = read_protocol(path)
        run = protocol['run']
        for key, field in self.fields_of_run.items():
            if run.get(key) is not None:
                setattr(self, field, run[key])
        self.samples = [SystemReference(**each) for each in run.get('samples', [])]
        self.instruments = [
            InstrumentReference(**each) for each in run.get('instruments', [])
        ]
        readers = {
            'stability_series': (StabilitySeriesStep, read_stability_series),
            'jv': (JVSweepStep, read_jv_file),
        }
        problems = []
        steps = []
        for step in protocol['steps']:
            if step.get('kind') not in readers:
                problems.append(
                    f'step `{step.get("name")}` is of kind `{step.get("kind")}`; '
                    f'only {", ".join(f"`{kind}`" for kind in readers)} are read.'
                )
                continue
            section_class, read = readers[step['kind']]
            section = section_class(name=step.get('name'), start_time=step.get('start'))
            problems += _fill_columns(section, read(step['file']), step.get('name'))
            steps.append(section)
        self.steps = steps
        return problems


def _fill_columns(section, columns: dict, step_name) -> list[str]:
    """Each column into the quantity of its name; a column with no such quantity is
    reported, not dropped unsaid."""
    own = set(section.m_def.all_quantities) - set(ActivityStep.m_def.all_quantities)
    problems = []
    for name, values in columns.items():
        if name not in own:
            problems.append(
                f'step `{step_name}` has a column `{name}`, which '
                f'`{type(section).__name__}` has no place for.'
            )
            continue
        # Text is kept as a list: an enumeration takes no numpy array of strings.
        text = isinstance(values, np.ndarray) and values.dtype.kind == 'U'
        setattr(section, name, values.tolist() if text else values)
    return problems


m_package.__init_metainfo__()
