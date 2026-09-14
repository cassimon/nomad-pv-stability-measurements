from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import (
    ChannelCommand,
    ControlGroup,
    Variable,
)
from nomad_pv_stability_measurements.schema_packages.units import (
    StabilityUnitAwareFloat,
)

m_package = SchemaPackage()


class TemperatureChannelCommand(ChannelCommand):
    """The temperature axis."""

    control_groups = (
        ControlGroup(temperature=Variable('K', display='degC', field='hold')),
    )

    hold = Quantity(
        type=StabilityUnitAwareFloat(),
        unit='K',
        description='Constant temperature to hold, authored with its unit, e.g. '
        '`65 °C`. Leave it empty to keep the channel uncontrolled in this command.',
    )


class IrradiationChannelCommand(ChannelCommand):
    """The irradiation axis."""

    control_groups = (ControlGroup(irradiance=Variable('W/m^2', field='hold')),)

    hold = Quantity(
        # `dark` belongs to this one field, not to every unit-ful field here (D8a).
        type=StabilityUnitAwareFloat(named={'dark': '0 W/m^2'}),
        unit='W/m^2',
        description='Constant irradiance to hold, authored with its unit, e.g. `1 sun` '
        'or `100 mW/cm^2`. Write `dark` for a run deliberately kept dark: that is a '
        'setpoint somebody chose, not silence about the channel (D8a). Leave it empty '
        'to keep the channel uncontrolled in this command.',
    )
    spectrum = Quantity(
        type=str,
        description='Which spectrum the lamp delivers, e.g. `AM1.5G`. Free text for now.',
    )


class ElectricalLoadChannelCommand(ChannelCommand):
    """What the cell's terminals are held at while it ages.

    Three variables in one control group: the cell's own I–V curve ties them, so
    commanding the voltage leaves the current measured rather than commanded — which
    is why asking for two of them at once is a contradiction, not two conditions.
    """

    control_groups = (
        ControlGroup(
            voltage=Variable('V'),
            current=Variable('A'),
            # Set, never read back: an instrument reports a voltage and a current.
            resistance=Variable('ohm', monitor=False),
            numberless=('open_circuit',),
            tied_by='the cell I-V curve: commanding one leaves the others measured',
        ),
    )

    voltage = Quantity(
        type=StabilityUnitAwareFloat(),
        unit='V',
        description='Constant voltage to hold, authored with its unit, e.g. `0.8 V`. '
        'Same field as `hold` written beside `variable: voltage`.',
    )
    current = Quantity(
        type=StabilityUnitAwareFloat(),
        unit='A',
        description='Constant current to hold, authored with its unit, e.g. `5 mA`. '
        'Same field as `hold` written beside `variable: current`.',
    )
    resistance = Quantity(
        type=StabilityUnitAwareFloat(),
        unit='ohm',
        description='Constant load resistance, authored with its unit, e.g. `1 kΩ`. '
        'Same field as `hold` written beside `variable: resistance`.',
    )
    open_circuit = Quantity(
        type=bool,
        description='Leave the terminals open. A setpoint somebody chose, so the '
        'channel counts as controlled — but it stands for no number at all, which is '
        'why it is its own field (D8a). Also written as `hold: open_circuit`.',
    )


class MechanicalChannelCommand(ChannelCommand):
    """How far the device is bent or stretched while it ages."""

    # Two groups, not one: bending a device says nothing about stretching it.
    control_groups = (
        ControlGroup(bend_radius=Variable('m', display='mm')),
        ControlGroup(strain=Variable('dimensionless', display='%')),
    )

    bend_radius = Quantity(
        type=StabilityUnitAwareFloat(),
        unit='m',
        description='Radius the device is bent to, authored with its unit, e.g. '
        '`5 mm`. Same field as `hold` written beside `variable: bend_radius`.',
    )
    strain = Quantity(
        type=StabilityUnitAwareFloat(),
        unit='dimensionless',
        description='How far the device is stretched, authored as a fraction or a '
        'percentage, e.g. `2 %`. Same field as `hold` written beside '
        '`variable: strain`.',
    )


#: Which class an authored `channel:` names (D19a). Not cosmetic: a setpoint loaded as
#: the base class is dropped without a word, since only the channel class declares it.
CHANNEL_CLASSES = {
    'temperature': TemperatureChannelCommand,
    'irradiation': IrradiationChannelCommand,
    'electrical_load': ElectricalLoadChannelCommand,
    'mechanical': MechanicalChannelCommand,
}


m_package.__init_metainfo__()
