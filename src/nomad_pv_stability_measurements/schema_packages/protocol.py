import re

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection

# The protocol's steps name these classes; importing them registers them with NOMAD.
from nomad_pv_stability_measurements.schema_packages.general import PlannedProcess
from nomad_pv_stability_measurements.schema_packages.hold_below_steps import (
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldCurrent,
    HoldIrradiance,
    HoldResistance,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.mpp_steps import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.ramp_steps import (
    RampCurrent,
    RampIrradiance,
    RampResistance,
    RampVoltage,
)
from nomad_pv_stability_measurements.schema_packages.utils import normalize_steps

m_package = SchemaPackage()

#: An ISOS designation, its level the last digit: `ISOS-L-3`, `ISOS-LC-3I` (§20.7).
_ISOS_DESIGNATION = re.compile(r'^ISOS-[A-Z]+-(?P<level>[1-3])I?$')
#: ISOS makes MPP tracking mandatory at this level, under light (p.37).
_MPP_MANDATORY_LEVEL = 3
#: The steps that set the electrical load, whichever way.
_LOAD_STEPS = (
    MPPTracking,
    VOCTracking,
    HoldVoltage,
    HoldCurrent,
    HoldResistance,
    RampVoltage,
    RampCurrent,
    RampResistance,
)


class GeoLocation(ArchiveSection):
    """Where on Earth a test ran, as coordinates.

    The place's *name* is deliberately not here: every NOMAD activity already declares
    `location`, "the location associated with this activity", so `Denver, U.S.` goes
    there and stays searchable beside every other activity in the Oasis. A section of
    its own rather than two flat fields, so the pair travels together (Design.md §15.12).
    """

    latitude = Quantity(
        type=np.float64,
        unit='degree',
        description='Degrees north of the equator; negative is south.',
    )
    longitude = Quantity(
        type=np.float64,
        unit='degree',
        description='Degrees east of Greenwich; negative is west.',
    )
    altitude = Quantity(
        type=np.float64,
        unit='m',
        description='Height above sea level; negative is below it. It sets the air '
        'mass, and so the spectrum an outdoor test actually sees. Write the unit where '
        'feet are meant (`5280 ft`): a bare number reads as metres (D6).',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # Reported, never repaired (D13a). The usual mistake is the pair the wrong way
        # round, which a latitude past ±90° is what catches.
        for field, limit in (('latitude', 90), ('longitude', 180)):
            value = getattr(self, field)
            if value is not None and abs(value.to('degree').magnitude) > limit:
                logger.error(
                    f'`{field}` is {value.to("degree").magnitude:g}°, outside '
                    f'±{limit}°: are latitude and longitude the wrong way round?'
                )


class StabilityProtocol(PlannedProcess, EntryData):
    """A PV stability test protocol: the steps that run, in order.

    The first steps usually set what holds for the whole run: monitor/control steps
    without an `estimated_duration`. For increased reability,
    `.stability.yaml` distinguishes `channel_settings` and `routine`. However, in the schema,
    they are all just different steps, and the protocol's own steps run in sequence as assumed by the
    parent classes.
    """

    standard = Quantity(
        type=str,
        description='Write here the name of the standard if this protocol is a standard one, e.g. `IEC 61215`. Free text for now.',
    )

    standard_variant = Quantity(
        type=str,
        description='Which of the options the standard offers this protocol takes, e.g. '
        '`65 °C` where the standard allows 65 °C or 85 °C. Each option is a protocol of '
        'its own; leave empty where the standard offers none. Free text (Design.md §18.1).',
    )

    standard_level = Quantity(
        type=int,
        description='The level of sophistication within the standard, 1 to 3 in ISOS. '
        'Left empty, it is derived from an ISOS designation (`ISOS-L-3` is 3) '
        '(Design.md §20.7).',
    )

    environment = Quantity(
        type=MEnum('indoor', 'outdoor', 'other'),
        description='Where the test is run. `indoor` is a lab, `outdoor` is a field test, and `other` is anything else. Free text in `notes` can be used for additional details.',
        default='indoor',
    )

    notes = Quantity(
        type=str,
        description='Anything else worth recording about this protocol, in free text.',
    )

    geo_location = SubSection(
        section_def=GeoLocation,
        description="Where the test ran, as coordinates; the place's name goes in "
        "NOMAD's own `location`. Chiefly for an `outdoor` test, where the site is part "
        'of the result — though a laboratory has a place on Earth too.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # The protocol's own steps run in sequence, like a sequential block's (§15.4).
        normalize_steps(self, 'sequential', logger)
        designation = _ISOS_DESIGNATION.match(self.standard or '')
        if designation is not None:
            if self.standard_level is None:
                self.standard_level = int(designation.group('level'))
            self.report_a_level_3_load_without_mpp_tracking(logger)

    def report_a_level_3_load_without_mpp_tracking(self, logger):
        """ "we indicate MPP tracking as mandatory only at the third, most advanced level
        of ISOS protocols" (Khenkin et al. 2020, p.37) — under light, since a dark test has
        no maximum power point to track. Reported, never repaired (D13a, §20.7)."""
        if self.standard_level != _MPP_MANDATORY_LEVEL:
            return
        steps = list(self.m_all_contents(depth_first=True))
        lit = any(
            isinstance(step, RampIrradiance)
            or (
                isinstance(step, HoldIrradiance)
                and (step.set_point is None or step.set_point.magnitude != 0)
            )
            or (
                isinstance(step, HoldBetweenIrradiance)
                and (step.upper_bound is None or step.upper_bound.magnitude != 0)
            )
            for step in steps
        )
        if not lit:
            return
        loads = [step for step in steps if isinstance(step, _LOAD_STEPS)]
        others = sorted({type(step).__name__ for step in loads} - {'MPPTracking'})
        if others or not loads:
            found = ', '.join(others) if others else 'no electrical load at all'
            logger.error(
                f'{self.standard} is level {self.standard_level} under light, where MPP '
                f'tracking is mandatory, but it writes {found}.'
            )


m_package.__init_metainfo__()
