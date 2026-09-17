"""The words an authored file uses for steps (Design.md §15.2).

None of them reaches the archive: a `channel:` and a variable's key choose the step's
class, `hold` becomes its `set_point`, and a named word becomes the value it stands for.
"""

from nomad_pv_stability_measurements.schema_packages.hold_below_steps import (
    HoldBelowWaterVaporFraction,
)
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    BalanceGas,
    HoldBendRadius,
    HoldCurrent,
    HoldIrradiance,
    HoldOxygenFraction,
    HoldPressure,
    HoldResistance,
    HoldStrain,
    HoldTemperature,
    HoldVoltage,
    HoldWaterVaporFraction,
)
from nomad_pv_stability_measurements.schema_packages.mpp_steps import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.ramp_steps import (
    RampBendRadius,
    RampCurrent,
    RampIrradiance,
    RampOxygenFraction,
    RampPressure,
    RampResistance,
    RampStrain,
    RampTemperature,
    RampVoltage,
    RampWaterVaporFraction,
)
from nomad_pv_stability_measurements.schema_packages.standard_values import (
    Dark,
    RoomTemperature,
)

#: The step class each variable key names when the step holds one value (§15.11).
VARIABLE_STEPS = {
    'temperature': HoldTemperature,
    'irradiance': HoldIrradiance,
    'voltage': HoldVoltage,
    'current': HoldCurrent,
    'resistance': HoldResistance,
    'bend_radius': HoldBendRadius,
    'strain': HoldStrain,
    'water_vapor': HoldWaterVaporFraction,
    'oxygen': HoldOxygenFraction,
    'pressure': HoldPressure,
    'balance_gas': BalanceGas,
}

#: Where a written value lands for a class that does not keep it in `set_point`. The
#: balance is a gas's name, not a number, so it has a field of its own (§15.15).
VALUE_FIELDS = {BalanceGas: 'gas'}

#: The same variables when the step ramps instead, chosen by an authored `ramp:`
#: (§15.14). One key, two kinds — which is what R4 reads as one axis (§15.11).
RAMP_STEPS = {
    'temperature': RampTemperature,
    'irradiance': RampIrradiance,
    'voltage': RampVoltage,
    'current': RampCurrent,
    'resistance': RampResistance,
    'bend_radius': RampBendRadius,
    'strain': RampStrain,
    'water_vapor': RampWaterVaporFraction,
    'oxygen': RampOxygenFraction,
    'pressure': RampPressure,
}

#: The same variables when the step keeps under a bound instead, chosen by an authored
#: `hold_below:` (§17.5). Only what a standard bounds; the rest are reported.
HOLD_BELOW_STEPS = {
    'water_vapor': HoldBelowWaterVaporFraction,
}

#: The variables an authored `channel:` groups, in the order an author reads them.
CHANNEL_VARIABLES = {
    'temperature': ('temperature',),
    'irradiation': ('irradiance',),
    'electrical_load': ('voltage', 'current', 'resistance'),
    'mechanical': ('bend_radius', 'strain'),
    'atmosphere': ('water_vapor', 'oxygen', 'pressure', 'balance_gas'),
}

#: Words a set point reads as a value, per step class. Never global: `dark` is an
#: irradiance and means nothing on the temperature axis, or in a duration (D8a).
NAMED_VALUES = {
    'irradiance': {'dark': Dark},
    'temperature': {'RT': RoomTemperature},
}

#: Words that name a step outright, with no value to hold: the load is driven to a point
#: the cell decides, not to a number the protocol writes (§15.13). `open_circuit` is what
#: ISOS Table 1 writes for `voc`, and is read as the same step.
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
    'humidity': 'the schema records the water in the atmosphere absolutely, as a '
    'volume ratio — write `water_vapor: 500 ppm` or `water_vapor: 2 %`. A relative '
    'humidity says nothing without the temperature it was read at, so write that '
    'beside it: `water_vapor: {rh: 85 %, at: 65 °C}` (§15.16)',
}

_CHANNEL_COMMANDS = 'nomad_pv_stability_measurements.schema_packages.channel_commands'

#: The channel classes that §13's bare archives name in `m_def`, each read as the
#: channel it was.
OLD_CHANNEL_CLASSES = {
    f'{_CHANNEL_COMMANDS}.TemperatureChannelCommand': 'temperature',
    f'{_CHANNEL_COMMANDS}.IrradiationChannelCommand': 'irradiation',
    f'{_CHANNEL_COMMANDS}.ElectricalLoadChannelCommand': 'electrical_load',
    f'{_CHANNEL_COMMANDS}.MechanicalChannelCommand': 'mechanical',
}
