"""Small helpers shared across schema modules."""

import pint


def parsed(text, parse, field: str, logger):
    """`text` parsed by `parse`, or `None` with an error logged.

    Never raises: NOMAD's own normalizer would catch it and log a plugin crash, so
    an authoring mistake is reported as an error and the twin is left empty (§7).
    """
    if not text or not text.strip():
        return None
    try:
        return parse(text)
    except (ValueError, pint.errors.PintError) as error:
        logger.error(f'could not parse `{field}` {text!r}: {error}')
        return None


def with_m_def(entry, cls: type) -> dict:
    """`entry` with an `m_def` naming `cls`, added only if it's missing.

    Without an `m_def`, NOMAD loads a dict into a repeating sub-section as the
    class *declared* on that sub-section, silently dropping every field a more
    specific subclass would have added (Design.md §9, D11a) — this is how
    callers steer that per entry. A non-dict `entry` (already a built section)
    or one that already names a class is returned unchanged.
    """
    if not isinstance(entry, dict) or 'm_def' in entry:
        return entry
    return {**entry, 'm_def': f'{cls.__module__}.{cls.__name__}'}
