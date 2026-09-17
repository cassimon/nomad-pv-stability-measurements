"""A file with `options:` as every protocol it stands for (Design.md §24).

Any section may list `options`: alternatives, each a set of keys written into that section.
Every combination of one alternative per `options` is a variant, translated as a file of
its own:

    electrical_load:
      options:
        - hold: mpp                 # a single value is its own label
        - label: fixed voltage near MPP
          variable: voltage
          reference_point: near V_MPP

An alternative may hold `options` of its own. A key is written beside the options or in
them, never both. A variant's `name` gets its labels in parentheses, in the order the file
writes them, and they are its `standard_variant` unless the file writes one.

Only this reads `options`; the translator never sees them.
"""

import itertools
from dataclasses import dataclass, field

from nomad_pv_stability_measurements.parsers.translate import Problem

OPTIONS = 'options'
LABEL = 'label'


@dataclass(frozen=True)
class Variant:
    #: The labels of the alternatives it takes, in the order the file writes them.
    labels: tuple[str, ...]
    document: object

    def key(self, stem: str) -> str:
        """The variant's name among its file's, e.g. `ISOS-L-2 (65 °C, MPP)`."""
        return f'{stem} ({", ".join(self.labels)})' if self.labels else stem


@dataclass
class Expansion:
    variants: list[Variant]
    problems: list[Problem] = field(default_factory=list)

    @property
    def has_options(self) -> bool:
        return len(self.variants) > 1 or any(v.labels for v in self.variants)


def expand(document) -> Expansion:
    """Every variant `document` stands for; a file without options stands for itself."""
    problems = []
    variants = []
    for written_labels, written in _expand(document, '', problems):
        labels = tuple(label for label in written_labels if label)
        _name(written, labels)
        variants.append(Variant(labels, written))
    keys = [variant.key('') for variant in variants]
    for key in sorted({key for key in keys if keys.count(key) > 1}):
        problems.append(
            Problem(
                OPTIONS,
                f'more than one variant is named `{key.strip() or "without options"}`; '
                f'give the alternatives a `label`.',
            )
        )
    # A mistake is made once, however many variants repeat it.
    return Expansion(variants, list(dict.fromkeys(problems)))


def _at(path: str, key) -> str:
    return f'{path}.{key}' if path else str(key)


def _expand(value, path: str, problems: list) -> list[tuple[tuple, object]]:
    """`value` as (labels, value) for each variant it stands for."""
    if isinstance(value, list):
        parts = [
            _expand(item, f'{path}[{index}]', problems)
            for index, item in enumerate(value)
        ]
        return [
            (
                sum((labels for labels, _ in combination), ()),
                [v for _, v in combination],
            )
            for combination in itertools.product(*parts)
        ]
    if not isinstance(value, dict):
        return [((), value)]
    parts = []
    for key, each in value.items():
        where = _at(path, key)
        if key == OPTIONS:
            parts.append(_alternatives(each, value, where, problems))
        else:
            parts.append([(ls, {key: v}) for ls, v in _expand(each, where, problems)])
    variants = []
    for combination in itertools.product(*parts):
        written = {}
        for _, keys in combination:
            written.update(keys)
        variants.append((sum((labels for labels, _ in combination), ()), written))
    return variants


def _alternatives(options, section: dict, path: str, problems: list) -> list:
    if not isinstance(options, list) or not options:
        problems.append(Problem(path, 'expected a list of alternatives.'))
        return [((), {})]
    variants = []
    for index, alternative in enumerate(options):
        where = f'{path}[{index}]'
        if not isinstance(alternative, dict):
            problems.append(Problem(where, f'expected a section, got {alternative!r}.'))
            continue
        keys = {key: value for key, value in alternative.items() if key != LABEL}
        for key in keys:
            if key in section:
                problems.append(
                    Problem(
                        _at(where, key),
                        f'`{key}` is also written beside the options; write it in one '
                        f'place.',
                    )
                )
        label = _label(alternative, keys, where, problems)
        for labels, written in _expand(keys, where, problems):
            variants.append(((label, *labels), written))
    return variants or [((), {})]


def _label(alternative: dict, keys: dict, where: str, problems: list) -> str:
    """The `label` written, or else the alternative's single value."""
    if LABEL in alternative:
        label = alternative[LABEL]
        if isinstance(label, str):
            return label
        problems.append(Problem(_at(where, LABEL), f'expected text, got {label!r}.'))
        return ''
    [value] = keys.values() if len(keys) == 1 else [None]
    if isinstance(value, str | int | float) and not isinstance(value, bool):
        return str(value)
    return ''


def _name(document, labels: tuple[str, ...]) -> None:
    """A variant is named after its alternatives."""
    data = document.get('data') if isinstance(document, dict) else None
    if not labels or not isinstance(data, dict):
        return
    variant = ', '.join(labels)
    if isinstance(data.get('name'), str):
        data['name'] = f'{data["name"]} ({variant})'
    data.setdefault('standard_variant', variant)
