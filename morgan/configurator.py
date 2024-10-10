import argparse
from collections import OrderedDict
import configparser
import os
import platform
import sys
import sysconfig

from packaging.version import Version

if Version(platform.python_version()) < Version('3.8'):
    import importlib_metadata as metadata
else:
    import importlib.metadata as metadata


def generate_env(name: str = "local"):
    """
    Generate a configuration block for the local client environment. This is
    an implementation of the PEP 508 specification of "Environment Markers".
    Resulting block is printed to standard output, and can either be copied to
    the configuration file, or piped to it using shell redirection (e.g. `>>`).
    """

    config = configparser.ConfigParser()
    config["env.{}".format(name)] = {
        'os_name': os.name,
        'platform_tag': sysconfig.get_platform(),
        'sys_platform': sys.platform,
        'platform_machine': platform.machine(),
        'platform_python_implementation': platform.python_implementation(),
        'platform_system': platform.system(),
        'python_version': '.'.join(platform.python_version_tuple()[:2]),
        'python_full_version': platform.python_version(),
        'implementation_name': sys.implementation.name,
    }
    config.write(sys.stdout)


def generate_reqs(mode: str = ">="):
    """
    Generate a requirements configuration block from current environment.

    The requirements block is printed to standard output,
    and can either be copied to the configuration file, or piped to it
    using shell redirection (e.g. `>>`).

    Args:
        mode (str, optional):
            Mode to use for versioning. Use "==" for exact versioning,
            ">=" for minimum versioning, or "<=" for maximum versioning.
            Defaults to ">=".
    """
    requirements = {dist.metadata["Name"].lower(): f"{mode}{dist.version}"
                    for dist in metadata.distributions()}
    config = configparser.ConfigParser()
    config["requirements"] = OrderedDict(sorted(requirements.items()))
    config.write(sys.stdout)


def add_arguments(parser: argparse.ArgumentParser):
    """
    Adds command line options specific to this script to an argument parser.
    """

    parser.add_argument(
        '-e', '--env',
        dest='env',
        help='Name of environment to configure'
    )

    parser.add_argument(
        '-m', '--mode',
        dest='mode',
        choices=['>=', '==', '<='],
        default=">=",
        help='Versioning mode for requirements',
    )
