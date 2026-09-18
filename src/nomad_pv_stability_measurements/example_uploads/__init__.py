from nomad.config.models.plugins import ExampleUploadEntryPoint

example_upload_entry_point = ExampleUploadEntryPoint(
    title='ISOS stability protocols',
    category='Examples',
    description='Every protocol of ISOS Table 1 (Khenkin et al., Nature Energy 5, '
    '35-49, 2020) as a `.stability.yaml` file: dark storage, held bias, light soaking, '
    'outdoor exposure, thermal cycling, light cycling and solar-thermal cycling.',
    path='example_uploads/isos',
)

simulation_example_upload_entry_point = ExampleUploadEntryPoint(
    title='Simulated PV stability measurement',
    category='Examples',
    description='A light–dark cycling plan after ISOS-LC-2, and a simulated 24 h run of '
    'it: flat steps with the time series of temperature, irradiance, humidity and MPP '
    'power. The data is made up.',
    path='example_uploads/simulation',
)
