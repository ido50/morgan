import argparse
import configparser
import hashlib
import json
import os
import os.path
import re
import tarfile
import traceback
from typing import Iterable, Tuple, Dict
import urllib.parse
import urllib.request
import zipfile

import packaging.requirements
import packaging.version
import packaging.utils
import packaging.tags
import packaging.specifiers

from morgan import server, configurator, metadata
from morgan.__about__ import __version__

PYPI_ADDRESS = "https://pypi.org/simple/"
PREFERRED_HASH_ALG = "sha256"


class Mirrorer:
    """
    Mirrorer is a class that implements the mirroring capabilities of Morgan.
    A class is used to maintain state, as the mirrorer needs to keep track of
    packages it already processed in the (very common) case that it encounters
    them again as dependencies.
    """

    def __init__(self, index_path: str):
        """
        The constructor only needs to path to the package index.
        """

        # load the configuration from the index_path, and parse the environments
        # into representations that are easier for the mirrorer to work with
        self.index_path = index_path
        self.config = configparser.ConfigParser()
        self.config.read(os.path.join(self.index_path, "morgan.ini"))
        self.envs = {}
        self._supported_pyversions = []
        self._supported_platforms = []
        for key in self.config:
            m = re.fullmatch(r"env\.(.+)", key)
            if m:
                env = self.config[key]
                env['platform_release'] = ''
                env['platform_version'] = ''
                env['implementation_version'] = ''
                env['extra'] = ''
                self.envs[m.group(1)] = dict(env)
                self._supported_pyversions.append(env["python_version"])
                self._supported_platforms.append(
                    re.compile(r".*" +
                               env["sys_platform"] +
                               r".*" +
                               env["platform_machine"]))

        self._processed_pkgs = {}

    def mirror(self, requirement_string: str):
        """
        Mirror a package according to a PEP 508-compliant requirement string.
        """

        requirement = parse_requirement(requirement_string)

        deps = self._mirror(requirement)
        if deps is None:
            return

        while len(deps) > 0:
            next_deps = {}
            for dep in deps:
                more_deps = self._mirror(
                    deps[dep]["requirement"],
                    required_by=deps[dep]["required_by"],
                )
                if more_deps:
                    next_deps.update(more_deps)
            deps = next_deps.copy()

    def copy_server(self):
        """
        Copy the server script to the package index. This method will first
        attempt to find the server file directly, and if that fails, it will
        use the inspect module to get the source code.
        """

        print("Copying server script")
        thispath = os.path.realpath(__file__)
        serverpath = os.path.join(os.path.dirname(thispath), "server.py")
        outpath = os.path.join(self.index_path, "server.py")
        if os.path.exists(serverpath):
            with open(serverpath, "rb") as inp, open(outpath, "wb") as out:
                out.write(inp.read())
        else:
            import inspect
            with open(outpath, "w") as out:
                out.write(inspect.getsource(server))

    def _mirror(
        self,
        requirement: packaging.requirements.Requirement,
        required_by: packaging.requirements.Requirement = None,
    ) -> dict:
        if requirement.name in self._processed_pkgs:
            return None

        if required_by:
            print("[{}]: {}".format(required_by, requirement))
        else:
            print("{}".format(requirement))

        data: dict = None

        # get information about this package from the Simple API in JSON
        # format as per PEP 691
        request = urllib.request.Request(
            "{}{}/".format(PYPI_ADDRESS, requirement.name),
            headers={
                'Accept': 'application/vnd.pypi.simple.v1+json',
            },
        )

        with urllib.request.urlopen(request) as response:
            data = json.load(response)

        if data["meta"]["api-version"] != "1.0":
            raise Exception(
                "Unsupported metadata version {}, only support 1.0".format(
                    data["meta"]["api-version"]))

        files = data["files"]
        if files is None or not isinstance(files, list):
            raise Exception(
                "Expected response to contain a list of 'files'")

        # filter and enrich files
        files = self._filter_files(requirement, files)
        if files is None:
            if required_by is None:
                raise Exception("No files match requirement")
            else:
                # this is a dependency, assume the dependency is not relevant
                # for any of our environments and don't return an error
                return None

        # download all files
        depdict = {}
        for file in files:
            try:
                file_deps = self._process_file(requirement, file)
                if file_deps:
                    depdict.update(file_deps)
            except Exception:
                print("\tFailed processing file {}, skipping it".format(
                    file["filename"]))
                traceback.print_exc()
                continue

        self._processed_pkgs[requirement.name] = True

        return depdict

    def _filter_files(
        self,
        requirement: packaging.requirements.Requirement,
        files: Iterable[dict],
    ) -> Iterable[dict]:
        # remove files with unsupported extensions
        files = list(filter(lambda file: re.search(
            r"\.(whl|zip|tar.gz)$", file["filename"]), files))

        # parse versions and platform tags for each file
        for file in files:
            try:
                if re.search(r"\.whl$", file["filename"]):
                    _, file["version"], ___, file["tags"] = \
                        packaging.utils.parse_wheel_filename(
                            file["filename"])
                    file["is_wheel"] = True
                elif re.search(r"\.(tar\.gz|zip)$", file["filename"]):
                    _, file["version"] = packaging.utils.parse_sdist_filename(
                        file["filename"])
                    file["is_wheel"] = False
                    file["tags"] = None
            except packaging.version.InvalidVersion:
                # ignore files with invalid version, PyPI no longer allows
                # packages with special versioning schemes, and we assume we
                # can ignore such files
                continue
            except Exception:
                print("\tSkipping file {}, exception caught".format(
                    file["filename"]))
                traceback.print_exc()
                continue

        # sort all files by version in reverse order, and ignore yanked files
        files = list(filter(lambda file: "version" in file and
                            not file.get("yanked", False), files))
        files.sort(key=lambda file: file["version"], reverse=True)

        # keep only files of the latest version that satisfies the
        # requirement (if requirement doesn't have any version specifiers,
        # take latest available version)
        if requirement.specifier is not None:
            files = list(filter(
                lambda file: requirement.specifier.contains(
                    file["version"]),
                files))

        if len(files) == 0:
            print("Skipping {}, no version matches requirement".format(
                requirement.name))
            return None

        latest_version = files[0]["version"]
        files = list(filter(
            lambda file: file["version"] == latest_version, files))

        # now we only have files from the latest version that satisfies the
        # requirement. we need to filter out files that do not match any of
        # our environments
        files = list(filter(
            lambda file: self._should_download(file), files))

        return files

    def _should_download(self, fileinfo: dict) -> bool:
        if fileinfo.get("requires-python", None):
            spec_set = packaging.specifiers.SpecifierSet(
                fileinfo["requires-python"])
            supported = False
            for supported_python in self._supported_pyversions:
                if spec_set.contains(supported_python):
                    supported = True
                    break
            if not supported:
                return False

        if fileinfo.get("tags", None):
            for tag in fileinfo["tags"]:
                (intrp_name, intrp_ver) = parse_interpreter(tag.interpreter)
                if intrp_name not in ("py", "cp"):
                    continue
                if (intrp_ver and
                        intrp_ver != "3" and
                        intrp_ver not in self._supported_pyversions):
                    continue

                if tag.platform == "any":
                    return True
                else:
                    for platformre in self._supported_platforms:
                        if platformre.fullmatch(tag.platform):
                            return True
            return False

        return True

    def _process_file(
        self,
        requirement: packaging.requirements.Requirement,
        fileinfo: dict,
    ) -> Dict[str, packaging.requirements.Requirement]:
        filepath = os.path.join(
            self.index_path, requirement.name, fileinfo["filename"])
        hashalg = PREFERRED_HASH_ALG\
            if PREFERRED_HASH_ALG in fileinfo["hashes"]\
            else fileinfo["hashes"].keys()[0]

        self._download_file(fileinfo, filepath, hashalg)

        md = self._extract_metadata(
            filepath, requirement.name, fileinfo["version"])

        deps = md.dependencies(requirement.extras, self.envs.values())
        if deps is None:
            return None

        depdict = {}
        for dep in deps:
            dep.name = packaging.utils.canonicalize_name(dep.name)
            depdict[dep.name] = {
                'requirement': dep,
                'required_by': requirement,
            }
        return depdict

    def _download_file(
        self,
        fileinfo: dict,
        target: str,
        hashalg: str,
    ) -> bool:
        exphash = fileinfo["hashes"][hashalg]

        os.makedirs(os.path.dirname(target), exist_ok=True)

        # if target already exists, verify its hash and only download if
        # there's a mismatch
        if os.path.exists(target):
            truehash = self._hash_file(target, hashalg)
            if truehash == exphash:
                return True

        print("\t{}...".format(fileinfo["url"]), end=" ")
        with urllib.request.urlopen(fileinfo["url"]) as inp,\
                open(target, "wb") as out:
            out.write(inp.read())
        print("done")

        truehash = self._hash_file(target, hashalg)
        if truehash != exphash:
            raise Exception(
                "Digest mismatch for {}".format(fileinfo["filename"]))

        return True

    def _hash_file(self, filepath: str, hashalg: str) -> str:
        contents = None
        with open(filepath, "rb") as fh:
            # verify downloaded file has same hash
            contents = fh.read()

        truehash = hashlib.new(hashalg)
        truehash.update(contents)

        with open("{}.hash".format(filepath), "w") as out:
            out.write("{}={}".format(hashalg, truehash.hexdigest()))

        return truehash.hexdigest()

    def _extract_metadata(
        self,
        filepath: str,
        package: str,
        version: packaging.version.Version,
    ) -> metadata.MetadataParser:
        md = metadata.MetadataParser(filepath)

        archive = None
        members = None
        opener = None

        if re.search(r"\.(whl|zip)$", filepath):
            archive = zipfile.ZipFile(filepath)
            members = [member.filename for member in archive.infolist()]
            opener = archive.open
        elif re.search(r"\.tar.gz$", filepath):
            archive = tarfile.open(filepath)
            members = [member.name for member in archive.getmembers()]
            opener = archive.extractfile
        else:
            raise Exception("Unexpected distribution file {}".format(filepath))

        for member in members:
            try:
                md.parse(opener, member)
            except Exception as e:
                print("Failed parsing member {} of {}: {}".format(
                    member, filepath, e))

        if md.seen_metadata_file():
            md.write_metadata_file("{}.metadata".format(filepath))

        archive.close()

        return md


def parse_interpreter(inp: str) -> Tuple[str, str]:
    """
    Parse interpreter tags in the name of a binary wheel file. Returns a tuple
    of interpreter name and optional version, which will either be <major> or
    <major>.<minor>.
    """

    m = re.fullmatch(r"^([^\d]+)(?:(\d)(?:[._])?(\d+)?)$", inp)
    if m is None:
        return (inp, None)

    intr = m.group(1)
    version = None
    if m.lastindex > 1:
        version = m.group(2)
        if m.lastindex > 2:
            version = "{}.{}".format(version, m.group(3))

    return (intr, version)


def parse_requirement(req_string: str) -> packaging.requirements.Requirement:
    """
    Parse a requirement string into a packaging.requirements.Requirement object.
    Also canonicalizes (or "normalizes") the name of the package.
    """

    req = packaging.requirements.Requirement(req_string)
    req.name = packaging.utils.canonicalize_name(req.name)
    return req


def mirror(index_path: str):
    """
    Run the mirror on the package index in the provided path, and based on the
    morgan.ini configuration file in the index. Copies the server script to the
    index at the end of the process. This function can safely be called multiple
    times on the same index path, files are only downloaded if necessary.
    """

    m = Mirrorer(index_path)
    for package in m.config["requirements"]:
        m.mirror("{}{}".format(package, m.config["requirements"][package]))
    m.copy_server()


def main():
    """
    Executes the command line interface of Morgan. Use -h for a full list of
    flags, options and arguments.
    """

    parser = argparse.ArgumentParser(
        description='Morgan: PyPI Mirror for Restricted Environments')

    parser.add_argument(
        '-i', '--index-path',
        dest='index_path',
        default=os.getcwd(),
        help='Path to the package index')

    server.add_arguments(parser)
    configurator.add_arguments(parser)

    parser.add_argument(
        "command",
        choices=["generate_env", "generate_reqs", "mirror", "serve",
            "copy_server", "version"],
        help="Command to execute")

    args = parser.parse_args()

    if args.command == "serve":
        server.run(args.index_path, args.host, args.port)
    elif args.command == "generate_env":
        configurator.generate_env(args.env)
    elif args.command == "generate_reqs":
        configurator.generate_reqs(args.mode)
    elif args.command == "mirror":
        mirror(args.index_path)
    elif args.command == "copy_server":
        Mirrorer(args.index_path).copy_server()
    elif args.command == "version":
        print("Morgan v{}".format(__version__))

if __name__ == "__main__":
    main()
