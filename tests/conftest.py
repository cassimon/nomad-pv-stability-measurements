import os

import pytest

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# `nomad.client` and `nomad.utils` are imported inside the fixtures: importing them
# while conftest loads sets the root logger to DEBUG before pytest configures
# logging, which breaks tests that log through the standard library.


@pytest.fixture
def logger():
    from nomad.utils import get_logger

    return get_logger(__name__)


@pytest.fixture
def load_example():
    """Parse and normalize an `.archive.yaml` from `tests/data`."""
    from nomad.client import normalize_all, parse

    def load(filename):
        archive = parse(os.path.join(DATA_DIR, filename))[0]
        normalize_all(archive)
        return archive

    return load
