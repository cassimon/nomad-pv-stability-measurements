from nomad.config.models.plugins import ExampleUploadEntryPoint

example_upload_entry_point = ExampleUploadEntryPoint(
    title='ISOS stability protocols',
    category='Examples',
    description='Every protocol of ISOS Table 1 (Khenkin et al., Nature Energy 5, '
    '35-49, 2020) as a `.stability.yaml` file: dark storage, held bias, light soaking, '
    'outdoor exposure, thermal cycling, light cycling and solar-thermal cycling.',
    path='example_uploads/isos',
)
