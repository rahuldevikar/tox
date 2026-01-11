"""PEP 751 pylock.toml lock file support for tox."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if sys.version_info >= (3, 11):  # pragma: >=3.11 cover
    import tomllib
else:  # pragma: <3.11 cover
    import tomli as tomllib

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

if TYPE_CHECKING:
    from argparse import Namespace


class PylockFile:
    """Parser for PEP 751 pylock.toml lock files."""

    def __init__(self, path: Path) -> None:
        """
        Initialize the pylock.toml parser.

        :param path: Path to the pylock.toml file
        """
        self._path = path
        self._data: dict[str, Any] | None = None
        self._requirements: list[Requirement] | None = None

    @property
    def path(self) -> Path:
        """Get the path to the lock file."""
        return self._path

    def _ensure_loaded(self) -> None:
        """Load and parse the pylock.toml file if not already loaded."""
        if self._data is not None:
            return

        if not self._path.exists():
            msg = f"Lock file not found: {self._path}"
            raise FileNotFoundError(msg)

        with self._path.open("rb") as f:
            self._data = tomllib.load(f)

        # Validate lock file version
        lock_version = self._data.get("lock-version")
        if lock_version is None:
            msg = "Lock file missing required 'lock-version' field"
            raise ValueError(msg)

        # Support version 1.x
        if not lock_version.startswith("1."):
            msg = f"Unsupported lock file version: {lock_version}, expected 1.x"
            raise ValueError(msg)

    def _check_compatibility(self, current_python: tuple[int, ...]) -> None:
        """
        Check if lock file is compatible with current Python version.

        :param current_python: Current Python version as a tuple (major, minor, ...)
        """
        self._ensure_loaded()
        assert self._data is not None

        requires_python = self._data.get("requires-python")
        if requires_python:
            spec = SpecifierSet(requires_python)
            version_str = ".".join(str(v) for v in current_python[:3])
            if not spec.contains(version_str):
                msg = f"Lock file requires Python {requires_python}, but current is {version_str}"
                raise ValueError(msg)

    def get_requirements(
        self,
        *,
        extras: set[str] | None = None,
        dependency_groups: set[str] | None = None,
        python_version: tuple[int, ...] | None = None,
    ) -> list[Requirement]:
        """
        Extract installable requirements from the lock file.

        :param extras: Set of extras to install (default: empty set)
        :param dependency_groups: Set of dependency groups to install (default: from default-groups)
        :param python_version: Python version tuple for marker evaluation (default: current)
        :return: List of requirements to install
        """
        self._ensure_loaded()
        assert self._data is not None

        if python_version is None:
            python_version = sys.version_info[:3]

        # Check compatibility
        self._check_compatibility(python_version)

        # Set up marker environment
        if extras is None:
            extras = set()

        if dependency_groups is None:
            dependency_groups = set(self._data.get("default-groups", []))

        # Build requirements list from packages
        requirements: list[Requirement] = []
        packages = self._data.get("packages", [])

        for pkg in packages:
            # Check if package should be included based on markers
            if not self._should_install_package(pkg, extras, dependency_groups):
                continue

            # Check requires-python constraint
            pkg_requires_python = pkg.get("requires-python")
            if pkg_requires_python:
                spec = SpecifierSet(pkg_requires_python)
                version_str = ".".join(str(v) for v in python_version)
                if not spec.contains(version_str):
                    continue

            # Build requirement from package info
            req_str = self._build_requirement_string(pkg)
            if req_str:
                requirements.append(Requirement(req_str))

        return requirements

    def _should_install_package(
        self,
        pkg: dict[str, Any],
        extras: set[str],
        dependency_groups: set[str],
    ) -> bool:
        """
        Determine if a package should be installed based on its marker.

        :param pkg: Package dictionary from lock file
        :param extras: Requested extras
        :param dependency_groups: Requested dependency groups
        :return: True if package should be installed
        """
        marker_str = pkg.get("marker")
        if not marker_str:
            return True

        # Parse and evaluate marker with extended syntax for extras and dependency_groups
        # For now, we'll do basic marker evaluation
        # TODO: Implement full PEP 751 marker syntax with 'in extras' and 'in dependency_groups'
        try:
            marker = Marker(marker_str)
            # Standard marker evaluation (platform, python_version, etc.)
            return marker.evaluate()
        except Exception:  # noqa: BLE001
            # If marker can't be evaluated (e.g., uses PEP 751 extensions), be conservative
            return True

    def _build_requirement_string(self, pkg: dict[str, Any]) -> str | None:
        """
        Build a requirement string from package info.

        For now, we build basic requirements. Full support would need:
        - Wheel selection based on platform
        - Handling VCS, directory, archive sources
        - Proper URL construction

        :param pkg: Package dictionary from lock file
        :return: Requirement string or None
        """
        name = pkg.get("name")
        if not name:
            return None

        version = pkg.get("version")
        if version:
            return f"{name}=={version}"

        # Without version (e.g., VCS packages), return name only
        return name

    def get_hash_options(self) -> list[str]:
        """
        Get hash options for pip install.

        :return: List of hash options (e.g., ['--require-hashes'])
        """
        # For security, we could enforce hash checking
        # This would require proper hash extraction from wheels/sdist entries
        return []

    @property
    def lock_version(self) -> str:
        """Get the lock file version."""
        self._ensure_loaded()
        assert self._data is not None
        return self._data["lock-version"]

    @property
    def created_by(self) -> str:
        """Get the tool that created the lock file."""
        self._ensure_loaded()
        assert self._data is not None
        return self._data.get("created-by", "unknown")


class PylockDeps:
    """Wrapper for pylock.toml that behaves like PythonDeps for tox integration."""

    def __init__(self, path: Path, root: Path) -> None:  # noqa: ARG002
        """
        Initialize pylock dependencies.

        :param path: Path to pylock.toml file (relative or absolute)
        :param root: Root directory for resolving relative paths
        """
        self._path = path if path.is_absolute() else root / path
        self._pylock = PylockFile(self._path)
        self._requirements: list[Requirement] | None = None

    @property
    def path(self) -> Path:
        """Get the lock file path."""
        return self._path

    @property
    def requirements(self) -> list[Requirement]:
        """Get requirements from lock file."""
        if self._requirements is None:
            self._requirements = self._pylock.get_requirements()
        return self._requirements

    @property
    def as_root_args(self) -> list[str]:
        """Convert to pip install arguments."""
        # For now, convert to individual requirement args
        # Future: could use --constraint with hash checking
        return [str(req) for req in self.requirements]

    @property
    def options(self) -> Namespace:
        """Get installation options (empty for lock files)."""
        from argparse import Namespace  # noqa: PLC0415

        return Namespace()

    def unroll(self) -> tuple[list[str], list[str]]:
        """
        Unroll dependencies into options and requirements.

        :return: Tuple of (options, requirements) as string lists
        """
        req_strings = [str(req) for req in self.requirements]
        return [], req_strings


__all__ = [
    "PylockDeps",
    "PylockFile",
]
