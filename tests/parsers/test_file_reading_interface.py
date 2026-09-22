"""Every institution's file reading module has the template's interface."""

import importlib
import inspect
import pathlib

import pytest

from nomad_pv_stability_measurements import parsers
from nomad_pv_stability_measurements.parsers import file_reading_TEMPLATE

INSTITUTIONS = sorted(
    path.stem.removeprefix('file_reading_')
    for path in pathlib.Path(parsers.__file__).parent.glob('file_reading_*.py')
    if path.stem not in {'file_reading_TEMPLATE', 'file_reading_utils'}
)


def interface(module) -> dict[str, list[str]]:
    """The public functions of `module` defined there, with their parameter names."""
    return {
        name: list(inspect.signature(function).parameters)
        for name, function in inspect.getmembers(module, inspect.isfunction)
        if not name.startswith('_') and function.__module__ == module.__name__
    }


@pytest.mark.parametrize('institution', INSTITUTIONS)
def test_an_institution_has_the_functions_of_the_template(institution):
    module = importlib.import_module(
        f'nomad_pv_stability_measurements.parsers.file_reading_{institution}'
    )

    assert module.INSTITUTION == institution
    assert interface(module) == interface(file_reading_TEMPLATE)
