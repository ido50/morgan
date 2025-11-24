import json
import re
import urllib.parse
import urllib.request
from typing import Dict


def to_single_dash(filename):
    'https://packaging.python.org/en/latest/specifications/version-specifiers/#version-specifiers'

    # selenium-2.0-dev-9429.tar.gz
    m = re.search(r'-[0-9].*-', filename)
    if m:
        s2 = filename[m.start() + 1:]
        # 2.0-dev-9429.tar.gz
        s2 = s2.replace('-dev-', '.dev')
        # 2.0.dev9429.tar.gz
        s2 = s2.replace('-', '.')
        filename = filename[:m.start() + 1] + s2
    return filename
    # selenium-2.0.dev9429.tar.gz


class RequestCache:  # pylint: disable=too-few-public-methods
    d: Dict[str, Dict] = {}  # name: data

    def get(self, url: str, name: str) -> dict:
        if name in self.d:
            return self.d[name]

        if not url.endswith('/'):
            url += '/'

        # get information about this package from the Simple API in JSON
        # format as per PEP 691
        request = urllib.request.Request(
            f"{url}{name}/",
            headers={
                "Accept": "application/vnd.pypi.simple.v1+json",
            },
        )

        with urllib.request.urlopen(request) as response:
            data = self.d[name] = json.load(response)
            data['response_url'] = str(response.url)
            return data


RCACHE = RequestCache()
