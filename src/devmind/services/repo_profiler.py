"""`RepoProfiler` — evidence-based detection of how a repo is built and tested (E4-F2-T3).

Priority order, per the spec: `pyproject.toml` first, then
`pytest.ini`/`tox.ini`/`setup.cfg`, then a `tests/` directory, then `test_*.py`
anywhere. `has_test_suite=False` is a legitimate result and is carried through to the
session record. Nothing here imports or runs the target repo — it reads files.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from devmind.core.constants import (
    INDEX_IGNORE_DIRS,
    LANGUAGE_BY_SOURCE_SUFFIX,
    LANGUAGE_PYTHON,
    LANGUAGE_UNKNOWN,
    PYTEST_MODULE_INVOCATION,
)
from devmind.core.enums import DependencyManager, TestFramework
from devmind.schemas.repo import RepoProfile

logger = logging.getLogger(__name__)

_INSTALL_COMMANDS: dict[DependencyManager, tuple[str, ...]] = {
    DependencyManager.UV: ("uv", "sync"),
    DependencyManager.POETRY: ("poetry", "install"),
    DependencyManager.PIP: ("pip", "install", "-e", "."),
}
_TEST_FILE_GLOBS: tuple[str, ...] = ("test_*.py", "*_test.py")


class RepoProfiler:
    """Produces a `RepoProfile` from a cloned repository on disk."""

    def profile(self, root: Path) -> RepoProfile:
        pyproject = self._read_pyproject(root)
        framework, test_paths = self._detect_tests(root, pyproject)
        dependency_manager = self._detect_dependency_manager(root, pyproject)
        install_command = (
            _INSTALL_COMMANDS[dependency_manager] if dependency_manager is not None else None
        )
        test_command = PYTEST_MODULE_INVOCATION if framework is TestFramework.PYTEST else ()
        return RepoProfile(
            language=self._detect_language(root, pyproject),
            test_framework=framework,
            test_paths=test_paths,
            dependency_manager=dependency_manager,
            install_command=install_command,
            test_command=test_command,
            package_dirs=self._detect_package_dirs(root),
            has_test_suite=framework is not None,
        )

    # --- pyproject -------------------------------------------------------------

    @staticmethod
    def _read_pyproject(root: Path) -> dict[str, object]:
        path = root / "pyproject.toml"
        if not path.is_file():
            return {}
        try:
            return tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (tomllib.TOMLDecodeError, OSError) as exc:
            logger.debug("pyproject.toml at %s did not parse: %s", path, exc)
            return {}

    # --- tests --------------------------------------------------------------------

    def _detect_tests(
        self, root: Path, pyproject: dict[str, object]
    ) -> tuple[TestFramework | None, tuple[str, ...]]:
        tool = pyproject.get("tool")
        tool_table = tool if isinstance(tool, dict) else {}

        pytest_config = tool_table.get("pytest")
        if isinstance(pytest_config, dict):
            ini = pytest_config.get("ini_options")
            paths = self._testpaths_from_ini(ini) or self._fallback_test_paths(root)
            return TestFramework.PYTEST, paths

        if self._pytest_in_optional_dependencies(pyproject):
            return TestFramework.PYTEST, self._fallback_test_paths(root)

        if (root / "pytest.ini").is_file():
            return TestFramework.PYTEST, self._fallback_test_paths(root)

        for config_name, marker in (("tox.ini", "pytest"), ("setup.cfg", "[tool:pytest]")):
            candidate = root / config_name
            if candidate.is_file() and marker in candidate.read_text(
                encoding="utf-8", errors="replace"
            ):
                return TestFramework.PYTEST, self._fallback_test_paths(root)

        if (root / "tests").is_dir():
            return TestFramework.PYTEST, ("tests",)

        discovered = self._discover_test_files(root)
        if discovered:
            return TestFramework.PYTEST, discovered

        return None, ()

    @staticmethod
    def _testpaths_from_ini(ini: object) -> tuple[str, ...]:
        if not isinstance(ini, dict):
            return ()
        raw = ini.get("testpaths")
        if isinstance(raw, str):
            return (raw,)
        if isinstance(raw, list):
            return tuple(str(item) for item in raw)
        return ()

    @staticmethod
    def _fallback_test_paths(root: Path) -> tuple[str, ...]:
        return ("tests",) if (root / "tests").is_dir() else ()

    @staticmethod
    def _pytest_in_optional_dependencies(pyproject: dict[str, object]) -> bool:
        project = pyproject.get("project")
        if not isinstance(project, dict):
            return False
        optional = project.get("optional-dependencies")
        if not isinstance(optional, dict):
            return False
        for group in optional.values():
            if isinstance(group, list) and any(
                isinstance(dep, str) and dep.lower().startswith("pytest") for dep in group
            ):
                return True
        return False

    def _discover_test_files(self, root: Path) -> tuple[str, ...]:
        directories: set[str] = set()
        for glob in _TEST_FILE_GLOBS:
            for path in root.rglob(glob):
                if path.is_symlink():
                    continue
                rel = path.relative_to(root)
                if any(part in INDEX_IGNORE_DIRS for part in rel.parts):
                    continue
                parent = rel.parent
                directories.add(parent.as_posix() if parent != Path() else ".")
        return tuple(sorted(directories))

    # --- dependency manager ---------------------------------------------------

    @staticmethod
    def _detect_dependency_manager(
        root: Path, pyproject: dict[str, object]
    ) -> DependencyManager | None:
        tool = pyproject.get("tool")
        tool_table = tool if isinstance(tool, dict) else {}

        if (root / "uv.lock").is_file() or "uv" in tool_table:
            return DependencyManager.UV
        if (root / "poetry.lock").is_file() or "poetry" in tool_table:
            return DependencyManager.POETRY
        if (
            "project" in pyproject
            or (root / "setup.py").is_file()
            or (root / "setup.cfg").is_file()
            or any(root.glob("requirements*.txt"))
        ):
            return DependencyManager.PIP
        return None

    # --- packages & language ------------------------------------------------------

    @staticmethod
    def _detect_package_dirs(root: Path) -> tuple[str, ...]:
        src = root / "src"
        if src.is_dir():
            packages = sorted(
                f"src/{child.name}"
                for child in src.iterdir()
                if child.is_dir() and (child / "__init__.py").is_file()
            )
            if packages:
                return tuple(packages)
            if any(src.glob("*.py")):
                return ("src",)

        return tuple(
            sorted(
                child.name
                for child in root.iterdir()
                if child.is_dir()
                and child.name not in INDEX_IGNORE_DIRS
                and child.name not in {"tests", "test", "docs"}
                and (child / "__init__.py").is_file()
            )
        )

    def _detect_language(self, root: Path, pyproject: dict[str, object]) -> str:
        if pyproject or (root / "setup.py").is_file():
            return LANGUAGE_PYTHON
        counts: dict[str, int] = {}
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root)
            if any(part in INDEX_IGNORE_DIRS for part in rel.parts):
                continue
            language = LANGUAGE_BY_SOURCE_SUFFIX.get(path.suffix)
            if language is not None:
                counts[language] = counts.get(language, 0) + 1
        if not counts:
            return LANGUAGE_UNKNOWN
        return max(sorted(counts), key=lambda language: counts[language])
