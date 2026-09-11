"""
The expanded protocol timeline (Design.md §4.4).

Never hand-authored: filled by the protocol's normalize pipeline (`source = simulated`)
or, later, from an instrument command log (`source = logged`). Events are stored as
column arrays -- one section, not one section per event.
"""

from nomad.datamodel.data import ArchiveSection
from nomad.metainfo import MEnum, Quantity, SchemaPackage

m_package = SchemaPackage()


class ProtocolTimeline(ArchiveSection):
    """
    Setpoint events as column arrays. Event `i` happens at `time[i]` and sets
    `targets[target_index[i]]` to `state_labels[state_index[i]]` with `value[i]`,
    inside the protocol node `paths[path_index[i]]`.
    """

    source = Quantity(
        type=MEnum('simulated', 'logged'),
        description='Expanded from the protocol, or read from an instrument log.',
    )
    estimated = Quantity(
        type=bool,
        description='A `stop_when` is present; the expansion assumed it never fires.',
    )
    truncated = Quantity(type=bool, description='Cut at the protocol `horizon`.')
    downsampled = Quantity(
        type=bool,
        description='Points were dropped to fit the budget; see `messages`.',
    )
    total_duration = Quantity(type=float, unit='hour')
    n_points = Quantity(type=int, description='Number of stored events.')
    messages = Quantity(
        type=str,
        shape=['*'],
        description='Validation messages and what downsampling dropped.',
    )

    # --- column arrays, one entry per event
    time = Quantity(type=float, shape=['*'], unit='second')
    target_index = Quantity(type=int, shape=['*'], description='Index into `targets`.')
    state_index = Quantity(
        type=int, shape=['*'], description='Index into `state_labels`.'
    )
    value = Quantity(
        type=float,
        shape=['*'],
        description=(
            "In the canonical unit of the target's kind (`target_units`). NaN where "
            'the state has no number (uncontrolled, track); 0 for off.'
        ),
    )
    path_index = Quantity(type=int, shape=['*'], description='Index into `paths`.')

    # --- lookup tables
    targets = Quantity(
        type=str,
        shape=['*'],
        description=(
            'One per (channel, variable, kind), e.g. `chamber.humidity[relative]`; '
            'implicit channels by their slot name, e.g. `atmosphere`.'
        ),
    )
    target_units = Quantity(
        type=str, shape=['*'], description='Canonical unit per target.'
    )
    state_labels = Quantity(type=str, shape=['*'])
    paths = Quantity(
        type=str,
        shape=['*'],
        description='Node paths, e.g. `light soak/daily cycle[7]/bias: track mpp`.',
    )


m_package.__init_metainfo__()
