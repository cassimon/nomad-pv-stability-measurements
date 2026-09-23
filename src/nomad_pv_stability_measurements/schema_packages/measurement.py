"""What a stability test recorded, one step at a time.

A `StabilityMeasurement` is a stability test as it ran, read from the files it left:
who ran it, when, on what, and its steps in the order they ran. A step that records
conditions and output over time is a `StabilitySeriesStep`; a J–V sweep is a
`JVSweepStep`.
"""

import numpy as np
from nomad.datamodel.data import ArchiveSection
from nomad.datamodel.metainfo.basesections.v2 import (
    ActivityStep,
    InstrumentReference,
    SystemReference,
)
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection
from nomad.units import ureg

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
    MPP tracking no `voltage`, `current_density` or `power_density`. `controlled` says
    which of them were controlled; the rest were only monitored. How the electrical
    load was tracked, as set, is in `tracking_algorithm`, `tracking_step` and
    `tracking_delay`. It shows what the electrical load read over time, where it read
    anything.
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

    controlled = Quantity(
        type=MEnum(
            'temperature',
            'irradiance',
            'relative_humidity',
            'voltage',
            'current_density',
        ),
        shape=['*'],
        description='Which recorded quantities were controlled during the step: held '
        'or driven to a value, not only logged. Every other recorded quantity was only '
        'monitored. Under MPP tracking the voltage is controlled and the current '
        'follows; the power is never controlled, so it cannot be named here.',
    )
    tracking_algorithm = Quantity(
        type=str,
        description='How the electrical load was set during the step, as the tracker '
        'names it: `fixed voltage`, `perturb and observe`, ...',
    )
    tracking_step = Quantity(
        type=np.float64,
        unit='V',
        description='How far the tracker moves the voltage in one step, as set.',
    )
    tracking_delay = Quantity(
        type=np.float64,
        unit='s',
        description='How long the tracker waits after moving the voltage before it '
        'reads the current, as set.',
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
            [(self.name, hours, recorded, self.controlled or [])], self.name or ''
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


class JVFiguresOfMerit(ArchiveSection):
    """What the J–V station reports of one scan: the figures of merit it worked out
    from the curve. Taken as the station reports them, never worked out again here.
    """

    direction = Quantity(
        type=MEnum('forward', 'reverse'),
        description='Which scan of the sweep these figures are of.',
    )
    irradiance = Quantity(
        type=np.float64,
        unit='W/m^2',
        description='The light on the cell during the scan; 1000 W/m² is one sun.',
    )
    open_circuit_voltage = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage where no current flows, V_oc.',
    )
    short_circuit_current_density = Quantity(
        type=np.float64,
        unit='A/m^2',
        description='The current density at zero voltage, J_sc.',
    )
    fill_factor = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='The power at the maximum power point over V_oc · J_sc, as a '
        'fraction: 0.8 is 80 %.',
    )
    efficiency = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='The power conversion efficiency, PCE: the power at the maximum '
        'power point over the power of the light, as a fraction: 0.2 is 20 %.',
    )
    potential_at_maximum_power_point = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage at the maximum power point, V_mpp.',
    )
    current_density_at_maximum_power_point = Quantity(
        type=np.float64,
        unit='A/m^2',
        description='The current density at the maximum power point, J_mpp.',
    )
    power_density_at_maximum_power_point = Quantity(
        type=np.float64,
        unit='W/m^2',
        description='The power per area at the maximum power point, P_mpp: what the '
        'cell delivers at its best, comparable with the power a series tracked.',
    )
    series_resistance = Quantity(
        type=np.float64,
        unit='ohm*m^2',
        description='The series resistance per area, from the slope of the curve '
        'at open circuit.',
    )
    shunt_resistance = Quantity(
        type=np.float64,
        unit='ohm*m^2',
        description='The shunt resistance per area, from the slope of the curve '
        'at short circuit.',
    )


class JVSweepStep(PlotSection, ActivityStep):
    """A step that sweeps the voltage across the cell and records the current density.

    One row per point: `voltage`, `current_density` and `direction` are equally long.
    A reverse and a forward sweep are listed together, `direction` telling them apart,
    and are shown as one curve each. What the J–V station worked out of each scan is in
    `figures_of_merit`, and how the sweep was set up in its settings, `voltage_start`
    to `scan_order`.
    """

    voltage_start = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage the forward scan was set to start from, the lower end '
        'of the range swept.',
    )
    voltage_stop = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage the forward scan was set to end at, the upper end of '
        'the range swept. The data can end before it, where the station stops a scan '
        'once it has found the open circuit voltage.',
    )
    voltage_step = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage between two points of a scan, as set.',
    )
    scan_rate = Quantity(
        type=np.float64,
        unit='V/s',
        description='How fast the voltage was swept, as set.',
    )
    scan_order = Quantity(
        type=MEnum(
            'forward', 'reverse', 'forward then reverse', 'reverse then forward'
        ),
        description='Which scans the sweep was set to take, in the order taken.',
    )

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

    figures_of_merit = SubSection(
        section_def=JVFiguresOfMerit,
        repeats=True,
        description='The figures of merit the J–V station reported, one per scan.',
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

    #: What the overview shows of each J–V scan, as the station reported it, and in
    #: which row: the efficiency on top, the power at the maximum power point beside
    #: the power the series tracked.
    reported_for_plotting = {
        'efficiency': 'efficiency',
        'power_density_at_maximum_power_point': 'power_density',
    }

    def figures_for_plotting(self, logger) -> list[PlotlyFigure]:
        """The whole test on one time axis, in hours since it started: on top the
        efficiency of each J–V scan as the station reported it, one line per direction,
        then the output and the conditions the series recorded, each in the colour of
        its role, controlled or only monitored, with each scan's power at the maximum
        power point as dots on the power density row, and a dashed line where
        each J–V sweep was taken. Nothing where there is nothing to draw. A step with no
        `start_time` has no place on the axis and is left out, with a warning."""
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
                step.controlled or [],
            )
            for step in placed
            if isinstance(step, StabilitySeriesStep)
        ]
        pieces = [piece for piece in pieces if piece[2]]
        sweeps = [step for step in placed if isinstance(step, JVSweepStep)]
        reported = {}
        for step in sweeps:
            for scan in step.figures_of_merit:
                for name, row in self.reported_for_plotting.items():
                    value = getattr(scan, name)
                    if scan.direction is not None and value is not None:
                        reported.setdefault(row, {}).setdefault(
                            scan.direction, []
                        ).append((since_start(step), value))
        scans = {
            row: {
                direction: (
                    [at for at, _ in points],
                    ureg.Quantity.from_list([value for _, value in points]),
                )
                for direction, points in by_direction.items()
            }
            for row, by_direction in reported.items()
        }
        if not pieces and not scans:
            return []
        marks = [(since_start(step), 'J–V') for step in sweeps]
        figure = over_time_figure_for_plotting(pieces, self.name or '', marks, scans)
        return [PlotlyFigure(label='Over time', index=0, open=True, figure=figure)]

    def read_files(
        self, path, read_protocol, read_stability_series, read_jv_file
    ) -> list[str]:
        """Fill this measurement in from the run file at `path` and the step files
        it names, each read by the function given for it.

        `read_protocol(path)` returns `{'run': {...}, 'steps': [...]}`; each step
        names its `kind`, `stability_series` or `jv`, and the `file` the matching
        function reads into one array per column. A J–V file may also hand back
        `figures_of_merit`, a table of what the station reported, one row per scan. A
        series step may say which of its quantities were `controlled`. How a step was
        set up, such as a sweep's `scan_rate`, is its `settings`, one value per name of
        the quantity it fills, given in the step or handed back by its reader.
        A J–V step may carry its `figures_of_merit` itself, with or without a `file`:
        a scan whose curve was not kept but whose figures the station logged.
        Returns what had no place here, one message each, so that nothing is left out
        unsaid.
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
            if step.get('controlled') is not None:
                if isinstance(section, StabilitySeriesStep):
                    section.controlled = list(step['controlled'])
                else:
                    problems.append(
                        f'step `{step.get("name")}` says what was controlled, which '
                        'only a stability series has a place for.'
                    )
            problems += _read_step(section, step, read)
            steps.append(section)
        self.steps = steps
        return problems


def _read_step(section, step: dict, read) -> list[str]:
    """Fill `section` in from `step` of a run and the file it names, read by `read`;
    returns what had no place, one message each."""
    problems = []
    if step.get('file') is None and step.get('figures_of_merit') is None:
        problems.append(f'step `{step.get("name")}` names no file to read.')
    columns = dict(read(step['file'])) if step.get('file') else {}
    reported = columns.pop('figures_of_merit', None)
    if step.get('figures_of_merit') is not None:
        if reported is not None:
            problems.append(
                f'step `{step.get("name")}` has figures of merit both in its '
                'file and in the run; those of its file are kept.'
            )
        else:
            reported = step['figures_of_merit']
    settings = {**step.get('settings', {}), **columns.pop('settings', {})}
    problems += _fill_columns(section, columns, step.get('name'))
    problems += _fill_columns(section, settings, step.get('name'), 'setting')
    if reported is not None and isinstance(section, JVSweepStep):
        scans = []
        for row in _rows(reported):
            scans.append(JVFiguresOfMerit())
            problems += _fill_columns(scans[-1], row, step.get('name'))
        section.figures_of_merit = scans
    elif reported is not None:
        problems.append(
            f'step `{step.get("name")}` has figures of merit, which only a '
            'J–V sweep has a place for.'
        )
    return problems


def _rows(table: dict) -> list[dict]:
    """A table of columns as its rows, each a value per column: text as `str`."""
    count = len(next(iter(table.values()), []))
    return [
        {
            name: str(values[index])
            if isinstance(values, np.ndarray) and values.dtype.kind == 'U'
            else values[index]
            for name, values in table.items()
        }
        for index in range(count)
    ]


def _fill_columns(section, columns: dict, step_name, what='column') -> list[str]:
    """Each column into the quantity of its name; a column with no such quantity is
    reported, not dropped unsaid. A column is an array, or one value of a row or of
    the settings."""
    own = set(section.m_def.all_quantities) - set(ActivityStep.m_def.all_quantities)
    problems = []
    for name, values in columns.items():
        if name not in own:
            problems.append(
                f'step `{step_name}` has a {what} `{name}`, which '
                f'`{type(section).__name__}` has no place for.'
            )
            continue
        # Text is kept as a list: an enumeration takes no numpy array of strings.
        text = isinstance(values, np.ndarray) and values.dtype.kind == 'U'
        setattr(section, name, values.tolist() if text else values)
    return problems


m_package.__init_metainfo__()
