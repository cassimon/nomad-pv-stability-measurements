import os

import pytest
from nomad.client import normalize_all, parse

from nomad_pv_stability_measurements.schema_packages.protocol import (
    Protocol,
    StabilityProtocol,
    SubProtocol,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# "A, then B and C at the same time, then D" (Design.md §3).
TREE = {
    'name': 'example',
    'steps': [
        {'subprotocol': 'A'},
        {
            'subprotocol': 'fork',
            'mode': 'parallel',
            'steps': [{'subprotocol': 'B'}, {'subprotocol': 'C'}],
        },
        {'subprotocol': 'D'},
    ],
}


def as_authored(node: Protocol) -> dict:
    """`node` as a dict without `m_def`, which `m_to_dict` writes on every nested
    step (the recursive `SectionProxy` never counts as the same definition)."""

    def strip(data):
        if isinstance(data, dict):
            return {k: strip(v) for k, v in data.items() if k != 'm_def'}
        if isinstance(data, list):
            return [strip(v) for v in data]
        return data

    return strip(node.m_to_dict())


def test_steps_nest_as_subprotocols():
    root = Protocol.m_from_dict(TREE)
    fork = root.steps[1]

    assert [step.subprotocol for step in root.steps] == ['A', 'fork', 'D']
    assert [step.subprotocol for step in fork.steps] == ['B', 'C']
    assert all(isinstance(step, SubProtocol) for step in [*root.steps, *fork.steps])


def test_only_subprotocols_have_the_subprotocol_field():
    assert 'subprotocol' not in Protocol.m_def.all_quantities
    assert 'subprotocol' in SubProtocol.m_def.all_quantities


def test_mode_defaults_to_sequential():
    assert Protocol().mode == 'sequential'
    assert Protocol(mode='parallel').mode == 'parallel'


def test_mode_rejects_unknown_values():
    with pytest.raises(ValueError):
        Protocol(mode='interleaved')


def test_tree_round_trips():
    assert as_authored(Protocol.m_from_dict(TREE)) == TREE


def test_entry_loads_from_yaml_and_names_subprotocols():
    mainfile = os.path.join(DATA_DIR, 'tree.archive.yaml')
    archive = parse(mainfile)[0]
    normalize_all(archive)
    root = archive.data.protocol

    assert isinstance(archive.data, StabilityProtocol)
    assert archive.data.name == 'my protocol'
    assert root.name == 'example'
    assert [step.name for step in root.steps] == ['A', 'fork', 'D']
    assert [step.name for step in root.steps[1].steps] == ['B', 'C']
