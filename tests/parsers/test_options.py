"""A section with `options:` stands for each of its alternatives, and a file for every
combination of them (Design.md §24)."""

import pytest

from nomad_pv_stability_measurements.parsers.options import expand


def variants(data) -> dict:
    expansion = expand({'data': {'name': 'P', **data}})
    assert expansion.problems == []
    return {
        variant.key('P'): variant.document['data'] for variant in expansion.variants
    }


def test_every_combination_of_alternatives_is_a_variant_named_after_them():
    read = variants(
        {
            'temperature': {'options': [{'hold': '65 °C'}, {'hold': '85 °C'}]},
            'electrical_load': {
                'control': True,
                'options': [
                    {'label': 'MPP', 'hold': 'mpp'},
                    {'label': 'fixed voltage', 'reference_point': 'near V_MPP'},
                ],
            },
        }
    )

    assert read['P (85 °C, fixed voltage)'] == {
        'name': 'P (85 °C, fixed voltage)',
        'standard_variant': '85 °C, fixed voltage',
        'temperature': {'hold': '85 °C'},
        'electrical_load': {'control': True, 'reference_point': 'near V_MPP'},
    }
    assert sorted(read) == [
        'P (65 °C, MPP)',
        'P (65 °C, fixed voltage)',
        'P (85 °C, MPP)',
        'P (85 °C, fixed voltage)',
    ]


def test_an_alternative_that_adds_nothing_leaves_the_name_as_it_is():
    read = variants(
        {'irradiation': {'control': True, 'options': [{}, {'label': 'narrow'}]}}
    )

    assert read['P'] == {'name': 'P', 'irradiation': {'control': True}}
    assert read['P (narrow)']['standard_variant'] == 'narrow'


def test_an_alternative_may_offer_options_of_its_own():
    read = variants(
        {
            'routine': {
                'options': [
                    {
                        'label': 'short',
                        'instructions': [
                            {'duration': '1 h', 'options': [{}, {'label': 'x'}]}
                        ],
                    },
                    {'label': 'long', 'instructions': [{'duration': '8 h'}]},
                ]
            }
        }
    )

    assert sorted(read) == ['P (long)', 'P (short)', 'P (short, x)']


def test_a_file_without_options_stands_for_itself():
    document = {'data': {'name': 'P'}}

    [variant] = expand(document).variants

    assert variant.document == document
    assert variant.key('P') == 'P'


@pytest.mark.parametrize(
    ('data', 'path', 'reported'),
    [
        (
            {'temperature': {'hold': 'RT', 'options': [{'hold': '65 °C'}]}},
            'data.temperature.options[0].hold',
            'write it in one place',
        ),
        (
            {'temperature': {'options': {'hold': '65 °C'}}},
            'data.temperature.options',
            'a list',
        ),
        (
            {'electrical_load': {'options': [{'hold': 'mpp', 'control': True}, {}]}},
            'options',
            'give the alternatives a `label`',
        ),
    ],
)
def test_a_mistake_is_reported_with_its_path(data, path, reported):
    [problem] = expand({'data': data}).problems

    assert problem.path == path
    assert reported in problem.message
