"""The words an authored file uses for steps (Design.md §15.2).

None of them reaches the archive: a `channel:` and a variable's key choose the step's
class, `hold` becomes its `setpoint`, and a named word becomes the value it stands for.
"""

from nomad_pv_stability_measurements.schema_packages.activity_steps import (
    BendRadius,
    Current,
    Irradiance,
    OxygenFraction,
    Resistance,
    Strain,
    Temperature,
    Voltage,
    WaterVaporFraction,
)

#: The step class each variable key names.
VARIABLE_STEPS = {
    'temperature': Temperature,
    'irradiance': Irradiance,
    'voltage': Voltage,
    'current': Current,
    'resistance': Resistance,
    'bend_radius': BendRadius,
    'strain': Strain,
    'water_vapor': WaterVaporFraction,
    'oxygen': OxygenFraction,
}

#: The variables an authored `channel:` groups, in the order an author reads them.
CHANNEL_VARIABLES = {
    'temperature': ('temperature',),
    'irradiation': ('irradiance',),
    'electrical_load': ('voltage', 'current', 'resistance'),
    'mechanical': ('bend_radius', 'strain'),
    'atmosphere': ('water_vapor', 'oxygen'),
}

#: Words a setpoint reads as a value, per step class. Never global: `dark` is an
#: irradiance and means nothing on the temperature axis, or in a duration (D8a).
NAMED_SETPOINTS = {Irradiance: {'dark': 0.0}}

#: Words the schema has no place for any more (§15), and why.
RETIRED_WORDS = {
    'open_circuit': 'the terminals left open have no setpoint to hold',
    'humidity': 'the schema records the water in the atmosphere absolutely, as a '
    'volume ratio — write `water_vapor: 500 ppm` or `water_vapor: 2 %`. An authored '
    '`%RH` is not translated, since it says nothing without the temperature it was '
    'measured at',
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
