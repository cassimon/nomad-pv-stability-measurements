"""Every institution's file reading module has the template's interface."""

import importlib
import inspect
import pathlib

import pytest

from nomad_pv_stability_measurements import file_reading
from nomad_pv_stability_measurements.file_reading import file_reading_TEMPLATE
from nomad_pv_stability_measurements.file_reading.file_reading_utils import SET_POINTS
from nomad_pv_stability_measurements.schema_packages.measurement import STEP_KINDS

INSTITUTIONS = sorted(
    path.stem.removeprefix('file_reading_')
    for path in pathlib.Path(file_reading.__file__).parent.glob('file_reading_*.py')
    if path.stem not in {'file_reading_TEMPLATE', 'file_reading_utils'}
)


def interface(module) -> dict[str, list[str]]:
    """The public functions of `module` defined there, with their parameter names."""
    return {
        name: list(inspect.signature(function).parameters)
        for name, function in inspect.getmembers(module, inspect.isfunction)
        if not name.startswith('_') and function.__module__ == module.__name__
    }


#: What every institution writes; the template's other functions are examples of
#: step readers, or optional.
REQUIRED = {'stability_run_belongs_to_this_institution', 'read_stability_run'}


@pytest.mark.parametrize('institution', INSTITUTIONS)
def test_an_institution_has_the_functions_of_the_template(institution):
    module = importlib.import_module(
        f'nomad_pv_stability_measurements.file_reading.file_reading_{institution}'
    )
    template = interface(file_reading_TEMPLATE)
    functions = interface(module)

    assert module.INSTITUTION == institution
    # Conditions are assumed only for what a phase of a protocol can hold.
    assert set(getattr(module, 'ASSUMED_CONDITIONS', {})) <= set(SET_POINTS)
    assert REQUIRED <= set(functions)
    # A function named as one of the template's takes the template's parameters.
    for name in set(functions) & set(template):
        assert functions[name] == template[name], name
    # Each step reader reads a kind of step the schema knows, from one file.
    assert module.STEP_READERS
    assert set(module.STEP_READERS) <= set(STEP_KINDS)
    for read in module.STEP_READERS.values():
        assert list(inspect.signature(read).parameters) == ['path']
