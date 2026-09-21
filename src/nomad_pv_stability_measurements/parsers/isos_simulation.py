"""Every protocol after an ISOS standard, simulated when it is parsed.

NOMAD gives a file to one parser only, so this extends the `.stability.yaml` parser: a
protocol whose `standard` is an ISOS designation gets a sibling entry, the simulated
run of it (`simulation_parser.simulate`: only the set values the plan states), whose
`protocol` references the protocol's own entry.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import yaml

from nomad_pv_stability_measurements.parsers.options import expand
from nomad_pv_stability_measurements.parsers.parser import (
    StabilityYamlParser,
    read,
    stem,
)
from nomad_pv_stability_measurements.parsers.simulation_parser import (
    measurement_plan,
    simulate,
)
from nomad_pv_stability_measurements.schema_packages.protocol import (
    _ISOS_DESIGNATION as ISOS_DESIGNATION,
)

if TYPE_CHECKING:
    from nomad.datamodel.datamodel import EntryArchive
    from structlog.stdlib import BoundLogger

#: How long each simulated run lasts, unless the protocol ends sooner: the horizon
#: ISOS results are usually read at.
RUN_LENGTH = timedelta(hours=1000)

#: How often a set value is recorded where the protocol does not say.
SAMPLE_EVERY = 300.0  # s

SIMULATED = ' (simulated)'


def isos_protocols(mainfile: str) -> list[str | None]:
    """The protocols in `mainfile` that follow an ISOS standard, by their entry key:
    `None` for a file without options, whose protocol is the file's own entry."""
    try:
        expansion = expand(read(mainfile))
    except (OSError, yaml.YAMLError):
        return []
    return [
        variant.key(stem(mainfile)) if expansion.has_options else None
        for variant in expansion.variants
        if isinstance(variant.document, dict)
        and ISOS_DESIGNATION.match(
            str((variant.document.get('data') or {}).get('standard') or '')
        )
    ]


def simulation_key(mainfile: str, protocol_key: str | None) -> str:
    """The entry key of the simulated run of a protocol: `ISOS-L-2 (65 °C) (simulated)`."""
    return f'{protocol_key or stem(mainfile)}{SIMULATED}'


class StabilityYamlSimulatingParser(StabilityYamlParser):
    """A `.stability.yaml`, as `StabilityYamlParser` reads it, plus a simulated run of
    each of its protocols that follows an ISOS standard."""

    def is_mainfile(
        self,
        filename: str,
        mime: str,
        buffer: bytes,
        decoded_buffer: str,
        compression: str | None = None,
    ) -> bool | Iterable[str]:
        matched = super().is_mainfile(
            filename, mime, buffer, decoded_buffer, compression
        )
        simulated = {simulation_key(filename, key) for key in isos_protocols(filename)}
        if not matched or not simulated:
            return matched
        protocols = matched if isinstance(matched, set) else set()
        return protocols | simulated

    def parse(
        self,
        mainfile: str,
        archive: 'EntryArchive',
        logger: 'BoundLogger',
        child_archives: dict[str, 'EntryArchive'] = None,
    ) -> None:
        super().parse(mainfile, archive, logger, child_archives)
        children = child_archives or {}
        for key in isos_protocols(mainfile):
            protocol = archive if key is None else children.get(key)
            simulation = children.get(simulation_key(mainfile, key))
            if protocol is None or protocol.data is None or simulation is None:
                logger.error('no simulation was made.', variant=key)
                continue
            simulation.metadata.entry_name = simulation_key(mainfile, key)
            try:
                simulation.data = simulated_run(protocol, logger.bind(variant=key))
            except ValueError as error:
                # One run that cannot be laid out must not cost the file its protocols.
                logger.error(f'no simulation was made: {error}', variant=key)


def simulated_run(protocol: 'EntryArchive', logger):
    """The simulated run of the protocol in `protocol`'s entry, starting now."""
    plan = measurement_plan(protocol.data.m_to_dict(), logger)
    start = datetime.now(timezone.utc).replace(microsecond=0)
    measurement = plan.create_activity(
        name=f'{plan.name}{SIMULATED}',
        datetime=start,
        datetime_end=start + RUN_LENGTH,
        description='Simulated when the protocol was parsed: only the set values the '
        'protocol states. Nothing was measured.',
    )
    simulate(measurement, SAMPLE_EVERY)
    # The standard it ran, in its own entry; outside an upload there is none, and the
    # copy kept in the measurement stands in.
    entry_id = protocol.metadata.entry_id if protocol.metadata else None
    if entry_id is not None:
        measurement.protocol = f'../upload/archive/{entry_id}#/data'
    return measurement
