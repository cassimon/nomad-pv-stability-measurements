"""Where light comes from: the sun, or a lamp.

A light source describes the light itself: what makes it, its spectrum, how it was
calibrated. How much of it reaches the sample is the irradiance an instruction states,
which names its source in `light_source`. The same classes describe the light a test ages
the cell under and the light its J–V scans are measured under.
"""

import numpy as np
from nomad.datamodel.data import ArchiveSection
from nomad.metainfo import Datetime, MEnum, Quantity, SchemaPackage, SubSection

from nomad_pv_stability_measurements.schema_packages.utils import words

m_package = SchemaPackage()


class GeoLocation(ArchiveSection):
    """Where on Earth something is, as coordinates.

    The place's *name* is deliberately not here: it goes in a `location` of its own, as
    `Denver, U.S.`, and stays searchable as text.
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
        'mass, and so the spectrum an outdoor test actually sees.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # Reported, never repaired. The usual mistake is the pair the wrong way round,
        # which a latitude past ±90° is what catches.
        for field, limit in (('latitude', 90), ('longitude', 180)):
            value = getattr(self, field)
            if value is not None and abs(value.to('degree').magnitude) > limit:
                logger.error(
                    f'`{field}` is {value.to("degree").magnitude:g}°, outside '
                    f'±{limit}°: are latitude and longitude the wrong way round?'
                )


class LightSource(ArchiveSection):
    """A source of light, of a kind not stated."""

    model = Quantity(
        type=str,
        description='The make and model, e.g. `Newport 91192`, as the maker names it.',
    )
    spectrum = Quantity(
        type=str,
        description='Which spectrum the light has, e.g. `AM1.5G`. A name for now.',
    )
    calibration = Quantity(
        type=str,
        description='How its intensity is calibrated and checked, e.g. against a '
        'reference cell, and how often. Some lamps degrade over a stability test, xenon '
        'lamps especially.',
    )

    def describe(self) -> str:
        """What it is, in words: `xenon lamp`, `sunlight`."""
        return words(type(self).__name__).lower()


class NaturalLightSource(LightSource):
    """The sun, outdoors: what the device receives follows from where it stands, when,
    and which way it faces. The sun's own position is worked out from the place and the
    time, never stated."""

    geo_location = SubSection(
        section_def=GeoLocation,
        description='Where the device stands.',
    )
    exposure_start = Quantity(
        type=Datetime,
        description='When the exposure to the sun starts.',
    )
    exposure_end = Quantity(
        type=Datetime,
        description='When the exposure to the sun ends.',
    )
    tilt = Quantity(
        type=np.float64,
        unit='degree',
        description="The device's angle to the horizon: 0° lies flat, facing up; 90° "
        "stands upright. On a tracker, its axis's angle.",
    )
    azimuth = Quantity(
        type=np.float64,
        unit='degree',
        description='The compass direction the device faces, clockwise from north: 180° '
        "faces south. On a tracker, its axis's direction.",
    )
    mounting = Quantity(
        type=MEnum('fixed', 'single-axis tracking', 'dual-axis tracking'),
        description='Whether the device stays put, or follows the sun about one axis or '
        'two, which turns it away from its `tilt` and `azimuth`.',
    )

    def describe(self) -> str:
        return 'sunlight'

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # Reported, never repaired.
        for field, low, high in (('tilt', 0, 180), ('azimuth', 0, 360)):
            value = getattr(self, field)
            if value is not None and not low <= value.to('degree').magnitude <= high:
                logger.error(
                    f'`{field}` is {value.to("degree").magnitude:g}°, outside '
                    f'{low}–{high}°.'
                )
        start, end = self.exposure_start, self.exposure_end
        if start is not None and end is not None and end < start:
            logger.error('`exposure_end` is before `exposure_start`.')


class ArtificialLightSource(LightSource):
    """A lamp. Any lamp can be built into a solar simulator: that is a property of the
    source, not a kind of it."""

    solar_simulator = Quantity(
        type=bool,
        description='Whether the source is a solar simulator: built to imitate '
        'sunlight, and classified against a standard for it.',
    )
    simulator_standard = Quantity(
        type=str,
        description='The standard a solar simulator is classified against, e.g. '
        '`IEC 60904-9:2020`, `ASTM E927`, `JIS C 8912`.',
    )
    simulator_classification = Quantity(
        type=str,
        description='Its class under that standard: spectral match, non-uniformity and '
        'temporal instability, e.g. `AAA` or `A+A+A+`. Spectral match class A counts '
        'only between 400 and 1100 nm.',
    )
    lamp_power = Quantity(
        type=np.float64,
        unit='W',
        description='The electrical power the lamp is rated for, e.g. `1000 W` for a '
        'xenon arc lamp: how a lamp is usually named. The light on the sample is the '
        'irradiance, stated where the light is used.',
    )

    def lamp_name(self) -> str:
        """The lamp, in words; empty where the kind is not stated."""
        return '' if type(self) is ArtificialLightSource else super().describe()

    def describe(self) -> str:
        """`xenon lamp`, `solar simulator`, `LED solar simulator AAA`."""
        name = self.lamp_name()
        if not self.solar_simulator:
            return name or 'artificial light'
        return ' '.join(
            filter(None, (name, 'solar simulator', self.simulator_classification))
        )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if not self.solar_simulator and (
            self.simulator_standard or self.simulator_classification
        ):
            logger.warning(
                'A solar simulator standard or class is written, but `solar_simulator` '
                'is not set: is the source a solar simulator?'
            )


class LED(ArtificialLightSource):
    """Light-emitting diodes, usually white. Without UV unless its range is extended
    below 400 nm."""

    colour_temperature = Quantity(
        type=np.float64,
        unit='K',
        description='The correlated colour temperature of its white light.',
    )

    def lamp_name(self) -> str:
        return 'LED'


class XenonLamp(ArtificialLightSource):
    """A xenon arc lamp. Its spectrum reaches into the UV, so any filtering is part of
    the light."""

    uv_filter = Quantity(
        type=bool,
        description='Whether the UV is filtered out of the light.',
    )


class MetalHalideLamp(ArtificialLightSource):
    """A metal halide lamp. Its spectrum reaches into the UV, so any filtering is part
    of the light."""

    uv_filter = Quantity(
        type=bool,
        description='Whether the UV is filtered out of the light.',
    )


class SulfurPlasmaLamp(ArtificialLightSource):
    """A sulfur plasma lamp. Its spectrum holds no UV to filter."""


m_package.__init_metainfo__()
