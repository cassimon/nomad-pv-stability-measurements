"""Fixtures shared by the schema tests."""

import pytest


class RecordingLogger:
    """A stand-in for NOMAD's logger that keeps what was logged.

    `normalize()` reports an authoring mistake instead of raising (Design.md §7), so
    the message is the whole observable behaviour of a validation rule.
    """

    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, message, **kwargs):
        self.errors.append(message)

    def warning(self, message, **kwargs):
        self.warnings.append(message)

    def info(self, message, **kwargs):
        pass

    debug = info


@pytest.fixture
def log():
    return RecordingLogger()


@pytest.fixture
def normalized(log):
    """Normalizes a hand-built section the way NOMAD's own pass does.

    Every nested section runs before its parent (**verified**) — which is what fills
    the typed twins (D19a) that a parent's checks read.
    """

    def run(section):
        for nested in section.m_all_contents(depth_first=True, include_self=True):
            nested.normalize(None, log)
        return section

    return run
