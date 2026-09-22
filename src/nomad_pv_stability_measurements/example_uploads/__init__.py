from nomad.config.models.plugins import ExampleUploadEntryPoint

example_upload_entry_point = ExampleUploadEntryPoint(
    title='ISOS stability protocols',
    category='Examples',
    description='Every protocol of ISOS Table 1 (Khenkin et al., Nature Energy 5, '
    '35-49, 2020) as a `.stability.yaml` file: dark storage, held bias, light soaking, '
    'outdoor exposure, thermal cycling, light cycling and solar-thermal cycling.',
    path='example_uploads/isos',
)

simulated_runs_example_upload_entry_point = ExampleUploadEntryPoint(
    title='Simulated ISOS stability runs',
    category='Examples',
    description='A simulated run of every ISOS protocol, taking the first of its '
    'options, beside a copy of the protocols it follows. Each run is a folder: a run '
    'file saying who ran what, when and on which cell, a J–V sweep before and after, '
    'and one table of every monitored quantity over a week. Nothing was measured.',
    resources=['example_uploads/isos', 'example_uploads/simulated_data/*'],
)

custom_protocols_example_upload_entry_point = ExampleUploadEntryPoint(
    title='Custom stability protocols with simulated runs',
    category='Examples',
    description='Three stability protocols that follow no standard, each with a '
    'simulated run: a stepped stress test in phases with counted temperature cycles, '
    'an emulated outdoor day repeated for five days, and damp heat interrupted by '
    'light soaks at the maximum power point. They show nested blocks, repetition by '
    'count and by time, and conditions held side by side. Nothing was measured.',
    resources=['example_uploads/custom_protocols/*'],
)

protocols_in_run_files_example_upload_entry_point = ExampleUploadEntryPoint(
    title='Simulated stability runs that describe their own test',
    category='Examples',
    description='Two simulated runs whose run files name no protocol file but '
    'describe the test themselves: damp heat at open circuit, and seven days and '
    'nights at 45 °C. Each run file makes two entries, the run and the protocol it '
    'describes, and the run refers to its protocol. Nothing was measured.',
    resources=['example_uploads/protocols_in_run_files/*'],
)
