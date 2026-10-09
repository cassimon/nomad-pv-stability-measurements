"""Where the measured data of the institutes is found for the tests.

The tests read the data from the HU-Box library `Ready-PV-data`, where new data is
added, not from the copy the package ships for its example uploads: locally as the folder Seafile syncs it to, beside the checkout; in CI as the copy
`scripts/fetch_pv_data.py` downloads, named by `PV_TEST_DATA`.
"""

import os
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]

#: The Seafile folder relative to the project, as synced on a developer's machine.
SYNCED = PROJECT / '../../../Seafile/Ready-PV-data'

PV_DATA = Path(os.environ.get('PV_TEST_DATA', SYNCED)).resolve()

requires_pv_data = pytest.mark.skipif(
    not PV_DATA.is_dir(),
    reason=f'no measured data at {PV_DATA}: sync HU-Box or set PV_TEST_DATA',
)
