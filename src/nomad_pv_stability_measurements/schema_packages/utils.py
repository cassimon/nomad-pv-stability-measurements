"""Small helpers shared across schema modules."""


def with_m_def(entry, cls: type) -> dict:
    """`entry` with an `m_def` naming `cls`, added only if it's missing.
    """
    if not isinstance(entry, dict) or 'm_def' in entry:
        return entry
    return {**entry, 'm_def': f'{cls.__module__}.{cls.__name__}'}
