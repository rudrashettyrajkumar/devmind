"""`WorkspaceManager` — creates, guards, and tears down per-session workspaces.

One directory per session under a shared root. The disk ceiling is checked *before*
each create so a run never discovers the disk is full at minute nine (spec
§WorkspaceManager). `guard_for()` is the only supported way to get a
`WorkspacePathGuard` for a session — every path-taking tool goes through it.
"""

import logging
import shutil
from pathlib import Path

from devmind.exceptions import WorkspaceError
from devmind.services.workspace_path_guard import WorkspacePathGuard

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Lifecycle for the isolated on-disk workspaces sessions run in."""

    def __init__(self, root: Path, max_bytes: int) -> None:
        self._root = root
        self._max_bytes = max_bytes

    def create(self, session_id: str) -> Path:
        """Create `<root>/<session_id>/` and return it.

        Raises `WorkspaceError` if the root is already over its disk ceiling, if the
        session id is not a safe single path segment, or if the directory exists.
        """
        segment = self._safe_segment(session_id)
        self._root.mkdir(parents=True, exist_ok=True)

        used = self.usage_bytes()
        if used >= self._max_bytes:
            raise WorkspaceError(
                f"workspace root {self._root} is at {used} bytes, over its "
                f"{self._max_bytes}-byte ceiling — refusing to create another workspace",
                details={"used_bytes": used, "max_bytes": self._max_bytes},
            )

        path = self._root / segment
        try:
            path.mkdir(parents=False, exist_ok=False)
        except FileExistsError as exc:
            raise WorkspaceError(
                f"workspace for session {session_id} already exists at {path}",
                details={"session_id": session_id, "path": str(path)},
            ) from exc
        logger.info("created workspace %s", path)
        return path

    def guard_for(self, session_id: str) -> WorkspacePathGuard:
        """A `WorkspacePathGuard` rooted at this session's workspace. The workspace
        must already exist (`create()` was called).
        """
        segment = self._safe_segment(session_id)
        return WorkspacePathGuard(self._root / segment)

    def destroy(self, session_id: str) -> None:
        """Remove the session's workspace. A no-op if it is already gone."""
        segment = self._safe_segment(session_id)
        path = self._root / segment
        if path.is_dir():
            shutil.rmtree(path)
            logger.info("destroyed workspace %s", path)

    def usage_bytes(self) -> int:
        """Total size of all regular files under the root. Symlinks are not followed."""
        if not self._root.exists():
            return 0
        total = 0
        for entry in self._root.rglob("*"):
            if entry.is_symlink() or not entry.is_file():
                continue
            total += entry.stat().st_size
        return total

    @staticmethod
    def _safe_segment(session_id: str) -> str:
        if not session_id or session_id in {".", ".."} or set(session_id) & set("/\\"):
            raise WorkspaceError(
                f"unsafe session id for a workspace path: {session_id!r}",
                details={"session_id": session_id},
            )
        return session_id
