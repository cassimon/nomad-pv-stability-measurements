"""The schema never depends on the parsing (Design.md §13.1)."""

import ast
import pathlib

import nomad_pv_stability_measurements

PACKAGE = pathlib.Path(nomad_pv_stability_measurements.__file__).parent


def imported_modules(path: pathlib.Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_the_schema_does_not_import_the_parsers_or_the_file_reading():
    offending = {
        path.name: module
        for path in (PACKAGE / 'schema_packages').glob('*.py')
        for module in imported_modules(path)
        if module.startswith(
            (
                'nomad_pv_stability_measurements.parsers',
                'nomad_pv_stability_measurements.file_reading',
            )
        )
    }

    assert offending == {}
