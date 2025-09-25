import email.parser
import re
from typing import Dict, Set, Callable, BinaryIO, Iterable

from packaging.version import Version
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.specifiers import SpecifierSet
from packaging.markers import Marker, Variable as MarkerVariable
import tomli


METADATA_VERSION_11 = Version("1.1")
METADATA_VERSION_12 = Version("1.2")
METADATA_VERSION_21 = Version("2.1")


class MetadataParser:
    """
    MetadataParser is used to incrementally parse metadata sources from a Python
    package (which could be a wheel archive, a source archive, or just a
    directory). The major use of the class is to resolve dependencies of the
    package.

    The class supports several sources:
    - Metadata files compliant with Python's "core metadata specifications"
      (https://packaging.python.org/en/latest/specifications/core-metadata/),
      e.g. METADATA and PKG-INFO files.
    - The pyproject.toml file, as per PEP 621 (https://peps.python.org/pep-0621).
    - Setuptools-specific requires.txt and setup-requires.txt files
      (https://setuptools.pypa.io/en/latest/deprecated/python_eggs.html#requires-txt)

    Attributes:
    -----------
    source_path : str
        The name of the package archive that the object was
        created to parse.
    name : str
        The name of the package, in canonicalized form
    version : packaging.version.Version
        The version of the package
    python_requirement : packaging.specifiers.SpecifierSet
        A specification of the Python versions supported by the package.
    extras_provided : Set[str]
        Extras provided by the package.
    core_dependencies: Set[packaging.requirements.Requirement]
        Core dependencies of the package.
    optional_dependencies: Dict[str, Set[packaging.requirements.Requirement]]
        Optional dependencies of the package. A dictionary whose keys are
        either names of extras (from extras_provided) or environment marker
        constraints (e.g. :python_version<2.7).
    build_dependencies : Set[packaging.requirements.Requirement]
        Dependencies required to build the package.
    """

    def __init__(self, source_path: str):
        """
        Object constructor.

        Parameters:
        -----------
        filename : str
            The name of the package archive that the object
            was created to parse.

        """

        self.source_path: str = source_path
        self.name: str = None
        self.version: Version = None
        self.python_requirement: SpecifierSet = None
        self.extras_provided: Set[str] = set()
        self.core_dependencies: Set[Requirement] = set()
        self.optional_dependencies: Dict[str, Set[Requirement]] = {}
        self.build_dependencies: Set[Requirement] = set()

    def parse(
        self,
        opener: Callable[[str], BinaryIO],
        filename: str,
    ):
        """
        Parses a file, gathering whatever metadata can be gathered from it. Any
        file can be provided to the method, irrelevant files are simply ignored.

        Parameters
        ----------
        opener : Callable[[str], BinaryIO]
            A function that can be used to open the file. The function takes one
            parameter, which is the file name, and returns a file object opened
            in binary mode.
        filename : str
            The file name that will be provided to the opener function. This can
            either be relative or absolute, so long as the opener function can
            open it. The name is important, as the method uses it to determine
            the kind of file it is.
        """

        parse_func = None
        main_metadata_file = False

        if re.search(r"\.whl$", self.source_path):
            if re.fullmatch(r"[^/]+\.dist-info/METADATA", filename):
                parse_func = self._parse_metadata_file
                main_metadata_file = True
        elif re.search(r"\.zip$", self.source_path):
            if re.fullmatch(r"([^/]+/)?PKG-INFO", filename):
                parse_func = self._parse_metadata_file
                main_metadata_file = True
        elif re.search(r"\.tar\.gz$", self.source_path):
            if re.fullmatch(r"[^/]+/PKG-INFO", filename):
                parse_func = self._parse_metadata_file
                main_metadata_file = True
            elif re.fullmatch(r"[^/]+(/[^/]+)?\.egg-info/(setup_)?requires.txt", filename):
                parse_func = self._parse_requirestxt
            elif re.fullmatch(r"[^/]+/pyproject.toml", filename):
                parse_func = self._parse_pyproject

        if parse_func:
            with opener(filename) as fp:
                if main_metadata_file:
                    self._metadata_file = fp.read()
                    fp.seek(0)
                parse_func(fp)

    def seen_metadata_file(self) -> bool:
        """
        Returns a boolean value if the archive's main METADATA file has already
        been read.
        """
        return hasattr(self, "_metadata_file")

    def write_metadata_file(self, target: str):
        """
        Writes the archive's main METADATA file to the target filepath, provided
        such a file was already read. The contents of the target file will be
        clobbered, if already existing. If the main metadata file has not been
        read yet, an exception will be raised.
        """
        if not hasattr(self, "_metadata_file"):
            raise Exception("Main METADATA file has not been read yet")

        with open(target, "wb") as out:
            out.write(self._metadata_file)

    def dependencies(
        self,
        extras: Set[str],
        envs: Iterable[Dict]
    ) -> Set[Requirement]:
        """
        Resolves the dependencies of the package, returning a set of
        requirements. Only requirements that are relevant to the provided extras
        and environments are returned.

        Parameters
        ----------
        extras : Set[str] = set()
            A set of extras that the package was required with. For example, if
            the instance of this class is used to parse the metadata of the
            package "pymongo", and the requirement string for that package was
            "pymongo[snappy,zstd]", then the set of extras will be (snappy, zstd).
        envs: Iterable[Dict] = []
            The list of environments for which Morgan is downloading package
            distributions. These are simple dictionaries whose keys match those
            defined by the "Environment Markers" section of PEP 508.

        Returns
        -------
        A set of packaging.requirements.Requirement objects.
        """

        deps = set()
        deps |= self.core_dependencies
        deps |= self.build_dependencies

        for extra in self.optional_dependencies:
            if ":" in extra:
                # this dependency includes a set of environment marker
                # specifications
                orig = extra
                (extra, spec) = extra.split(":")
                if extra and extra not in extras:
                    continue
                marker = Marker(spec)
                for env in envs:
                    if marker.evaluate(env):
                        deps |= self.optional_dependencies[orig]
                        break
            elif extra in extras:
                deps |= self.optional_dependencies[extra]

        irrelevant_deps = set()
        for dep in deps:
            relevant = True
            if dep.marker:
                relevant = False
                for env in envs:
                    env["extra"] = ",".join(extras)
                    if dep.marker.evaluate(env):
                        relevant = True
                        break

            if not relevant:
                irrelevant_deps.add(dep)
                continue

        deps -= irrelevant_deps

        return deps

    def _add_core_requirements(self, reqs):
        self.core_dependencies |= set([Requirement(dep) for dep in reqs])

    def _add_optional_requirements(self, extra, reqs):
        if extra not in self.optional_dependencies:
            self.optional_dependencies[extra] = set()
        self.optional_dependencies[extra] |= set(
            [Requirement(dep) for dep in reqs])

    def _parse_pyproject(self, fp):
        data = tomli.load(fp)
        project = data.get("project")

        if project is not None:
            (name, version) = (project.get("name"), project.get("version"))

            if name is not None:
                self.name = canonicalize_name(name)

            if version is not None:
                self.version = Version(version)

            if "requires-python" in project:
                self.python_requirement = SpecifierSet(
                    project["requires-python"])

            if "dependencies" in project:
                self._add_core_requirements(project["dependencies"])

            if "optional-dependencies" in project:
                for extra in project["optional-dependencies"]:
                    self._add_optional_requirements(
                        extra, project["optional-dependencies"][extra])

        build_system = data.get("build-system")
        if build_system is not None and "requires" in build_system:
            self.build_dependencies |= set(
                [Requirement(req) for req in build_system["requires"]])

    def _parse_metadata_file(self, fp):
        data = email.parser.BytesParser().parse(fp, True)

        (name, version, metadata_version) = (data.get("Name"),
                                             data.get("Version"),
                                             data.get("Metadata-Version"))
        if metadata_version is None:
            return

        metadata_version = Version(metadata_version)

        if name is not None:
            self.name = canonicalize_name(name)
        if version is not None:
            self.version = Version(version)

        if metadata_version >= METADATA_VERSION_21:
            self._parse_metadata_21(data)
        if metadata_version >= METADATA_VERSION_12:
            self._parse_metadata_12(data)
        elif metadata_version == METADATA_VERSION_11:
            self._parse_metadata_11(data)

    def _parse_metadata_21(self, data):
        provides_extra = data.get_all("Provides-Extra")
        if provides_extra is not None:
            self.extras_provided |= set(provides_extra)

    def _parse_metadata_12(self, data):
        requires_python = data.get("Requires-Python")
        if requires_python is not None:
            self.python_requirement = SpecifierSet(requires_python)

        requires_dist = data.get_all("Requires-Dist")
        if requires_dist is not None:
            for requirement_str in requires_dist:
                req = Requirement(requirement_str)
                extra = None
                if req.marker is not None:
                    for marker in req.marker._markers:
                        if isinstance(marker[0], MarkerVariable) and \
                                marker[0].value == "extra":
                            extra = marker[2].value
                            break

                if extra:
                    if extra not in self.optional_dependencies:
                        self.optional_dependencies[extra] = set()
                    self.optional_dependencies[extra].add(req)
                else:
                    self.core_dependencies.add(req)

    def _parse_metadata_11(self, data):
        requires = data.get_all("Requires")
        if requires is not None:
            for requirement_str in requires:
                self.core_dependencies.add(Requirement(requirement_str))

    def _parse_requirestxt(self, fp):
        section = None
        content = []
        for line in fp.readlines():
            line = line.strip().decode("UTF-8")
            if line.startswith("["):
                if line.endswith("]"):
                    if section or content:
                        if section:
                            self._add_optional_requirements(section, content)
                        elif fp.name.endswith("setup_requires.txt"):
                            self._add_build_requirements(content)
                        else:
                            self._add_core_requirements(content)
                    section = line[1:-1]
                    content = []
                else:
                    raise ValueError("Invalid section heading", line)
            elif line:
                content.append(line)

        if section:
            self._add_optional_requirements(section, content)
        elif fp.name.endswith("setup_requires.txt"):
            self._add_build_requirements(content)
        else:
            self._add_core_requirements(content)
