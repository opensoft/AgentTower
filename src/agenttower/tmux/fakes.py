"""Test-only tmux adapter that scripts canned outcomes from a JSON fixture.

The fixture format (R-012) is:

```json
{
  "containers": {
    "<container-id>": {
      "uid": "1000",
      "id_u_failure": null,
      "socket_dir_missing": false,
      "socket_unreadable": false,
      "sockets": {
        "default": [
          {"session_name": "...", "window_index": 0, "pane_index": 0,
           "pane_id": "%0", "pane_pid": 1234, "pane_tty": "/dev/pts/0",
           "pane_current_command": "bash", "pane_current_path": "/workspace",
           "pane_title": "...", "pane_active": true}
        ],
        "work": {"failure": {"code": "tmux_no_server", "message": "..."}}
      }
    }
  }
}
```

Per-container failure knobs supersede per-socket data: ``id_u_failure`` set
to a string code raises ``TmuxError`` with that code on ``resolve_uid``;
``socket_dir_missing: true`` raises ``socket_dir_missing`` on
``list_socket_dir``; ``socket_unreadable: true`` raises ``socket_unreadable``.

Adapter never spawns a subprocess (R-017 / SC-009).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..socket_api import errors as _errors
from .adapter import SocketListing, TmuxError
from .parsers import ParsedPane


class FakeTmuxAdapter:
    """Scriptable adapter that satisfies the :class:`TmuxAdapter` Protocol."""

    def __init__(
        self,
        script: Mapping[str, Any] | None = None,
        *,
        path: Path | None = None,
    ) -> None:
        self._script: dict[str, Any] = dict(script) if script is not None else {}
        self._path = path

    @classmethod
    def from_path(cls, path: str | Path) -> "FakeTmuxAdapter":
        return cls(path=Path(path))

    def _load(self) -> dict[str, Any]:
        if self._path is None:
            return self._script
        text = self._path.read_text(encoding="utf-8")
        return json.loads(text)

    def _container(self, container_id: str) -> dict[str, Any]:
        script = self._load()
        containers = script.get("containers", {})
        if container_id not in containers:
            raise TmuxError(
                code=_errors.DOCKER_EXEC_FAILED,
                message=f"fake fixture has no container {container_id!r}",
                container_id=container_id,
            )
        entry = containers[container_id]
        if not isinstance(entry, dict):
            raise TmuxError(
                code=_errors.OUTPUT_MALFORMED,
                message=f"fake fixture container entry is not a dict: {container_id!r}",
                container_id=container_id,
            )
        return entry

    # -- TmuxAdapter Protocol --------------------------------------------------

    def resolve_uid(self, *, container_id: str, bench_user: str) -> str:
        entry = self._container(container_id)
        failure = entry.get("id_u_failure")
        if failure:
            code, message = _normalize_failure(failure, default_code=_errors.DOCKER_EXEC_FAILED)
            raise TmuxError(code=code, message=message, container_id=container_id)
        uid = entry.get("uid")
        if not uid:
            raise TmuxError(
                code=_errors.OUTPUT_MALFORMED,
                message="fake fixture container has no uid",
                container_id=container_id,
            )
        return str(uid)

    def list_socket_dir(
        self, *, container_id: str, bench_user: str, uid: str
    ) -> SocketListing:
        entry = self._container(container_id)
        if entry.get("socket_dir_missing"):
            raise TmuxError(
                code=_errors.SOCKET_DIR_MISSING,
                message=f"/tmp/tmux-{uid}: no such file or directory",  # NOSONAR - fixture mirrors real tmux socket-dir error.
                container_id=container_id,
            )
        if entry.get("socket_unreadable"):
            raise TmuxError(
                code=_errors.SOCKET_UNREADABLE,
                message=f"/tmp/tmux-{uid}: permission denied",  # NOSONAR - fixture mirrors real tmux socket-dir error.
                container_id=container_id,
            )
        socket_listing_failure = entry.get("socket_listing_failure")
        if socket_listing_failure:
            code, message = _normalize_failure(
                socket_listing_failure, default_code=_errors.DOCKER_EXEC_FAILED
            )
            raise TmuxError(code=code, message=message, container_id=container_id)
        sockets_section = entry.get("sockets", {})
        socket_names = tuple(sockets_section.keys())
        return SocketListing(container_id=container_id, uid=str(uid), sockets=socket_names)

    def list_panes(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
    ) -> Sequence[ParsedPane]:
        entry = self._container(container_id)
        socket_name = _socket_name_from_path(socket_path)
        sockets = entry.get("sockets", {})
        if socket_name not in sockets:
            raise TmuxError(
                code=_errors.TMUX_NO_SERVER,
                message=f"fake fixture has no socket {socket_name!r}",
                container_id=container_id,
                tmux_socket_path=socket_path,
            )
        socket_data = sockets[socket_name]
        if isinstance(socket_data, dict) and "failure" in socket_data:
            failure = socket_data["failure"]
            code, message = _normalize_failure(
                failure, default_code=_errors.TMUX_NO_SERVER
            )
            raise TmuxError(
                code=code,
                message=message,
                container_id=container_id,
                tmux_socket_path=socket_path,
            )
        if not isinstance(socket_data, list):
            raise TmuxError(
                code=_errors.OUTPUT_MALFORMED,
                message=f"fake fixture socket {socket_name!r} is not a list",
                container_id=container_id,
                tmux_socket_path=socket_path,
            )
        out: list[ParsedPane] = []
        for pane in socket_data:
            out.append(
                ParsedPane(
                    tmux_session_name=str(pane["session_name"]),
                    tmux_window_index=int(pane["window_index"]),
                    tmux_pane_index=int(pane["pane_index"]),
                    tmux_pane_id=str(pane["pane_id"]),
                    pane_pid=int(pane["pane_pid"]),
                    pane_tty=str(pane.get("pane_tty", "")),
                    pane_current_command=str(pane.get("pane_current_command", "")),
                    pane_current_path=str(pane.get("pane_current_path", "")),
                    pane_title=str(pane.get("pane_title", "")),
                    pane_active=bool(pane.get("pane_active", False)),
                )
            )
        return out


def _normalize_failure(
    failure: Any, *, default_code: str
) -> tuple[str, str]:
    if isinstance(failure, str):
        return failure, f"fake {failure}"
    if isinstance(failure, dict):
        code = str(failure.get("code", default_code))
        message = str(failure.get("message", f"fake {code}"))
        return code, message
    return default_code, "fake failure"


def _socket_name_from_path(socket_path: str) -> str:
    """Return the basename of *socket_path* without invoking ``os.path``."""
    if "/" in socket_path:
        return socket_path.rsplit("/", 1)[-1]
    return socket_path
