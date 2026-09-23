"""Reads an authored protocol into the bare archive the schema loads (Design.md §13, §15).

Works on plain dicts and never builds a section. From the schema it reads definitions
only: the class an entry names and each quantity's declared unit. The authoring words it
knows (`channel`, `hold`, `dark`, ...) are listed in `channels.py`. What it cannot read
becomes a `Problem`, never an exception, so one typo does not stop the rest of the file
from loading (§7).
"""

import difflib
import importlib
import re
from dataclasses import dataclass, field

import pint

from nomad_pv_stability_measurements.parsers.channels import (
    CHANNEL_VARIABLES,
    HOLD_BELOW_INSTRUCTIONS,
    HOLD_BETWEEN_INSTRUCTIONS,
    JV_SCAN_FIELDS,
    JV_SCAN_WORD,
    NAMED_VALUES,
    OLD_CHANNEL_CLASSES,
    OLD_CLASSES,
    RAMP_INSTRUCTIONS,
    RETIRED_WORDS,
    TRACKED_POINT_CHANNEL,
    TRACKED_POINTS,
    VALUE_FIELDS,
    VARIABLE_ALIASES,
    VARIABLE_INSTRUCTIONS,
)
from nomad_pv_stability_measurements.parsers.units import (
    parse,
    parse_difference,
    volume_ratio_of_relative_humidity,
)
from nomad_pv_stability_measurements.schema_packages.base_instructions import (
    MonitorControlInstruction,
)
from nomad_pv_stability_measurements.schema_packages.characterization_instructions import (
    JVScan,
)
from nomad_pv_stability_measurements.schema_packages.general import (
    FIXED,
    OPEN_ENDED,
    TYPICAL,
    WHOLE_BLOCK,
    CountingRepeatingBlock,
    Duration,
    IndefiniteRepeatingBlock,
    Instruction,
    InstructionBlock,
    Plan,
    RepeatingBlock,
    TimedRepeatingBlock,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol

#: Keys an instruction may be written with that are no field of the schema. They are
#: read here and never reach the archive.
AUTHORING_WORDS = (
    'channel',
    'variable',
    'hold',
    'hold_tolerance',
    'hold_below',
    'hold_between',
    'ramp',
    'duration',
    'instructions',
    'mode',
    'repeat',
    'repeat_for',
    JV_SCAN_WORD,
)
#: Keys a protocol may be written with that become its instructions (§14.3).
PROTOCOL_WORDS = ('channel_settings', 'routine', 'duration')
#: Keys an instruction or a plan may be written with for a field of another name
#: (§15.1, §15.6).
RENAMED = {
    'mode': 'sub_instruction_execution_mode',
    'repeat_for': 'repeat_duration',
    # A field renamed in the schema itself: every bare archive written before §17.4 still
    # spells it `setpoint`, and still loads (§13.1a).
    'setpoint': 'set_point',
}
#: What `repeat:` says when it is no number of times (§23).
REPEAT_INDEFINITELY = 'indefinitely'
#: `repeat:` words of the former notation, and what to write instead (§23).
RETIRED_REPEATS = {
    'until_end_of_protocol': f'`repeat: {REPEAT_INDEFINITELY}`, or leave `repeat` out',
    'until_end_of_duration': 'a timed block, `repeat_for: 12 h`',
    'n_times': 'the number itself, `repeat: 5`',
}
#: How a duration is written where it is no fixed length.
DURATION_WORDS = {'open-ended': OPEN_ENDED, 'whole block': WHOLE_BLOCK}
#: What a typical length is written with: `typical 1 min`.
TYPICAL_WORD = 'typical'
#: Every way a single instruction in a block may write its duration.
DURATION_SPELLINGS = '`1 h`, `typical 1 min`, `open-ended` or `whole block`'
#: The former word for `instructions` (§25).
RETIRED_INSTRUCTIONS = 'commands'

#: Both kinds back to their variable. A bare archive names either in its `m_def`, so a
#: stored ramp has to read back as a ramp and not as a hold (§15.14).
RAMP_KEYS = {cls: key for key, cls in RAMP_INSTRUCTIONS.items()}
HOLD_BELOW_KEYS = {cls: key for key, cls in HOLD_BELOW_INSTRUCTIONS.items()}
HOLD_BETWEEN_KEYS = {cls: key for key, cls in HOLD_BETWEEN_INSTRUCTIONS.items()}
VARIABLE_KEYS = (
    {cls: key for key, cls in VARIABLE_INSTRUCTIONS.items()}
    | RAMP_KEYS
    | HOLD_BELOW_KEYS
    | HOLD_BETWEEN_KEYS
)

#: The fields a named value such as `dark` or `RT` may be written into (D8a, §17.3).
NAMED_FIELDS = ('set_point', 'start_point', 'end_point', 'upper_bound', 'lower_bound')

#: What a `ramp:` writes, and the field each becomes (§15.14).
RAMP_FIELDS = {'from': 'start_point', 'to': 'end_point', 'rate': 'ramp_rate'}
#: What a `hold_between:` writes, and the field each becomes (§22).
BETWEEN_FIELDS = {'lower': 'lower_bound', 'upper': 'upper_bound'}

#: A relative humidity may be written the way it is usually read, `85 %RH` (§20.6).
_RELATIVE_HUMIDITY_UNIT = re.compile(r'%\s*rh$', re.IGNORECASE)


@dataclass(frozen=True)
class Problem:
    #: Where in the file, e.g. `data.routine.instructions[3].hold`.
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
    """One authored section read as `cls`, e.g. a block and its instructions."""
    problems = []
    return Translation(_section(authored, cls, '', problems), problems)


def _at(path: str, key: str) -> str:
    return f'{path}.{key}' if path else key


def _protocol(authored: dict, cls: type, path: str, problems: list) -> dict:
    """The protocol's own fields. `channel_settings` becomes its first instructions and
    `routine` its last, around any `instructions` written directly (§14.3). The protocol
    starts all of them together (§23)."""
    authored = dict(authored)
    settings = authored.pop('channel_settings', None)
    routine = authored.pop('routine', None)
    bare = _fields(authored, cls, path, problems)
    instructions = [
        *_settings_instructions(settings, _at(path, 'channel_settings'), problems),
        *bare.pop('instructions', []),
    ]
    if routine is not None:
        instructions += _instruction(routine, _at(path, 'routine'), problems)
    if instructions:
        bare['instructions'] = instructions
    return bare


def _settled(reads: list, path: str, in_block: bool, problems: list) -> list:
    """`reads`, the instructions one entry became, each with a duration where it wrote
    none. The protocol's own instructions — its settings — last as long as it; inside a
    block each states its own, unless a ramp works it out from its rate."""
    for each in reads:
        cls = _class_of(each)
        if cls is None or issubclass(cls, InstructionBlock) or 'duration' in each:
            continue
        if not in_block:
            each['duration'] = {'kind': WHOLE_BLOCK}
        elif 'ramp_rate' not in each:
            problems.append(
                Problem(
                    path,
                    f'an instruction in a block writes its `duration`: '
                    f'{DURATION_SPELLINGS}.',
                )
            )
    return reads


def _class_of(bare: dict) -> type | None:
    module, _, name = str(bare.get('m_def', '')).rpartition('.')
    try:
        return getattr(importlib.import_module(module), name, None)
    except ImportError:
        return None


def _settings_instructions(settings, path: str, problems: list) -> list:
    """The instructions of `channel_settings`. Written without a duration, they last as
    long as the protocol, which runs them in parallel with its routine. A channel of
    several variables may list one setting per variable: `atmosphere: [{...}, {...}]`."""
    if settings is None:
        return []
    if not isinstance(settings, dict):
        problems.append(Problem(path, f'expected a section, got {settings!r}.'))
        return []
    instructions = []
    for channel, written in settings.items():
        where = _at(path, channel)
        if isinstance(written, list):
            for index, block in enumerate(written):
                instructions += _setting(block, channel, f'{where}[{index}]', problems)
        else:
            instructions += _setting(written, channel, where, problems)
    return instructions


def _setting(block, channel: str, path: str, problems: list) -> list:
    """One setting of `channel`, as the instructions it reads as."""
    if not isinstance(block, dict):
        problems.append(Problem(path, f'expected a section, got {block!r}.'))
        return []
    written = block.get('channel', channel)
    if written != channel:
        problems.append(
            Problem(
                _at(path, 'channel'),
                f'`channel: {written}` does not match the slot `{channel}`.',
            )
        )
    read = _instruction({**block, 'channel': channel}, path, problems)
    return _settled(read, path, False, problems)


def _section(authored, cls: type, path: str, problems: list) -> dict:
    if not isinstance(authored, dict):
        problems.append(Problem(path, f'expected a section, got {authored!r}.'))
        return {}
    if issubclass(cls, MonitorControlInstruction):
        read = _monitor_control(authored, cls, path, problems)
        return {k: v for k, v in read[0].items() if k != 'm_def'} if read else {}
    return _fields(authored, cls, path, problems)


def _fields(authored: dict, cls: type, path: str, problems: list) -> dict:
    quantities = cls.m_def.all_quantities
    sub_sections = cls.m_def.all_sub_sections
    bare = {}
    for written, value in authored.items():
        where = _at(path, written)
        key = _renamed(written, cls)
        if written == RETIRED_INSTRUCTIONS and key != written:
            problems.append(
                Problem(
                    where, '`commands` is not written any more: write `instructions`.'
                )
            )
        if key != written and key in authored:
            problems.append(
                Problem(where, f'`{written}` and `{key}` are one field; write one.')
            )
        elif written == 'repeat' and issubclass(cls, InstructionBlock):
            _repeat(value, cls, where, problems, bare)
        elif written == 'duration' and issubclass(cls, Instruction | Plan):
            _duration(value, cls, where, problems, bare)
        elif key == 'm_def':
            bare[key] = value
        elif key in quantities:
            read = _value(value, cls, key, where, problems)
            if read is not None:
                bare[key] = read
        elif key in sub_sections and sub_sections[key].repeats:
            in_block = issubclass(cls, InstructionBlock)
            bare[key] = _instruction_list(value, where, in_block, problems)
        elif key in sub_sections:
            nested = sub_sections[key].sub_section.section_cls
            bare[key] = _section(value, nested, where, problems)
        else:
            problems.append(Problem(where, _unknown(written, cls)))
    return bare


def _duration(value, cls: type, where: str, problems: list, bare: dict) -> None:
    """`duration: 1 h` as a fixed duration, `typical 1 min` as a typical one, and
    `open-ended` or `whole block` as those kinds; a bare archive's section as itself. A
    block takes none: its duration follows from its instructions."""
    if issubclass(cls, InstructionBlock):
        problems.append(
            Problem(
                where,
                "a block's duration follows from its instructions. To stop it after a "
                'time, write `repeat_for`; to stop the whole protocol, write '
                '`duration` on the protocol.',
            )
        )
    elif isinstance(value, dict):
        bare['duration'] = _section(value, Duration, where, problems)
    elif isinstance(value, str) and value.strip().lower() in DURATION_WORDS:
        bare['duration'] = {'kind': DURATION_WORDS[value.strip().lower()]}
    else:
        kind, text = FIXED, value
        if isinstance(value, str) and value.strip().lower().startswith(TYPICAL_WORD):
            kind, text = TYPICAL, value.strip()[len(TYPICAL_WORD) :]
        read = _value(text, Duration, 'value', where, problems)
        if read is not None:
            bare['duration'] = {'kind': kind, 'value': read}


def _renamed(written: str, cls: type) -> str:
    """The field `written` stands for on `cls`: a block's `instructions` are its
    `sub_instructions`. Only instructions and plans take other names."""
    if not issubclass(cls, Instruction | Plan):
        return written
    if written in ('instructions', RETIRED_INSTRUCTIONS):
        return 'instructions' if issubclass(cls, Plan) else 'sub_instructions'
    return RENAMED.get(written, written)


def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _repeat(value, cls: type, where: str, problems: list, bare: dict) -> None:
    """`repeat: 5` as a counting block's `repeat_n`; `repeat: indefinitely` is an
    indefinite block, which writes nothing (§23, §27)."""
    if issubclass(cls, TimedRepeatingBlock):
        message = 'a timed block is stopped by its `repeat_for`; write no `repeat`.'
    elif not issubclass(cls, RepeatingBlock):
        message = f'{cls.__name__} runs its instructions once; write no `repeat`.'
    elif value in RETIRED_REPEATS:
        message = (
            f'`repeat: {value}` is not written any more: write '
            f'{RETIRED_REPEATS[value]}.'
        )
    elif value == REPEAT_INDEFINITELY and issubclass(cls, CountingRepeatingBlock):
        message = 'a CountingRepeatingBlock counts: write a number of times.'
    elif _is_count(value) and cls is IndefiniteRepeatingBlock:
        message = (
            'an IndefiniteRepeatingBlock never finishes: write no number of times.'
        )
    elif value == REPEAT_INDEFINITELY:
        return
    elif _is_count(value) and issubclass(cls, CountingRepeatingBlock):
        bare['repeat_n'] = value
        return
    else:
        message = (
            f'could not read `repeat` {value!r}: write a number of times, or '
            f'`{REPEAT_INDEFINITELY}`.'
        )
    problems.append(Problem(where, message))


def _instruction_list(entries, path: str, in_block: bool, problems: list) -> list:
    if not isinstance(entries, list):
        problems.append(Problem(path, 'expected a list of instructions.'))
        return []
    instructions = []
    for index, entry in enumerate(entries):
        where = f'{path}[{index}]'
        read = _instruction(entry, where, problems)
        instructions += _settled(read, where, in_block, problems)
    return instructions


def _instruction(entry, path: str, problems: list) -> list[dict]:
    """One authored entry as the instructions it becomes: usually one, none when it
    cannot be read, one per variable for a channel logged without a set point (§15.2)."""
    if not isinstance(entry, dict):
        problems.append(Problem(path, f'expected an instruction, got {entry!r}.'))
        return []
    rest = {key: value for key, value in entry.items() if key != 'm_def'}
    qualified = entry.get('m_def')
    if qualified in OLD_CHANNEL_CLASSES:
        rest.setdefault('channel', OLD_CHANNEL_CLASSES[qualified])  # §13's archives
        cls = None
    elif qualified in OLD_CLASSES:
        cls = OLD_CLASSES[qualified]  # a class renamed since (§20.6)
    elif qualified is not None:
        cls = _resolve(qualified, path, problems)
        if cls is None:
            return []
    elif JV_SCAN_WORD in rest:
        cls = JVScan
        rest = _jv_scan(rest, path, problems)
    elif 'channel' in rest:
        cls = None
    elif 'repeat_for' in rest:
        cls = TimedRepeatingBlock
    elif _is_count(rest.get('repeat')):
        cls = CountingRepeatingBlock
    else:
        cls = IndefiniteRepeatingBlock  # `repeat: indefinitely`, or no `repeat` at all
    if cls is None or issubclass(cls, MonitorControlInstruction):
        return _monitor_control(rest, cls, path, problems)
    return [{'m_def': m_def(cls), **_fields(rest, cls, path, problems)}]


def _jv_scan(authored: dict, path: str, problems: list) -> dict:
    """`jv_scan: {every: 10 min, from: -0.1 V, to: 1.2 V, ...}` as the fields of a
    `JVScan`, beside the entry's other keys such as its `duration`. `jv_scan: {}`, or
    with no settings, is one scan."""
    rest = dict(authored)
    written = rest.pop(JV_SCAN_WORD)
    if written is None:
        return rest
    if not isinstance(written, dict):
        where = _at(path, JV_SCAN_WORD)
        problems.append(
            Problem(where, f"expected the scan's settings, got {written!r}.")
        )
        return rest
    for word, value in written.items():
        rest[JV_SCAN_FIELDS.get(word, word)] = value
    return rest


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
    #: `hold_tolerance: 2 K`; `None` when not written (§17.4)
    tolerance: object = None
    #: `hold_below: 55 %`, which picks the bounded kind (§17.5); `None` when not written
    below: object = None
    #: `hold_between: {lower: …, upper: …}`, which picks the range kind (§22)
    between: object = None

    @classmethod
    def take(cls, authored: dict, path: str) -> '_Words':
        hold = authored.pop('hold', None)
        if isinstance(hold, str) and not hold.strip():
            hold = None  # blank text asks nothing, like never writing the key (D8)
        ramp = authored.pop('ramp', None)
        tolerance = authored.pop('hold_tolerance', None)
        below = authored.pop('hold_below', None)
        between = authored.pop('hold_between', None)
        for old, new in VARIABLE_ALIASES.items():  # a key's former spelling (§20.6)
            if old in authored:
                authored.setdefault(new, authored.pop(old))
            if authored.get('variable') == old:
                authored['variable'] = new
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
                if key in VARIABLE_INSTRUCTIONS
            },
            retired=retired,
            tracked=tracked,
            ramp=ramp,
            tolerance=tolerance,
            below=below,
            between=between,
        )


def _monitor_control(authored: dict, cls: type | None, path: str, problems: list):
    """A monitor/control entry as the instructions the schema stores (§15.2): the class its
    `m_def`, `channel` or variable names, and `hold` or the variable's key as the
    `set_point`, which also sets `control`."""
    authored = dict(authored)
    words = _Words.take(authored, path)
    for where, word in words.retired:
        problems.append(
            Problem(
                where,
                f'`{word}` is not part of the schema any more (§15): '
                f'{RETIRED_WORDS[word]}. The instruction is left out.',
            )
        )
    if words.retired:
        return []
    if words.tracked:
        return _tracked_instructions(words, authored, path, problems)
    classes = _instruction_classes(words, cls, path, problems)
    if not classes:
        return []
    bare = _fields(authored, classes[0], path, problems)
    reader = _kind_fields(words)
    if reader is not None:
        read = reader(words, classes, path, problems)
        if read is None:
            return []
        bare.update(read)
        bare.setdefault('control', True)
    # A class naming a point or a gas has no `set_point` to fill, and reaches here when a
    # bare archive names it in `m_def` and is read back (§13.1a, §15.13).
    elif (
        len(classes) == 1
        and _value_field(classes[0]) in classes[0].m_def.all_quantities
    ):
        written = _set_point(words, classes[0], path, problems)
        if written is not None:
            bare[_value_field(classes[0])] = written
            bare.setdefault('control', True)
        tolerance = _tolerance(words, classes[0], path, problems)
        if tolerance is not None:
            bare['set_point_tolerance'] = tolerance
    elif words.tolerance is not None:
        problems.append(
            Problem(
                _at(path, 'hold_tolerance'),
                'a tolerance belongs to one held value: say which variable it is for.',
            )
        )
    return [{'m_def': m_def(each), **bare} for each in classes]


def _tracked_instructions(
    words: _Words, authored: dict, path: str, problems: list
) -> list[dict]:
    """An instruction naming a point the cell decides, not a value to hold (§15.13).

    Asking for one is asking the load to be regulated, so it sets `control` exactly as a
    written set point does — there is simply no number to store beside it.
    """
    if len(words.tracked) > 1:
        written = ', '.join(word for _, word, _ in words.tracked)
        problems.append(
            Problem(
                path,
                f'a load sits at one point, but this instruction writes {written}.',
            )
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
                f'`{word}` is where the cell decides, so it takes no set point, but this '
                f'instruction also writes {", ".join(words.keys)}.',
            )
        )
        return []
    if words.tolerance is not None:
        problems.append(
            Problem(
                _at(path, 'hold_tolerance'),
                f'`{word}` is where the cell decides, so there is no value to be a '
                f'tolerance of.',
            )
        )
        return []
    tracking = TRACKED_POINTS[word]
    bare = _fields(authored, tracking, path, problems)
    bare.setdefault('control', True)
    return [{'m_def': m_def(tracking), **bare}]


def _kind_fields(words: _Words):
    """The reader for the word that chose a kind other than a hold, if one was written:
    `ramp:`, `hold_between:` or `hold_below:` (§15.14, §17.5, §22)."""
    if words.ramp is not None:
        return _ramp_fields
    if words.between is not None:
        return _between_fields
    return _bound_fields if words.below is not None else None


def _ramp_fields(
    words: _Words, classes: list, path: str, problems: list
) -> dict | None:
    """`ramp: {from, to, rate}` as the fields the schema stores (§15.14).

    `None` where the instruction cannot be read at all, so the caller leaves it out.
    """
    where = _at(path, 'ramp')
    if (
        words.hold is not None
        or words.tolerance is not None
        or words.below is not None
        or words.between is not None
        or words.keys
    ):
        problems.append(
            Problem(
                where, 'an instruction ramps or holds, not both; write one of them.'
            )
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


def _instruction_classes(words: _Words, cls, path: str, problems: list) -> list[type]:
    """The instruction classes a monitor/control entry becomes."""
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
                f'an instruction sets one variable, but this one writes {", ".join(chosen)}; '
                f'write one instruction per variable.',
            )
        )
        return []
    table, word = _kind(words, cls)
    if chosen or len(allowed) == 1:
        key = (chosen or allowed)[0]
        if key not in table:
            problems.append(Problem(_at(path, word), _no_such_kind(key, word)))
        return [table[key]] if key in table else []
    # A ramp or a bound names one variable, never a channel's worth — decided here, not
    # by how many classes the kind's table happens to have (§17.5).
    if words.hold is not None or word != 'hold':
        problems.append(Problem(_at(path, word), _unplaced(words, word, allowed)))
        return []
    # Nothing set: a channel logged as a whole, one instruction per variable (§15.2).
    return [table[key] for key in allowed if key in table]


def _kind(words: _Words, cls) -> tuple[dict, str]:
    """Which kind of instruction an entry is, as the table naming its classes and the word that
    chose it. `ramp:` and `hold_below:` choose their kinds — and so does a `Ramp…` or
    `HoldBelow…` class a bare archive names, which arrives without either word
    (§15.14, §17.5)."""
    if words.ramp is not None or cls in RAMP_KEYS:
        return RAMP_INSTRUCTIONS, 'ramp'
    if words.between is not None or cls in HOLD_BETWEEN_KEYS:
        return HOLD_BETWEEN_INSTRUCTIONS, 'hold_between'
    if words.below is not None or cls in HOLD_BELOW_KEYS:
        return HOLD_BELOW_INSTRUCTIONS, 'hold_below'
    return VARIABLE_INSTRUCTIONS, 'hold'


def _unplaced(words: _Words, word: str, allowed: tuple) -> str:
    """Why a value written on a channel of several variables could not be placed."""
    if word == 'ramp':
        return 'say which variable ramps: a whole channel cannot.'
    if word in ('hold_below', 'hold_between'):
        return 'say which variable is bounded: a whole channel cannot be.'
    return (
        f'could not place `hold` {words.hold!r}: say which variable it sets, '
        f'as `variable:` or as the key itself — {", ".join(allowed)}.'
    )


def _no_such_kind(key: str, word: str) -> str:
    if word == 'ramp':
        return f'`{key}` does not ramp: it holds one value and nothing else.'
    if word == 'hold_between':
        return (
            f'`{key}` takes no `hold_between`: no standard gives it a range yet (§22).'
        )
    return f'`{key}` takes no `{word}`: no standard bounds it yet (§17.5).'


def _bound_fields(
    words: _Words, classes: list, path: str, problems: list
) -> dict | None:
    """`hold_below: 55 %` as the field the schema stores (§17.5).

    `None` where the instruction cannot be read at all, so the caller leaves it out.
    """
    where = _at(path, 'hold_below')
    if words.hold is not None or words.tolerance is not None or words.keys:
        problems.append(
            Problem(
                where,
                'an instruction holds a value or keeps under a bound, not both; write one of them.',
            )
        )
        return None
    if isinstance(words.below, dict):
        bound = _relative_humidity(words.below, classes[0], where, problems)
    else:
        bound = _value(words.below, classes[0], 'upper_bound', where, problems)
    return {} if bound is None else {'upper_bound': bound}


def _between_fields(
    words: _Words, classes: list, path: str, problems: list
) -> dict | None:
    """`hold_between: {lower, upper}` as the fields the schema stores (§22). A bound
    left out is reported by the instruction's own `normalize`, as a stored archive would be.

    `None` where the instruction cannot be read at all, so the caller leaves it out.
    """
    where = _at(path, 'hold_between')
    if (
        words.hold is not None
        or words.tolerance is not None
        or words.below is not None
        or words.keys
    ):
        problems.append(
            Problem(
                where,
                'an instruction holds a value or keeps it in a range, not both; write one of '
                'them.',
            )
        )
        return None
    if not isinstance(words.between, dict):
        problems.append(
            Problem(
                where,
                f'expected a section with `lower` and `upper`, got {words.between!r}.',
            )
        )
        return None
    bare = {}
    for written, value in words.between.items():
        if written not in BETWEEN_FIELDS:
            problems.append(
                Problem(
                    _at(where, written),
                    f'`{written}` is no part of a range; it has '
                    f'{", ".join(BETWEEN_FIELDS)}.',
                )
            )
            continue
        field_name = BETWEEN_FIELDS[written]
        read = _value(value, classes[0], field_name, _at(where, written), problems)
        if read is not None:
            bare[field_name] = read
    return bare


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
    """Where a written value lands: `set_point`, unless the class keeps it elsewhere."""
    return VALUE_FIELDS.get(cls, 'set_point')


def _set_point(words: _Words, cls: type, path: str, problems: list):
    """The value as written: under the variable's own key, or as `hold`.

    Usually it lands in `set_point`; a class whose value is no number says where instead
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
    if axis != 'absolute_humidity':
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
    # Read through the water vapour's own hold: a bound has no `set_point` to ask.
    relative = _value(
        written['rh'],
        VARIABLE_INSTRUCTIONS['absolute_humidity'],
        'set_point',
        _at(where, 'rh'),
        problems,
    )
    kelvin = _value(
        written['at'],
        VARIABLE_INSTRUCTIONS['temperature'],
        'set_point',
        _at(where, 'at'),
        problems,
    )
    if relative is None or kelvin is None:
        return None
    return volume_ratio_of_relative_humidity(relative, kelvin)


def _value(value, cls: type, key: str, where: str, problems: list):
    """`value` as the schema stores it: a unit-ful quantity takes a number in its
    declared unit, read from text that writes its own (§6), or from a word the parser
    knows for that set point (D8a). Complaints name the key the file wrote, the last part
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
    if VARIABLE_KEYS.get(cls) == 'relative_humidity':
        text = _RELATIVE_HUMIDITY_UNIT.sub('%', text)  # `85 %RH` is `85 %` here only
    standard = _standard_value(text, cls) if key in NAMED_FIELDS else None
    read = parse_difference if key.endswith('_tolerance') else parse
    try:
        number = standard().value.to(unit) if standard else read(text, unit)
        return float(number.m)
    except (ValueError, pint.errors.PintError) as error:
        # The complaint quotes what the file wrote, not what a name resolved to.
        problems.append(Problem(where, f'could not read `{label}` {text!r}: {error}'))
        return None


def _standard_value(text, cls: type):
    """The `StandardValue` a word names for this class's variable, if it names one."""
    if not isinstance(text, str):
        return None
    return NAMED_VALUES.get(VARIABLE_KEYS.get(cls), {}).get(text.strip())


def _tolerance(words: _Words, cls: type, path: str, problems: list):
    """`hold_tolerance`, or else the tolerance a named value brings with it (§17.4).

    Written explicitly, it wins: a lab stating a tighter tolerance than the standard's is
    stating a fact about its own run, not contradicting anything.
    """
    where = _at(path, 'hold_tolerance')
    if 'set_point_tolerance' not in cls.m_def.all_quantities:
        if words.tolerance is not None:
            problems.append(
                Problem(where, f'{cls.__name__} holds no value to be a tolerance of.')
            )
        return None
    if words.tolerance is not None:
        return _value(words.tolerance, cls, 'set_point_tolerance', where, problems)
    key = VARIABLE_KEYS.get(cls)
    standard = _standard_value(words.keys.get(key, words.hold), cls)
    if standard is None or standard().tolerance is None:
        return None
    unit = cls.m_def.all_quantities['set_point_tolerance'].unit
    return float(standard().tolerance.to(unit).magnitude)


def _unknown(key: str, cls: type) -> str:
    """NOMAD would drop an unknown key without a word (§9); this says so, and guesses."""
    known = [*cls.m_def.all_quantities, *cls.m_def.all_sub_sections]
    if issubclass(cls, Instruction):
        known += AUTHORING_WORDS
    if issubclass(cls, MonitorControlInstruction):
        known += [*VARIABLE_INSTRUCTIONS, *RETIRED_WORDS, *TRACKED_POINTS]
    if issubclass(cls, StabilityProtocol):
        known += PROTOCOL_WORDS
    close = difflib.get_close_matches(key, known, n=1)
    hint = f' Did you mean `{close[0]}`?' if close else ''
    return f'`{key}` is not a field of {cls.__name__}, so it is ignored.{hint}'
