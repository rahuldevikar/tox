"""Tests for PEP 751 pylock.toml support."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tox.tox_env.python.pip.pylock import PylockDeps, PylockFile

if TYPE_CHECKING:
    from tox.pytest import ToxProjectCreator


@pytest.fixture()
def simple_lock_file(tmp_path: Path) -> Path:
    """Create a simple pylock.toml file for testing."""
    lock_content = """lock-version = "1.0"
requires-python = ">=3.8"
created-by = "test"

[[packages]]
name = "requests"
version = "2.31.0"

[[packages]]
name = "urllib3"
version = "2.0.7"

[[packages]]
name = "certifi"
version = "2023.7.22"
"""
    lock_file = tmp_path / "pylock.toml"
    lock_file.write_text(lock_content)
    return lock_file


@pytest.fixture()
def lock_file_with_markers(tmp_path: Path) -> Path:
    """Create a pylock.toml file with environment markers."""
    lock_content = """lock-version = "1.0"
requires-python = ">=3.8"
created-by = "test"

[[packages]]
name = "colorama"
version = "0.4.6"
marker = "sys_platform == 'win32'"

[[packages]]
name = "pytest"
version = "7.4.0"
"""
    lock_file = tmp_path / "pylock.toml"
    lock_file.write_text(lock_content)
    return lock_file


def test_pylock_file_load(simple_lock_file: Path) -> None:
    """Test basic loading of a pylock.toml file."""
    pylock = PylockFile(simple_lock_file)
    
    assert pylock.lock_version == "1.0"
    assert pylock.created_by == "test"


def test_pylock_file_not_found() -> None:
    """Test that FileNotFoundError is raised for missing files."""
    pylock = PylockFile(Path("/nonexistent/pylock.toml"))
    
    with pytest.raises(FileNotFoundError, match="Lock file not found"):
        _ = pylock.lock_version


def test_pylock_file_invalid_version(tmp_path: Path) -> None:
    """Test that ValueError is raised for unsupported versions."""
    lock_file = tmp_path / "pylock.toml"
    lock_file.write_text('lock-version = "2.0"\ncreated-by = "test"')
    
    pylock = PylockFile(lock_file)
    
    with pytest.raises(ValueError, match="Unsupported lock file version"):
        _ = pylock.lock_version


def test_pylock_file_missing_version(tmp_path: Path) -> None:
    """Test that ValueError is raised when lock-version is missing."""
    lock_file = tmp_path / "pylock.toml"
    lock_file.write_text('created-by = "test"')
    
    pylock = PylockFile(lock_file)
    
    with pytest.raises(ValueError, match="missing required 'lock-version' field"):
        _ = pylock.lock_version


def test_get_requirements_basic(simple_lock_file: Path) -> None:
    """Test extracting requirements from a simple lock file."""
    pylock = PylockFile(simple_lock_file)
    requirements = pylock.get_requirements()
    
    assert len(requirements) == 3
    req_names = {req.name for req in requirements}
    assert req_names == {"requests", "urllib3", "certifi"}
    
    # Check versions are pinned
    for req in requirements:
        assert str(req.specifier).startswith("==")


def test_get_requirements_with_python_version_check(tmp_path: Path) -> None:
    """Test that packages with incompatible requires-python are filtered."""
    lock_content = """lock-version = "1.0"
requires-python = ">=3.8"
created-by = "test"

[[packages]]
name = "old-package"
version = "1.0.0"
requires-python = ">=2.7,<3.0"

[[packages]]
name = "new-package"
version = "2.0.0"
requires-python = ">=3.8"
"""
    lock_file = tmp_path / "pylock.toml"
    lock_file.write_text(lock_content)
    
    pylock = PylockFile(lock_file)
    requirements = pylock.get_requirements(python_version=(3, 9, 0))
    
    assert len(requirements) == 1
    assert requirements[0].name == "new-package"


def test_pylock_deps_integration(simple_lock_file: Path, tmp_path: Path) -> None:
    """Test PylockDeps wrapper for tox integration."""
    pylock_deps = PylockDeps(simple_lock_file, tmp_path)
    
    # Test requirements property
    requirements = pylock_deps.requirements
    assert len(requirements) == 3
    
    # Test as_root_args
    args = pylock_deps.as_root_args
    assert len(args) == 3
    assert any("requests==2.31.0" in arg for arg in args)
    
    # Test unroll
    options, reqs = pylock_deps.unroll()
    assert options == []
    assert len(reqs) == 3


def test_pylock_deps_relative_path(tmp_path: Path) -> None:
    """Test PylockDeps with relative path."""
    lock_content = """lock-version = "1.0"
requires-python = ">=3.8"
created-by = "test"

[[packages]]
name = "pytest"
version = "7.4.0"
"""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    lock_file = subdir / "pylock.toml"
    lock_file.write_text(lock_content)
    
    # Use relative path
    relative_lock = Path("subdir") / "pylock.toml"
    pylock_deps = PylockDeps(relative_lock, tmp_path)
    
    assert pylock_deps.path == lock_file
    assert len(pylock_deps.requirements) == 1


def test_full_example_from_pep_751(tmp_path: Path) -> None:
    """Test with an example similar to PEP 751 specification."""
    lock_content = """lock-version = "1.0"
environments = ["sys_platform == 'win32'", "sys_platform == 'linux'"]
requires-python = "==3.12"
created-by = "mousebender"

[[packages]]
name = "attrs"
version = "25.1.0"
requires-python = ">=3.8"

[[packages]]
name = "cattrs"
version = "24.1.2"
requires-python = ">=3.8"

[[packages]]
name = "numpy"
version = "2.2.3"
requires-python = ">=3.10"
"""
    lock_file = tmp_path / "pylock.toml"
    lock_file.write_text(lock_content)
    
    pylock = PylockFile(lock_file)
    
    # Test with Python 3.12
    requirements = pylock.get_requirements(python_version=(3, 12, 0))
    assert len(requirements) == 3
    
    # Test with Python 3.9 - should exclude numpy
    requirements_py39 = pylock.get_requirements(python_version=(3, 9, 0))
    assert len(requirements_py39) == 2
    req_names = {req.name for req in requirements_py39}
    assert "numpy" not in req_names


def test_pylock_toml_with_tox(tox_project: ToxProjectCreator) -> None:
    """Test that pylock.toml files work with tox deps configuration."""
    # Create a pylock.toml file
    lock_content = """lock-version = "1.0"
requires-python = ">=3.8"
created-by = "test"

[[packages]]
name = "pytest"
version = "7.4.0"
"""
    
    project = tox_project({
        "tox.ini": "[testenv]\ndeps=-r pylock.toml\nskip_install=true\ncommands=python --version",
        "pylock.toml": lock_content,
    })
    
    # Mock execute to avoid actually installing
    execute_calls = project.patch_execute(lambda r: 0 if "install" in r.run_id else None)
    
    result = project.run("r")
    result.assert_success()
    
    # Check that pip was called with the expanded requirement, not -r pylock.toml
    assert execute_calls.call_count >= 1
    install_call = next((call for call in execute_calls.call_args_list if "install" in call[0][3].run_id), None)
    assert install_call is not None
    
    # The command should contain pytest==7.4.0, not -r pylock.toml
    cmd = install_call[0][3].cmd
    assert "pytest==7.4.0" in " ".join(cmd)
    assert "pylock.toml" not in " ".join(cmd)


def test_pylock_toml_named_file(tox_project: ToxProjectCreator) -> None:
    """Test that named pylock files (pylock.dev.toml) work."""
    lock_content = """lock-version = "1.0"
requires-python = ">=3.8"
created-by = "test"

[[packages]]
name = "black"
version = "23.7.0"
"""
    
    project = tox_project({
        "tox.ini": "[testenv]\ndeps=-r pylock.dev.toml\nskip_install=true\ncommands=python --version",
        "pylock.dev.toml": lock_content,
    })
    
    execute_calls = project.patch_execute(lambda r: 0 if "install" in r.run_id else None)
    
    result = project.run("r")
    result.assert_success()
    
    # Check that the named file was processed
    install_call = next((call for call in execute_calls.call_args_list if "install" in call[0][3].run_id), None)
    assert install_call is not None
    cmd = install_call[0][3].cmd
    assert "black==23.7.0" in " ".join(cmd)

