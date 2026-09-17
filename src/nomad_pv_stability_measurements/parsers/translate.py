"""Reads an authored protocol into the bare archive the schema loads (Design.md §13, §15).

Works on plain dicts and never builds a section. From the schema it reads definitions
only: the class an entry names and each quantity's declared unit. The authoring words it
knows (`channel`, `hold`, `dark`, ...) are listed in `channels.py`. What it cannot read
becomes a `Problem`, never an exception, so one typo does not stop the rest of the file
from loading (§7).
"""

import difflib
import importlib
from dataclasses import dataclass, field

import pint

from nomad_pv_stability_measurements.parsers.channels import (
    CHANNEL_VARIABLES,
    NAMED_SETPOINTS,
    OLD_CHANNEL_CLASSES,
    RAMP_STEPS,
    RETIRED_WORDS,
    TRACKED_POINT_CHANNEL,
    TRACKED_POINTS,
    VALUE_FIELDS,
    VARIABLE_STEPS,
)
from nomad_pv_stability_measurements.parsers.units import (
    parse,
    volume_ratio_of_relative_humidity,
)
from nomad_pv_stability_measurements.schema_packages.general import PlannedProcessStep
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol
from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedMonitorControlStep,
    PlannedSubroutineStep,
)

#: Keys a step may be written with that are no field of the schema. They are read
#: here and never reach the archive.
AUTHORING_WORDS = (
    'channel',
    'variable',
    'hold',
    'ramp',
    'duration',
    'commands',
    'mode',
)
#: Keys a protocol may be written with that become its steps (§14.3).
PROTOCOL_WORDS = ('channel_settings', 'routine')
#: Keys a step may be written with for a field of another name (§15.1, §15.6).
RENAMED = {
    'duration': 'estimated_duration',
    'commands': 'steps',
    'mode': 'execution_mode',
}

#: Both kinds back to their variable. A bare archive names either in its `m_def`, so a
#: stored ramp has to read back as a ramp and not as a hold (§15.14).
RAMP_KEYS = {cls: key for key, cls in RAMP_STEPS.items()}
VARIABLE_KEYS = {cls: key for key, cls in VARIABLE_STEPS.items()} | RAMP_KEYS

#: What a `ramp:` writes, and the field each becomes (§15.14).
RAMP_FIELDS = {'from': 'start_point', 'to': 'end_point', 'rate': 'ramp_rate'}


@dataclass(frozen=True)
class Problem:
    #: Where in the file, e.g. `data.routine.commands[3].hold`.
    path: str
    message: str


@dataclass
class Translation:
    archive: dict
    problems: list[Problem] = field(default_factory=list)


def m_def(cls: type) -> str:
    """The qualified name NOMAD writes, and resolves, for `cls`."""
    return f'{cls.__module__}.{cls.__name__}'


def translate(document) -> Translation:
    """A whole authored file, `{data: {...}}`, as the archive NOMAD loads."""
    problems = []
    data = document.get('data') if isinstance(document, dict) else None
    if not isinstance(data, dict):
        problems.append(Problem('data', 'the file needs a `data:` section.'))
        return Translation({}, problems)
    rest = {key: value for key, value in data.items() if key != 'm_def'}
    cls = StabilityProtocol
    if 'm_def' in data:
        cls = _resolve(data['m_def'], 'data', problems) or cls
    archive = {'m_def': m_def(cls), **_protocol(rest, cls, 'data', problems)}
    return Translation({'data': archive}, problems)


def translate_section(authored: dict, cls: type) -> Translation:
    """One authored section read as `cls`, e.g. a block and its steps."""
    problems = []
    return Translation(_section(authored, cls, '', problems), problems)


def _at(path: str, key: str) -> str:
    return f'{path}.{key}' if path else key


def _protocol(authored: dict, cls: type, path: str, problems: list) -> dict:
    """The protocol's own fields. `channel_settings` becomes its first steps and
    `routine` its last, around any `steps` written directly (§14.3)."""
    authored = dict(authored)
    settings = authored.pop('channel_settings', None)
    routine = authored.pop('routine', None)
    bare = _fields(authored, cls, path, problems)
    steps = [
        *_settings_steps(settings, _at(path, 'channel_settings'), problems),
        *bare.pop('steps', []),
    ]
    if routine is not None:
        steps += _step(routine, _at(path, 'routine'), problems)
    if steps:
        bare['steps'] = steps
    return bare


def _settings_steps(settings, path: str, problems: list) -> list:
    """The steps of `channel_settings`, without a duration: conditions that hold for
    the whole protocol (D13). The routine, one block deeper, overrides them for its
    span."""
    if settings is None:
        return []
    if not isinstance(settings, dict):
        problems.append(Problem(path, f'expected a section, got {settings!r}.'))
        return []
    steps = []
    for channel, block in settings.items():
        where = _at(path, channel)
        if not isinstance(block, dict):
            problems.append(Problem(where, f'expected a section, got {block!r}.'))
            continue
        written = block.get('channel', channel)
        if written != channel:
            problems.append(
                Problem(
                    _at(where, 'channel'),
                    f'`channel: {written}` does not match the slot `{channel}`.',
                )
            )
        steps += _step({**block, 'channel': channel}, where, problems)
    return steps


def _section(authored, cls: type, path: str, problems: list) -> dict:
    if not isinstance(authored, dict):
        problems.append(Problem(path, f'expected a section, got {authored!r}.'))
        return {}
    if issubclass(cls, PlannedMonitorControlStep):
        steps = _monitor_control(authored, cls, path, problems)
        return {k: v for k, v in steps[0].items() if k != 'm_def'} if steps else {}
    return _fields(authored, cls, path, problems)


def _fields(authored: dict, cls: type, path: str, problems: list) -> dict:
    quantities = cls.m_def.all_quantities
    sub_sections = cls.m_def.all_sub_sections
    bare = {}
    for written, value in authored.items():
        where = _at(path, written)
        key = RENAMED.get(written, written)
        if not issubclass(cls, PlannedProcessStep):
            key = written
        if key != written and key in authored:
            problems.append(
                Problem(where, f'`{written}` and `{key}` are one field; write one.')
            )
        elif key == 'm_def':
            bare[key] = value
        elif key in quantities:
            read = _value(value, cls, key, where, problems)
            if read is not None:
                bare[key] = read
        elif key in sub_sections and sub_sections[key].repeats:
            bare[key] = _commands(value, where, problems)
        elif key in sub_sections:
            nested = sub_sections[key].sub_section.section_cls
            bare[key] = _section(value, nested, where, problems)
        else:
            problems.append(Problem(where, _unknown(written, cls)))
    return bare


def _commands(entries, path: str, problems: list) -> list:
    if not isinstance(entries, list):
        problems.append(Problem(path, 'expected a list of steps.'))
        return []
    return [
        step
        for index, entry in enumerate(entries)
        for step in _step(entry, f'{path}[{index}]', problems)
    ]


def _step(entry, path: str, problems: list) -> list[dict]:
    """One authored entry as the steps it becomes: usually one, none when it cannot be
    read, one per variable for a channel logged without a setpoint (§15.2)."""
    if not isinstance(entry, dict):
        problems.append(Problem(path, f'expected a step, got {entry!r}.'))
        return []
    rest = {key: value for key, value in entry.items() if key != 'm_def'}
    qualified = entry.get('m_def')
    if qualified in OLD_CHANNEL_CLASSES:
        rest.setdefault('channel', OLD_CHANNEL_CLASSES[qualified])  # §13's archives
        cls = None
    elif qualified is not None:
        cls = _resolve(qualified, path, problems)
        if cls is None:
            return []
    elif 'channel' in rest:
        cls = None
    else:
        cls = PlannedSubroutineStep
    if cls is None or issubclass(cls, PlannedMonitorControlStep):
        return _monitor_control(rest, cls, path, problems)
    return [{'m_def': m_def(cls), **_fields(rest, cls, path, problems)}]


def _resolve(qualified, path: str, problems: list) -> type | None:
    module, _, name = str(qualified).rpartition('.')
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError, ValueError):
        problems.append(
            Problem(_at(path, 'm_def'), f'cannot find the class `{qualified}`.')
        )
        return None


@dataclass
class _Words:
    """What a monitor/control entry's authoring words say, taken off its dict."""

    channel: str | None
    #: `variable: voltage`
    named: str | None
    #: `hold: 0.8 V`; `None` when not written or blank
    hold: object
    #: A variable as its own key: `voltage: 0.8 V`
    keys: dict
    #: (where, word) for each word the schema has no place for any more
    retired: list
    #: (where, word, value) for each word naming a point the cell decides (§15.13)
    tracked: list
    #: `ramp: {from: …, to: …, rate: …}`, which picks the ramping kind (§15.14)
    ramp: object

    @classmethod
    def take(cls, authored: dict, path: str) -> '_Words':
        hold = authored.pop('hold', None)
        if isinstance(hold, str) and not hold.strip():
            hold = None  # blank text asks nothing, like never writing the key (D8)
        ramp = authored.pop('ramp', None)
        retired = [(_at(path, key), key) for key in authored if key in RETIRED_WORDS]
        for _, key in retired:
            authored.pop(key)
        if isinstance(hold, str) and hold.strip() in RETIRED_WORDS:
            retired.append((_at(path, 'hold'), hold.strip()))
            hold = None
        tracked = [
            (_at(path, key), key, authored.pop(key))
            for key in list(authored)
            if key in TRACKED_POINTS
        ]
        if isinstance(hold, str) and hold.strip() in TRACKED_POINTS:
            tracked.append((_at(path, 'hold'), hold.strip(), True))
            hold = None
        variable = authored.get('variable')
        if isinstance(variable, str) and variable.strip() in RETIRED_WORDS:
            retired.append((_at(path, 'variable'), variable.strip()))
            authored.pop('variable')
            variable = None
        return cls(
            channel=authored.pop('channel', None),
            named=authored.pop('variable') if isinstance(variable, str) else None,
            hold=hold,
            keys={
                key: authored.pop(key)
                for key in list(authored)
                if key in VARIABLE_STEPS
            },
            retired=retired,
            tracked=tracked,
            ramp=ramp,
        )


def _monitor_control(authored: dict, cls: type | None, path: str, problems: list):
    """A monitor/control entry as the steps the schema stores (§15.2): the class its
    `m_def`, `channel` or variable names, and `hold` or the variable's key as the
    `setpoint`, which also sets `control`."""
    authored = dict(authored)
    words = _Words.take(authored, path)
    for where, word in words.retired:
        problems.append(
            Problem(
                where,
                f'`{word}` is not part of the schema any more (§15): '
                f'{RETIRED_WORDS[word]}. The step is left out.',
            )
        )
    if words.retired:
        return []
    if words.tracked:
        return _tracked_steps(words, authored, path, problems)
    classes = _step_classes(words, cls, path, problems)
    if not classes:
        return []
    bare = _fields(authored, classes[0], path, problems)
    if words.ramp is not None:
        ramped = _ramp_fields(words, classes, path, problems)
        if ramped is None:
            return []
        bare.update(ramped)
        bare.setdefault('control', True)
    # A class naming a point or a gas has no `setpoint` to fill, and reaches here when a
    # bare archive names it in `m_def` and is read back (§13.1a, §15.13).
    elif (
        len(classes) == 1
        and _value_field(classes[0]) in classes[0].m_def.all_quantities
    ):
        written = _setpoint(words, classes[0], path, problems)
        if written is not None:
            bare[_value_field(classes[0])] = written
            bare.setdefault('control', True)
    return [{'m_def': m_def(each), **bare} for each in classes]


def _tracked_steps(
    words: _Words, authored: dict, path: str, problems: list
) -> list[dict]:
    """A step naming a point the cell decides, not a value to hold (§15.13).

    Asking for one is asking the load to be regulated, so it sets `control` exactly as a
    written setpoint does — there is simply no number to store beside it.
    """
    if len(words.tracked) > 1:
        written = ', '.join(word for _, word, _ in words.tracked)
        problems.append(
            Problem(path, f'a load sits at one point, but this step writes {written}.')
        )
        return []
    where, word, value = words.tracked[0]
    if value is False:
        problems.append(
            Problem(
                where, f'`{word}: false` asks for nothing; write it or leave it out.'
            )
        )
        return []
    if words.channel is not None and words.channel != TRACKED_POINT_CHANNEL:
        problems.append(
            Problem(
                _at(path, 'channel'),
                f'`{word}` is a point of `{TRACKED_POINT_CHANNEL}`, not of '
                f'`{words.channel}`.',
            )
        )
        return []
    if words.keys:
        problems.append(
            Problem(
                path,
                f'`{word}` is where the cell decides, so it takes no setpoint, but this '
                f'step also writes {", ".join(words.keys)}.',
            )
        )
        return []
    tracking = TRACKED_POINTS[word]
    bare = _fields(authored, tracking, path, problems)
    bare.setdefault('control', True)
    return [{'m_def': m_def(tracking), **bare}]


def _ramp_fields(
    words: _Words, classes: list, path: str, problems: list
) -> dict | None:
    """`ramp: {from, to, rate}` as the fields the schema stores (§15.14).

    `None` where the step cannot be read at all, so the caller leaves it out.
    """
    where = _at(path, 'ramp')
    if words.hold is not None or words.keys:
        problems.append(
            Problem(where, 'a step ramps or holds, not both; write one of them.')
        )
        return None
    if len(classes) != 1:
        problems.append(
            Problem(where, 'say which variable ramps: a whole channel cannot.')
        )
        return None
    if not isinstance(words.ramp, dict):
        problems.append(Problem(where, f'expected a section, got {words.ramp!r}.'))
        return None
    bare = {}
    for written, value in words.ramp.items():
        if written not in RAMP_FIELDS:
            problems.append(
                Problem(
                    _at(where, written),
                    f'`{written}` is no part of a ramp; it has '
                    f'{", ".join(RAMP_FIELDS)}.',
                )
            )
            continue
        field_name = RAMP_FIELDS[written]
        read = _value(value, classes[0], field_name, _at(where, written), problems)
        if read is not None:
            bare[field_name] = read
    return bare


def _step_classes(words: _Words, cls, path: str, problems: list) -> list[type]:
    """The step classes a monitor/control entry becomes."""
    if cls is not None and cls not in VARIABLE_KEYS:
        return [cls]  # the base, or a class the parser has no words for
    allowed = _allowed(words, cls, path, problems)
    if allowed is None:
        return []
    written = [(_at(path, 'variable'), words.named)] if words.named else []
    written += [(_at(path, key), key) for key in words.keys]
    chosen = []
    for where, key in written:
        if key not in allowed:
            problems.append(
                Problem(
                    where,
                    f'`{key}` is not a variable of '
                    f'{f"`{words.channel}`" if words.channel else cls.__name__}; it has '
                    f'{", ".join(allowed)}.',
                )
            )
        elif key not in chosen:
            chosen.append(key)
    if len(chosen) > 1:
        problems.append(
            Problem(
                path,
                f'a step sets one variable, but this one writes {", ".join(chosen)}; '
                f'write one step per variable.',
            )
        )
        return []
    # `ramp:` picks the ramping kind of the same variable — and so does a `Ramp…` class
    # the file named itself, which arrives with no `ramp:` at all (§15.14).
    table = RAMP_STEPS if words.ramp is not None or cls in RAMP_KEYS else VARIABLE_STEPS
    if chosen or len(allowed) == 1:
        key = (chosen or allowed)[0]
        if key not in table:
            problems.append(
                Problem(
                    _at(path, 'ramp'),
                    f'`{key}` does not ramp: it holds one value and nothing else.',
                )
            )
        return [table[key]] if key in table else []
    if words.hold is not None:
        problems.append(
            Problem(
                _at(path, 'hold'),
                f'could not place `hold` {words.hold!r}: say which variable it sets, '
                f'as `variable:` or as the key itself — {", ".join(allowed)}.',
            )
        )
        return []
    # Nothing set: a channel logged as a whole, one step per variable (§15.2).
    return [table[key] for key in allowed if key in table]


def _allowed(words: _Words, cls, path: str, problems: list) -> tuple | None:
    """The variable keys an entry may set: its class's own, or its channel's."""
    if words.channel is not None and words.channel not in CHANNEL_VARIABLES:
        problems.append(
            Problem(
                _at(path, 'channel'),
                f'`{words.channel}` is not a channel; the channels are '
                f'{", ".join(CHANNEL_VARIABLES)}.',
            )
        )
        return None
    if cls is None:
        return CHANNEL_VARIABLES[words.channel]
    key = VARIABLE_KEYS[cls]
    if words.channel is not None and key not in CHANNEL_VARIABLES[words.channel]:
        problems.append(
            Problem(
                _at(path, 'channel'),
                f'`channel: {words.channel}` does not match {cls.__name__}.',
            )
        )
        return None
    return (key,)


def _value_field(cls: type) -> str:
    """Where a written value lands: `setpoint`, unless the class keeps it elsewhere."""
    return VALUE_FIELDS.get(cls, 'setpoint')


def _setpoint(words: _Words, cls: type, path: str, problems: list):
    """The value as written: under the variable's own key, or as `hold`.

    Usually it lands in `setpoint`; a class whose value is no number says where instead
    (`BalanceGas` keeps a gas's name in `gas`, §15.15).
    """
    field_name = _value_field(cls)
    key = VARIABLE_KEYS.get(cls)
    if key in words.keys and words.hold is not None:
        problems.append(
            Problem(
                _at(path, 'hold'),
                f'`hold` and `{key}` both set {key}; write one of them.',
            )
        )
    if key in words.keys:
        written, where = words.keys[key], _at(path, key)
    else:
        written, where = words.hold, _at(path, 'hold')
    if isinstance(written, dict):
        return _relative_humidity(written, cls, where, problems)
    return _value(written, cls, field_name, where, problems)


def _relative_humidity(written: dict, cls: type, where: str, problems: list):
    """`{rh: 85 %, at: 65 °C}` as the volume ratio it is at that temperature (§15.16).

    The one compound value the schema reads, and only on the water axis: a relative
    humidity says nothing without the temperature it was measured at (§15.7), so it
    carries that temperature itself rather than borrowing a neighbour's.
    """
    axis = VARIABLE_KEYS.get(cls)
    if axis != 'water_vapor':
        problems.append(
            Problem(where, f'`{axis or cls.__name__}` takes a value, not a section.')
        )
        return None
    if set(written) != {'rh', 'at'}:
        problems.append(
            Problem(
                where,
                'a relative humidity is written `{rh: 85 %, at: 65 °C}`: both halves, '
                'and nothing else.',
            )
        )
        return None
    relative = _value(written['rh'], cls, 'setpoint', _at(where, 'rh'), problems)
    kelvin = _value(
        written['at'],
        VARIABLE_STEPS['temperature'],
        'setpoint',
        _at(where, 'at'),
        problems,
    )
    if relative is None or kelvin is None:
        return None
    return volume_ratio_of_relative_humidity(relative, kelvin)


def _value(value, cls: type, key: str, where: str, problems: list):
    """`value` as the schema stores it: a unit-ful quantity takes a number in its
    declared unit, read from text that writes its own (§6), or from a word the parser
    knows for that setpoint (D8a). Complaints name the key the file wrote, the last part
    of `where`."""
    label = where.rpartition('.')[2]
    unit = cls.m_def.all_quantities[key].unit
    if unit is None or value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        problems.append(
            Problem(where, f'could not read `{label}` {value!r}: expected a value.')
        )
        return None
    if not isinstance(value, str):
        return float(value)  # a plain number is already in the declared unit (D6)
    text = value.strip()
    if not text:
        return None  # blank text asks nothing, like never writing the key (D8)
    named = NAMED_SETPOINTS.get(cls, {}) if key == 'setpoint' else {}
    try:
        number = named.get(text)
        return float(number if number is not None else parse(text, unit).m)
    except (ValueError, pint.errors.PintError) as error:
        # The complaint quotes what the file wrote, not what a name resolved to.
        problems.append(Problem(where, f'could not read `{label}` {text!r}: {error}'))
        return None


def _unknown(key: str, cls: type) -> str:
    """NOMAD would drop an unknown key without a word (§9); this says so, and guesses."""
    known = [*cls.m_def.all_quantities, *cls.m_def.all_sub_sections]
    if issubclass(cls, PlannedProcessStep):
        known += AUTHORING_WORDS
    if issubclass(cls, PlannedMonitorControlStep):
        known += [*VARIABLE_STEPS, *RETIRED_WORDS, *TRACKED_POINTS]
    if issubclass(cls, StabilityProtocol):
        known += PROTOCOL_WORDS
    close = difflib.get_close_matches(key, known, n=1)
    hint = f' Did you mean `{close[0]}`?' if close else ''
    return f'`{key}` is not a field of {cls.__name__}, so it is ignored.{hint}'
