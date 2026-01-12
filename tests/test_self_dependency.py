"""Test for issue #3489 - Self-dependency when using depends with env_run_base."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.conftest import ToxProjectCreator


def test_depends_in_env_run_base_no_circular_dependency(tox_project: ToxProjectCreator) -> None:
    """Test that environments don't depend on themselves via env_run_base.

    Reproduces issue #3489:
    - env_run_base has depends = ["lint"]
    - lint inherits from env_run_base
    - WITHOUT FIX: lint depends on itself -> circular dependency (ValueError)
    - WITH FIX: self-dependency is filtered out, lint runs successfully
    """
    project = tox_project(
        {
            "pyproject.toml": """
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"

                [project]
                name = "demo"
                version = "1.0"

                [tool.tox]
                env_list = ["lint", "py"]

                [tool.tox.env.lint]
                skip_install = true
                commands = [
                    ["python", "-c", "print('linting')"],
                ]

                [tool.tox.env_run_base]
                depends = ["lint"]
                package = "wheel"
                commands = [["python", "-c", "print('testing')"]]
            """,
        },
    )

    # Run all envs - should not fail with circular dependency error
    result = project.run()
    result.assert_success()

    # Both lint and py should have run
    assert "lint: commands[0]" in result.out or "lint: OK" in result.out
    assert "py: commands[0]" in result.out or "py: OK" in result.out
    
    # Verify lint ran before py (dependency ordering)
    lint_index = result.out.find("lint:")
    py_index = result.out.find("py:")
    assert lint_index < py_index, "lint should run before py (dependency ordering)"


def test_depends_with_specific_env_selection(tox_project: ToxProjectCreator) -> None:
    """Test dependency ordering when both envs are selected."""
    project = tox_project(
        {
            "pyproject.toml": """
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"

                [project]
                name = "demo"
                version = "1.0"

                [tool.tox]
                env_list = ["lint", "py"]

                [tool.tox.env.lint]
                skip_install = true
                commands = [
                    ["python", "-c", "print('linting')"],
                ]

                [tool.tox.env.py]
                depends = ["lint"]
                package = "wheel"
                commands = [["python", "-c", "print('testing')"]]
            """,
        },
    )

    # Run both lint and py explicitly - should respect dependency ordering
    result = project.run("-e", "lint,py")
    result.assert_success()

    # Both should have run
    assert "lint: commands[0]" in result.out or "lint: OK" in result.out
    assert "py: commands[0]" in result.out or "py: OK" in result.out
    
    # Verify lint ran before py (dependency ordering)
    lint_index = result.out.find("lint:")
    py_index = result.out.find("py:")
    assert lint_index < py_index, "lint should run before py (dependency ordering)"
