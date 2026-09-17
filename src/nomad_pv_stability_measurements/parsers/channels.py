"""The words an authored file uses for instructions (Design.md §15.2).

None of them reaches the archive: a `channel:` and a variable's key choose the instruction's
class, `hold` becomes its `set_point`, and a named word becomes the value it stands for.
"""

from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBelowAbsoluteHumidity,
    HoldBelowOxygenFraction,
    HoldBelowRelativeHumidity,
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    BalanceGas,
    HoldAbsoluteHumidity,
    HoldBendRadius,
    HoldCurrent,
    HoldIrradiance,
    HoldOxygenFraction,
    HoldPressure,
    HoldRelativeHumidity,
    HoldResistance,
    HoldStrain,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.ramp_instructions import (
    RampAbsoluteHumidity,
    RampBendRadius,
    RampCurrent,
    RampIrradiance,
    RampOxygenFraction,
    RampPressure,
    RampRelativeHumidity,
    RampResistance,
    RampStrain,
    RampTemperature,
    RampVoltage,
)
from nomad_pv_stability_measurements.schema_packages.standard_values import (
    Dark,
    RoomTemperature,
)

#: The instruction class each variable key names when the instruction holds one value (§15.11).
VARIABLE_INSTRUCTIONS = {
    'temperature': HoldTemperature,
    'irradiance': HoldIrradiance,
    'voltage': HoldVoltage,
    'current': HoldCurrent,
    'resistance': HoldResistance,
    'bend_radius': HoldBendRadius,
    'strain': HoldStrain,
    'absolute_humidity': HoldAbsoluteHumidity,
    'relative_humidity': HoldRelativeHumidity,
    'oxygen': HoldOxygenFraction,
    'pressure': HoldPressure,
    'balance_gas': BalanceGas,
}

#: Where a written value lands for a class that does not keep it in `set_point`. The
#: balance is a gas's name, not a number, so it has a field of its own (§15.15).
VALUE_FIELDS = {BalanceGas: 'gas'}

#: The same variables when the instruction ramps instead, chosen by an authored `ramp:`
#: (§15.14). One key, two kinds (§15.11).
RAMP_INSTRUCTIONS = {
    'temperature': RampTemperature,
    'irradiance': RampIrradiance,
    'voltage': RampVoltage,
    'current': RampCurrent,
    'resistance': RampResistance,
    'bend_radius': RampBendRadius,
    'strain': RampStrain,
    'absolute_humidity': RampAbsoluteHumidity,
    'relative_humidity': RampRelativeHumidity,
    'oxygen': RampOxygenFraction,
    'pressure': RampPressure,
}

#: The same variables when the instruction keeps under a bound instead, chosen by an authored
#: `hold_below:` (§17.5). Only what a standard bounds — the relative humidity, and the
#: water and oxygen of an inert atmosphere (§20.5); the rest are reported.
HOLD_BELOW_INSTRUCTIONS = {
    'absolute_humidity': HoldBelowAbsoluteHumidity,
    'relative_humidity': HoldBelowRelativeHumidity,
    'oxygen': HoldBelowOxygenFraction,
}

#: The same variables when the instruction keeps between two bounds, chosen by an authored
#: `hold_between:` (§22). Only what a standard gives a range for: the irradiance.
HOLD_BETWEEN_INSTRUCTIONS = {
    'irradiance': HoldBetweenIrradiance,
}

#: A variable's former key, still read as the key it became (§13.1a, §20.6).
VARIABLE_ALIASES = {'water_vapor': 'absolute_humidity'}

#: The variables an authored `channel:` groups, in the order an author reads them.
CHANNEL_VARIABLES = {
    'temperature': ('temperature',),
    'irradiation': ('irradiance',),
    'electrical_load': ('voltage', 'current', 'resistance'),
    'mechanical': ('bend_radius', 'strain'),
    'atmosphere': (
        'absolute_humidity',
        'relative_humidity',
        'oxygen',
        'pressure',
        'balance_gas',
    ),
}

#: Words a set point reads as a value, per instruction class. Never global: `dark` is an
#: irradiance and means nothing on the temperature axis, or in a duration (D8a).
NAMED_VALUES = {
    'irradiance': {'dark': Dark},
    'temperature': {'RT': RoomTemperature},
}

#: Words that name an instruction outright, with no value to hold: the load is driven to a point
#: the cell decides, not to a number the protocol writes (§15.13). `open_circuit` is what
#: ISOS Table 1 writes for `voc`, and is read as the same instruction.
TRACKED_POINTS = {
    'mpp': MPPTracking,
    'voc': VOCTracking,
    'open_circuit': VOCTracking,
}

#: The channel those points belong to. Written on any other, they are reported, the way
#: `dark` is refused off the irradiance axis (D8a).
TRACKED_POINT_CHANNEL = 'electrical_load'

#: Words the schema has no place for any more (§15), and why.
RETIRED_WORDS = {
    'humidity': 'humidity is two variables — write `relative_humidity: 85 %`, or the '
    'water as a volume ratio, `absolute_humidity: 500 ppm` (§20.6)',
}

_CHANNEL_COMMANDS = 'nomad_pv_stability_measurements.schema_packages.channel_commands'

_SCHEMA = 'nomad_pv_stability_measurements.schema_packages'

#: Classes renamed in the schema, which older bare archives still name in `m_def`, each
#: read as the class it became (§13.1a, §20.6).
OLD_CLASSES = {
    f'{_SCHEMA}.hold_steps.HoldWaterVaporFraction': HoldAbsoluteHumidity,
    f'{_SCHEMA}.ramp_steps.RampWaterVaporFraction': RampAbsoluteHumidity,
    f'{_SCHEMA}.hold_below_steps.HoldBelowWaterVaporFraction': HoldBelowAbsoluteHumidity,
}

#: The channel classes that §13's bare archives name in `m_def`, each read as the
#: channel it was.
OLD_CHANNEL_CLASSES = {
    f'{_CHANNEL_COMMANDS}.TemperatureChannelCommand': 'temperature',
    f'{_CHANNEL_COMMANDS}.IrradiationChannelCommand': 'irradiation',
    f'{_CHANNEL_COMMANDS}.ElectricalLoadChannelCommand': 'electrical_load',
    f'{_CHANNEL_COMMANDS}.MechanicalChannelCommand': 'mechanical',
}
