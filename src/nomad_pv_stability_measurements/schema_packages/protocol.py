import re

import numpy as np
from nomad.datamodel.data import ArchiveSection
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection

# The protocol's instructions name these classes; importing them registers them with NOMAD.
from nomad_pv_stability_measurements.schema_packages import (  # noqa: F401
    hold_below_instructions,
    hold_instructions,
    mpp_instructions,
    ramp_instructions,
)
from nomad_pv_stability_measurements.schema_packages.general import Plan

m_package = SchemaPackage()

#: An ISOS designation, its level the last digit: `ISOS-L-3`, `ISOS-LC-3I` (§20.7).
_ISOS_DESIGNATION = re.compile(r'^ISOS-[A-Z]+-(?P<level>[1-3])I?$')


class GeoLocation(ArchiveSection):
    """Where on Earth a test ran, as coordinates.

    The place's *name* is deliberately not here: it goes in the protocol's own
    `location`, as `Denver, U.S.`, and stays searchable as text. A section of
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


class StabilityProtocol(Plan):
    """A PV stability test protocol: the instructions a test runs.

    All of the protocol's own instructions run in parallel. The first usually set what
    holds for the whole run: monitor/control instructions without an
    `estimated_duration`, which never finish. For readability, `.stability.yaml`
    distinguishes `channel_settings` and `routine`; in the schema they are all just
    instructions, started together. The protocol's `estimated_duration`, if written, is
    where all of them are stopped.

    A plan only: this plugin never calls `execute()`.
    """

    instruction_execution_mode = 'parallel'

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

    location = Quantity(
        type=str,
        description='Where the test runs, by name, e.g. `Denver, U.S.`.',
    )

    geo_location = SubSection(
        section_def=GeoLocation,
        description="Where the test ran, as coordinates; the place's name goes in "
        '`location`. Chiefly for an `outdoor` test, where the site is part '
        'of the result — though a laboratory has a place on Earth too.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        designation = _ISOS_DESIGNATION.match(self.standard or '')
        if designation is not None and self.standard_level is None:
            self.standard_level = int(designation.group('level'))


m_package.__init_metainfo__()
