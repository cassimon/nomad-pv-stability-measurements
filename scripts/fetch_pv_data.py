"""Download the HU-Box library that the tests read into a folder, or update it.

    HUBOX_REPO_TOKEN=... python scripts/fetch_pv_data.py test-resources/Ready-PV-data

The library is listed through Seafile's repo-token API on HU-Box. A file is
downloaded when it is missing locally, or its size or modification time differ from
the library's; each download is given the library's modification time, so the next
run skips it. Seafile serves a file in two steps: the API, given the token, hands
out a short-lived link, and the file is fetched from that link.
"""

import argparse
import json
import os
import posixpath
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API = 'https://box.hu-berlin.de/api/v2.1/via-repo-token'


def ask(endpoint: str, **query):
    """The API's JSON answer, asked with the repo token."""
    url = f'{API}/{endpoint}/?{urllib.parse.urlencode(query)}'
    request = urllib.request.Request(url)
    # Should the API redirect, the token is not sent along.
    request.add_unredirected_header(
        'Authorization', f'Token {os.environ["HUBOX_REPO_TOKEN"]}'
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main(dest: Path):
    files = ask('dir', path='/', recursive=1, type='f')['dirent_list']
    downloaded = 0
    for file in files:
        path = posixpath.join(file['parent_dir'], file['name'])
        target = dest / path.lstrip('/')
        mtime = datetime.fromisoformat(file['mtime']).timestamp()

        if (
            target.is_file()
            and target.stat().st_size == file['size']
            and int(target.stat().st_mtime) == int(mtime)
        ):
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(ask('download-link', path=path), target)
        os.utime(target, (mtime, mtime))
        downloaded += 1
        print(f'fetched {path}')

    print(f'{downloaded} of {len(files)} files downloaded into {dest}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('dest', type=Path, help='folder to download the library into')
    main(parser.parse_args().dest)
