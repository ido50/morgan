import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List

from packaging.requirements import Requirement
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion


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


class Cache:  # pylint: disable=protected-access
    def __init__(self):
        self.cache: set[str] = set()

    def check(self, req: Requirement) -> bool:
        if self.is_simple_case(req):
            return req.name in self.cache
        return str(req) in self.cache

    def add(self, req: Requirement):
        if self.is_simple_case(req):
            self.cache.add(req.name)
        else:
            self.cache.add(str(req))

    def is_simple_case(self, req):
        if not req.marker and not req.extras:
            specifier = req.specifier
            if not specifier:
                return True
            if all(spec.operator in ('>', '>=') for spec in specifier._specs):
                return True
        return False


@dataclass
class RequestCache:  # pylint: disable=too-few-public-methods
    d: Dict[str, Dict] = field(default_factory=dict)  # name: data

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
            data = json.load(response)
            data['response_url'] = str(response.url)

        # check metadata version ~1.0
        v_str = data["meta"]["api-version"]  # 1.4
        if not v_str:
            v_str = "1.0"
        v_int = [int(i) for i in v_str.split(".")[:2]]
        if v_int[0] != 1:
            raise ValueError(f"Unsupported metadata version {v_str}, only support 1.x")

        files = data["files"]
        if files is None or not isinstance(files, list):
            raise ValueError("Expected response to contain a list of 'files'")

        data["files"] = enrich_files(files)
        self.d[name] = data
        return data


def enrich_files(files: List[Dict]) -> List[Dict]:
    '''
    1) remove files with unsupported extensions or yanked
    2) parse versions and platform tags for each file
       (file["version"], file["tags"])
    '''

    def _ext(file: dict) -> bool:
        'remove files with unsupported extensions or yanked'
        f = file['filename'].endswith
        y = file.get("yanked", False)
        return not y and (f('.whl') or f('.zip') or f('.tar.gz'))

    def _parse(file: dict) -> bool:
        'parse versions and platform tags for each file'
        name = file['filename']
        f = name.endswith
        try:
            if f('.whl'):
                _, file["version"], _, file["tags"] = parse_wheel_filename(name)
                file["is_wheel"] = True
            elif f('.zip') or f('.tar.gz'):
                _, file["version"] = parse_sdist_filename(
                    # fix: selenium-2.0-dev-9429.tar.gz -> 9429
                    to_single_dash(name)
                )
                file["is_wheel"] = False
                file["tags"] = None
        except (InvalidVersion, InvalidSdistFilename, InvalidWheelFilename):
            # old versions
            # expandvars-0.6.0-macosx-10.15-x86_64.tar.gz

            # ignore files with invalid version, PyPI no longer allows
            # packages with special versioning schemes, and we assume we
            # can ignore such files
            return False
        return True

    filter1 = (file for file in files if _ext(file))
    filter2 = (file for file in filter1 if _parse(file))

    files2 = list(filter2)
    files2.sort(key=lambda file: file["version"], reverse=True)
    return files2


RCACHE = RequestCache()
