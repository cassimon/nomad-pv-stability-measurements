import numpy as np
from nomad.metainfo import MEnum, Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldInstruction,
    MonitorControlInstruction,
)

m_package = SchemaPackage()


class HoldTemperature(HoldInstruction):
    """The sample's temperature."""

    set_point = Quantity(type=np.float64, unit='K', description='Temperature to hold.')
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='K',
        description='How far either side of `set_point` still counts.',
    )


class HoldIrradiance(HoldInstruction):
    """The light on the sample."""

    set_point = Quantity(
        type=np.float64, unit='W/m^2', description='Irradiance to hold.'
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='W/m^2',
        description='How far either side of `set_point` still counts.',
    )
    spectrum = Quantity(
        type=str,
        description='Which spectrum the lamp delivers, e.g. `AM1.5G`. Free text for now.',
    )


class HoldVoltage(HoldInstruction):
    """The voltage at the cell's terminals."""

    set_point = Quantity(type=np.float64, unit='V', description='Voltage to hold.')
    reference_point = Quantity(
        type=MEnum('V_MPP', 'near V_MPP', 'V_oc', '-V_oc'),
        description='The voltage taken from the device instead of written as a number: '
        'its maximum power point or open-circuit voltage, measured on the fresh device '
        '(§20.3). The sign is part of the value.',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='V',
        description='How far either side of `set_point` still counts.',
    )


class HoldCurrent(HoldInstruction):
    """The current through the cell."""

    set_point = Quantity(type=np.float64, unit='A', description='Current to hold.')
    reference_point = Quantity(
        type=MEnum('J_SC', '-J_MPP'),
        description='The current taken from the device instead of written as a number: '
        'its short-circuit current, or its current at the maximum power point, measured '
        'on the fresh device (§20.3). The sign is part of the value.',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='A',
        description='How far either side of `set_point` still counts.',
    )


class HoldResistance(HoldInstruction):
    """The load across the cell's terminals."""

    set_point = Quantity(
        type=np.float64, unit='ohm', description='Load resistance to connect.'
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='ohm',
        description='How far either side of `set_point` still counts.',
    )


class HoldBendRadius(HoldInstruction):
    """How far the device is bent."""

    set_point = Quantity(
        type=np.float64, unit='m', description='Radius the device is bent to.'
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='m',
        description='How far either side of `set_point` still counts.',
    )


class HoldStrain(HoldInstruction):
    """How far the device is stretched."""

    set_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far the device is stretched, as a fraction.',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `set_point` still counts.',
    )


class HoldAbsoluteHumidity(HoldInstruction):
    """The water in the atmosphere around the sample, as a volume ratio (§20.6)."""

    set_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Water vapour to hold, as a volume ratio: the fraction itself, so '
        '`500 ppm` is 5e-4 and `2 %` is 0.02. "Absolute" in the glovebox sense, not '
        'g/m³; for the relative humidity use `HoldRelativeHumidity` (§20.6).',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `set_point` still counts.',
    )


class HoldRelativeHumidity(HoldInstruction):
    """The relative humidity around the sample, as the fraction itself (§20.6)."""

    set_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Relative humidity to hold, as a fraction: `85 %` is 0.85. At '
        'whatever temperature the sample is at — the instruction states no temperature of its '
        'own, and is not converted into a volume ratio.',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `set_point` still counts.',
    )


class HoldOxygenFraction(HoldInstruction):
    """The oxygen in the atmosphere around the sample, as a volume ratio."""

    set_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Oxygen to hold, as a volume ratio: the fraction itself, so '
        '`0.1 ppm` is 1e-7 (a glovebox) and `21 %` is 0.21 (air).',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `set_point` still counts.',
    )


class HoldPressure(HoldInstruction):
    """The total pressure of the atmosphere around the sample."""

    set_point = Quantity(
        type=np.float64,
        unit='Pa',
        description='Pressure to hold: the atmosphere as a whole, beside the fractions '
        'the other instructions record (§15.10).',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='Pa',
        description='How far either side of `set_point` still counts.',
    )


class BalanceGas(MonitorControlInstruction):
    """What the rest of the atmosphere is, beside the fractions the other instructions record.

    A name, not a number, so it declares no `set_point` either (§15.10, §15.11).
    """

    gas = Quantity(
        type=str,
        description='Which gas makes up the balance, e.g. `N2`, `air`, `Ar`. Free text, '
        'like `HoldIrradiance.spectrum`.',
    )

    def describe_values(self) -> str:
        return f' {self.gas}' if self.gas else ''


m_package.__init_metainfo__()
