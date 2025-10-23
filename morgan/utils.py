import os
import re
from typing import Dict, Iterable, Optional, Set

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


def is_requirement_relevant(
    requirement: Requirement, envs: Iterable[Dict], extras: Optional[Set[str]] = None
) -> bool:
    """Determines if a requirement is relevant for any of the provided environments.

    Args:
        requirement: The requirement to evaluate.
        envs: The environments to check against.
        extras: Optional extras to consider during evaluation.

    Returns:
        True if the requirement has no marker or if its marker evaluates to
        True for at least one environment, False otherwise.
    """
    if not requirement.marker:
        return True

    # If no environments specified, assume relevant
    if not envs:
        return True

    for env in envs:
        # Create a copy of the environment to avoid modifying the original
        env_copy = env.copy()
        env_copy.setdefault("extra", "")
        if extras:
            env_copy["extra"] = ",".join(extras)

        if requirement.marker.evaluate(env_copy):
            return True

    return False


def filter_relevant_requirements(
    requirements: Iterable[Requirement],
    envs: Iterable[Dict],
    extras: Optional[Set[str]] = None,
) -> Set[Requirement]:
    """Filters a collection of requirements to only those relevant for the provided environments.

    Args:
        requirements: Requirements to filter.
        envs: The environments to check against.
        extras: Optional extras to consider during evaluation.

    Returns:
        Set of requirements relevant for at least one environment.
    """
    return {req for req in requirements if is_requirement_relevant(req, envs, extras)}


def touch_file(path: str, fileinfo: dict):
    "upload-time: 2025-05-28T18:46:29.349478Z"
    time_str = fileinfo.get("upload-time")
    if not path or not time_str:
        return
    dt = dateutil.parser.parse(time_str)
    ts = dt.timestamp()
    os.utime(path, (ts, ts))
