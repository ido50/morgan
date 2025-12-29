import os
import re
from collections import OrderedDict

import dateutil  # type: ignore[import-untyped]
from packaging.requirements import Requirement


def to_single_dash(filename):
    "https://packaging.python.org/en/latest/specifications/version-specifiers/#version-specifiers"

    # selenium-2.0-dev-9429.tar.gz
    m = re.search(r"-[0-9].*-", filename)
    if m:
        s2 = filename[m.start() + 1 :]
        # 2.0-dev-9429.tar.gz
        s2 = s2.replace("-dev-", ".dev")
        # 2.0.dev9429.tar.gz
        s2 = s2.replace("-", ".")
        filename = filename[: m.start() + 1] + s2
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
            if all(spec.operator in (">", ">=") for spec in specifier._specs):
                return True
        return False


class ListExtendingOrderedDict(OrderedDict):
    """An OrderedDict subclass that aggregates list values for duplicate keys.

    This class extends OrderedDict to provide special handling for list values.
    When a list value is assigned to an existing key, the new list is extended
    onto the existing list instead of replacing it.

    In the context of configparser, this allows for accumulating multiple values
    from different sections or repeated keys, such as in multiline requirements.

    Examples:
        >>> d = MultiOrderedDict()
        >>> d['key'] = [1, 2]
        >>> d['key'] = [3, 4]
        >>> d['key']
        [1, 2, 3, 4]
        >>> d['other'] = 'value'
        >>> d['other'] = 'new_value'  # Non-list values behave normally
        >>> d['other']
        'new_value'
    """

    def __setitem__(self, key, value):
        """Sets the value for the given key, extending lists if the key exists.

        Args:
            key: The dictionary key.
            value: The value to set. If this is a list and the key already exists,
                the list will be extended to the existing value instead of replacing it.
        """
        if isinstance(value, list) and key in self:
            self[key].extend(value)
        else:
            super().__setitem__(key, value)


def touch_file(path: str, fileinfo: dict):
    'upload-time: 2025-05-28T18:46:29.349478Z'
    time_str = fileinfo.get('upload-time')
    if not path or not time_str:
        return
    dt = dateutil.parser.parse(time_str)
    ts = dt.timestamp()
    os.utime(path, (ts, ts))
