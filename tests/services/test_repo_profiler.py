from __future__ import annotations

from pathlib import Path

import pytest

from devmind.core.enums import DependencyManager, TestFramework
from devmind.services.repo_profiler import RepoProfiler


@pytest.fixture
def profiler() -> RepoProfiler:
    return RepoProfiler()


def test_pytest_detected_from_pyproject(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )
    (tmp_path / "tests").mkdir()
    profile = profiler.profile(tmp_path)
    assert profile.test_framework is TestFramework.PYTEST
    assert profile.has_test_suite is True
    assert profile.test_paths == ("tests",)
    assert profile.test_command == ("python", "-m", "pytest")


def test_pytest_detected_from_pytest_ini(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    profile = profiler.profile(tmp_path)
    assert profile.test_framework is TestFramework.PYTEST


def test_pytest_detected_from_optional_dependencies(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[project.optional-dependencies]\ndev = ["pytest>=8", "ruff"]\n'
    )
    profile = profiler.profile(tmp_path)
    assert profile.test_framework is TestFramework.PYTEST


def test_bare_tests_directory_is_enough(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_thing.py").write_text("def test_x():\n    assert True\n")
    profile = profiler.profile(tmp_path)
    assert profile.test_framework is TestFramework.PYTEST
    assert profile.test_paths == ("tests",)


def test_loose_test_files_are_discovered(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "test_unit.py").write_text("def test_x():\n    assert True\n")
    profile = profiler.profile(tmp_path)
    assert profile.test_framework is TestFramework.PYTEST
    assert "pkg" in profile.test_paths


def test_no_tests_is_a_legitimate_outcome(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (tmp_path / "app.py").write_text("print('hi')\n")
    profile = profiler.profile(tmp_path)
    assert profile.test_framework is None
    assert profile.has_test_suite is False
    assert profile.test_paths == ()
    assert profile.test_command == ()


def test_dependency_manager_uv(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (tmp_path / "uv.lock").write_text("")
    profile = profiler.profile(tmp_path)
    assert profile.dependency_manager is DependencyManager.UV
    assert profile.install_command == ("uv", "sync")


def test_dependency_manager_poetry(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nname = "x"\n')
    profile = profiler.profile(tmp_path)
    assert profile.dependency_manager is DependencyManager.POETRY
    assert profile.install_command == ("poetry", "install")


def test_dependency_manager_pip_from_requirements(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n")
    profile = profiler.profile(tmp_path)
    assert profile.dependency_manager is DependencyManager.PIP
    assert profile.install_command == ("pip", "install", "-e", ".")


def test_package_dirs_under_src(profiler: RepoProfiler, tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    profile = profiler.profile(tmp_path)
    assert profile.package_dirs == ("src/mypkg",)


def test_language_is_python_when_pyproject_present(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    assert profiler.profile(tmp_path).language == "python"


def test_language_falls_back_to_dominant_suffix(profiler: RepoProfiler, tmp_path: Path) -> None:
    (tmp_path / "a.js").write_text("")
    (tmp_path / "b.js").write_text("")
    (tmp_path / "c.rb").write_text("")
    assert profiler.profile(tmp_path).language == "javascript"
