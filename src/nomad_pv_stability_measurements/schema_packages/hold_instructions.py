import numpy as np
from nomad.metainfo import MEnum, Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.base_instructions import (
    ElectricalLoad,
    HoldInstruction,
    Illuminated,
    MonitorControlInstruction,
)

m_package = SchemaPackage()


#: The one point a condition of the surroundings is taken from, where the protocol states
#: no number: whatever the laboratory, or the weather, gives.
AMBIENT = 'ambient'


def ambient(quantity: str) -> Quantity:
    """`reference_point` for a quantity that may be left to the surroundings."""
    return Quantity(
        type=MEnum(AMBIENT),
        description=f'The {quantity} taken from the surroundings instead of written as a '
        f'number: `{AMBIENT}`, whatever the laboratory or the weather gives.',
    )


class HoldTemperature(HoldInstruction):
    """The sample's temperature."""

    value = Quantity(type=np.float64, unit='K', description='Temperature to hold.')
    tolerance = Quantity(
        type=np.float64,
        unit='K',
        description='How far either side of `value` still counts.',
    )
    reference_point = ambient('temperature')


class HoldIrradiance(Illuminated, HoldInstruction):
    """The light on the sample."""

    value = Quantity(type=np.float64, unit='W/m^2', description='Irradiance to hold.')
    tolerance = Quantity(
        type=np.float64,
        unit='W/m^2',
        description='How far either side of `value` still counts.',
    )


class HoldVoltage(ElectricalLoad, HoldInstruction):
    """The voltage at the cell's terminals."""

    controlled = ('voltage',)
    dependent = ('current',)

    value = Quantity(type=np.float64, unit='V', description='Voltage to hold.')
    reference_point = Quantity(
        type=MEnum('V_MPP', 'near V_MPP', 'V_oc', '-V_oc'),
        description='The voltage taken from the device instead of written as a number: '
        'its maximum power point or open-circuit voltage, measured on the fresh device '
        '(§20.3). The sign is part of the value.',
    )
    tolerance = Quantity(
        type=np.float64,
        unit='V',
        description='How far either side of `value` still counts.',
    )


class HoldCurrent(ElectricalLoad, HoldInstruction):
    """The current through the cell."""

    controlled = ('current',)
    dependent = ('voltage',)

    value = Quantity(type=np.float64, unit='A', description='Current to hold.')
    reference_point = Quantity(
        type=MEnum('J_SC', '-J_MPP'),
        description='The current taken from the device instead of written as a number: '
        'its short-circuit current, or its current at the maximum power point, measured '
        'on the fresh device (§20.3). The sign is part of the value.',
    )
    tolerance = Quantity(
        type=np.float64,
        unit='A',
        description='How far either side of `value` still counts.',
    )


class HoldResistance(ElectricalLoad, HoldInstruction):
    """The load across the cell's terminals."""

    controlled = ('resistance',)
    dependent = ('voltage', 'current')

    value = Quantity(
        type=np.float64, unit='ohm', description='Load resistance to connect.'
    )
    tolerance = Quantity(
        type=np.float64,
        unit='ohm',
        description='How far either side of `value` still counts.',
    )


class HoldBendRadius(HoldInstruction):
    """How far the device is bent."""

    value = Quantity(
        type=np.float64, unit='m', description='Radius the device is bent to.'
    )
    tolerance = Quantity(
        type=np.float64,
        unit='m',
        description='How far either side of `value` still counts.',
    )


class HoldStrain(HoldInstruction):
    """How far the device is stretched."""

    value = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far the device is stretched, as a fraction.',
    )
    tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `value` still counts.',
    )


class HoldAbsoluteHumidity(HoldInstruction):
    """The water in the atmosphere around the sample, as a volume ratio (§20.6)."""

    value = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Water vapour to hold, as a volume ratio: the fraction itself, so '
        '`500 ppm` is 5e-4 and `2 %` is 0.02. "Absolute" in the glovebox sense, not '
        'g/m³; for the relative humidity use `HoldRelativeHumidity` (§20.6).',
    )
    tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `value` still counts.',
    )


class HoldRelativeHumidity(HoldInstruction):
    """The relative humidity around the sample, as the fraction itself (§20.6)."""

    value = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Relative humidity to hold, as a fraction: `85 %` is 0.85. At '
        'whatever temperature the sample is at — the instruction states no temperature of its '
        'own, and is not converted into a volume ratio.',
    )
    tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `value` still counts.',
    )
    reference_point = ambient('relative humidity')


class HoldOxygenFraction(HoldInstruction):
    """The oxygen in the atmosphere around the sample, as a volume ratio."""

    value = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Oxygen to hold, as a volume ratio: the fraction itself, so '
        '`0.1 ppm` is 1e-7 (a glovebox) and `21 %` is 0.21 (air).',
    )
    tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `value` still counts.',
    )
    reference_point = Quantity(
        type=MEnum(AMBIENT),
        description='The oxygen taken from the surroundings instead of written as a '
        'number: `ambient`, whatever the air around the sample holds. Not the 21 % of '
        'fresh air: people, flames and processes in a laboratory consume oxygen.',
    )


class HoldPressure(HoldInstruction):
    """The total pressure of the atmosphere around the sample."""

    value = Quantity(
        type=np.float64,
        unit='Pa',
        description='Pressure to hold: the atmosphere as a whole, beside the fractions '
        'the other instructions record (§15.10).',
    )
    tolerance = Quantity(
        type=np.float64,
        unit='Pa',
        description='How far either side of `value` still counts.',
    )


class BalanceGas(MonitorControlInstruction):
    """What the rest of the atmosphere is, beside the fractions the other instructions record.

    A name, not a number, so it declares no `value` either.
    """

    gas = Quantity(
        type=str,
        description='Which gas makes up the balance, e.g. `N2`, `air`, `Ar`. Free text, '
        'like `LightSource.spectrum`.',
    )

    def describe_values(self) -> str:
        return f' {self.gas}' if self.gas else ''


m_package.__init_metainfo__()
