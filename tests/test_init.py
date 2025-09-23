import argparse
import hashlib
import os
import tempfile

import pytest
from pathlib import Path

from morgan import PYPI_ADDRESS, Mirrorer, parse_interpreter, parse_requirement, server


class TestParseInterpreter:
    @pytest.mark.parametrize(
        "interpreter_string, expected_name, expected_version",
        [
            ("cp38", "cp", "3.8"),
            ("cp3", "cp", "3"),
            ("cp310", "cp", "3.10"),
            ("cp3_10", "cp", "3.10"),
            ("py38", "py", "3.8"),
            ("something_strange", "something_strange", None),
        ],
        ids=[
            "typical_cpython",
            "cpython_no_minor_version",
            "cpython_two_digit_minor",
            "cpython_with_underscore",
            "generic_python",
            "unrecognized_format",
        ],
    )
    def test_parse_interpreter_components(
        self, interpreter_string, expected_name, expected_version
    ):
        name, version = parse_interpreter(interpreter_string)
        assert name == expected_name
        assert version == expected_version


class TestParseRequirement:
    def test_parse_basic_requirement(self):
        req = parse_requirement("requests")
        assert req.name == "requests"
        assert str(req.specifier) == ""
        assert not req.extras

    def test_parse_versioned_requirement(self):
        req = parse_requirement("requests>=2.0.0")
        assert req.name == "requests"
        assert str(req.specifier) == ">=2.0.0"
        assert not req.extras

    def test_parse_requirement_with_extras(self):
        req = parse_requirement("requests[security,socks]>=2.0.0")
        assert req.name == "requests"
        assert str(req.specifier) == ">=2.0.0"
        assert set(req.extras) == {"security", "socks"}

    def test_normalize_package_name(self):
        req = parse_requirement("Requests-HTTP")
        assert req.name == "requests-http"


class TestMirrorer:
    @pytest.fixture
    def temp_index_path(self, tmpdir):
        # Create minimal config file
        config_path = os.path.join(tmpdir, "morgan.ini")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                """
                [env.test_env]
                python_version = 3.10
                sys_platform = linux
                platform_machine = x86_64
                platform_tag = manylinux

                [requirements]
                requests = >=2.0.0
                """
            )
        yield tmpdir

    def test_mirrorer_initialization(self, temp_index_path):
        args = argparse.Namespace(
            index_path=temp_index_path,
            index_url="https://pypi.org/simple/",
            config=os.path.join(temp_index_path, "morgan.ini"),
        )

        mirrorer = Mirrorer(args)

        assert mirrorer.index_path == temp_index_path
        assert mirrorer.index_url == "https://pypi.org/simple/"
        assert "test_env" in mirrorer.envs
        assert mirrorer.envs["test_env"]["python_version"] == "3.10"
        assert mirrorer.envs["test_env"]["sys_platform"] == "linux"
        assert mirrorer.envs["test_env"]["platform_machine"] == "x86_64"

    def test_server_file_copying(self, temp_index_path):
        args = argparse.Namespace(
            index_path=temp_index_path,
            index_url=PYPI_ADDRESS,
            config=os.path.join(temp_index_path, "morgan.ini"),
        )
        mirrorer = Mirrorer(args)

        mirrorer.copy_server()

        expected_serverpath = os.path.join(temp_index_path, "server.py")
        assert os.path.exists(
            expected_serverpath
        ), "server.py should be copied to index_path"

        with open(server.__file__, "rb") as original_server, open(
            expected_serverpath, "rb"
        ) as copied_server:
            assert (
                original_server.read() == copied_server.read()
            ), "Copied file should match source"

    def test_file_hashing(self, temp_index_path):
        args = argparse.Namespace(
            index_path=temp_index_path,
            index_url=PYPI_ADDRESS,
            config=os.path.join(temp_index_path, "morgan.ini"),
        )
        mirrorer = Mirrorer(args)

        test_data = b"test content for hashing"
        test_file = os.path.join(temp_index_path, "test_artifact.whl")
        with open(test_file, "wb") as file:
            file.write(test_data)

        expected_hash = hashlib.sha256(test_data).hexdigest()

        # noqa: SLF001 # pylint: disable=W0212
        digest = mirrorer._hash_file(test_file, "sha256")

        assert digest == expected_hash, "Returned hash should match sha256 digest"
        hash_file = test_file + ".hash"
        assert os.path.exists(hash_file), "Hash file should be created"
        with open(hash_file, "r", encoding="utf-8") as file:
            assert (
                file.read() == f"sha256={expected_hash}"
            ), "Hash file content should be correctly formatted"
