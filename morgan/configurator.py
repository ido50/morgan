import argparse
import configparser
import os
import platform
import sys


def generate_env(name: str = "local"):
    """
    Generate a configuration block for the local client environment. This is
    an implementation of the PEP 345 specification of "Environment Markers".
    Resulting block is printed to standard output, and can either be copied to
    the configuration file, or piped to it using shell redirection (e.g. `>>`).
    """

    config = configparser.ConfigParser()
    config["env.{}".format(name)] = {
        'os_name': os.name,
        'sys_platform': sys.platform,
        'platform_machine': platform.machine(),
        'platform_python_implementation': platform.python_implementation(),
        'platform_system': platform.system(),
        'python_version': '.'.join(platform.python_version_tuple()[:2]),
        'python_full_version': platform.python_version(),
        'implementation_name': sys.implementation.name,
    }
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