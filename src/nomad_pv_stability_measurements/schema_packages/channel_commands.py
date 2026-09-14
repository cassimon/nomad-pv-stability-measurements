from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import ChannelCommand
from nomad_pv_stability_measurements.schema_packages.units import (
    StabilityUnitAwareFloat,
)

m_package = SchemaPackage()


class TemperatureChannelCommand(ChannelCommand):
    """The temperature axis."""

    hold = Quantity(
        type=StabilityUnitAwareFloat(),
        unit='K',
        description='Constant temperature to hold, authored with its unit, e.g. '
        '`65 °C`. Leave it empty to keep the channel uncontrolled in this command.',
    )


class IrradiationChannelCommand(ChannelCommand):
    """The irradiation axis."""

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


#: Which class an authored `channel:` names (D19a). Not cosmetic: a `hold` loaded as
#: the base class is dropped without a word, since only the channel class declares it.
CHANNEL_CLASSES = {
    'temperature': TemperatureChannelCommand,
    'irradiation': IrradiationChannelCommand,
}


m_package.__init_metainfo__()
