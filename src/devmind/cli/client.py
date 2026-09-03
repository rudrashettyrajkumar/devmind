"""`DevMindCLI` — the operator surface over the HTTP API (E11-F3).

`rich`-rendered. Every command is one or a few calls to the API and a render; the CLI
holds no domain logic. The `httpx.Client` and the confirmation prompt are injected so
the command tests never open a socket or block on stdin.

`approve` is deliberately heavy: it makes you type the session id back. Approving an
autonomous agent's code change should take a deliberate second, and a single keystroke
next to "n" is not deliberate (spec §CLI client).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from devmind.core.constants import API_V1_PREFIX
from devmind.core.enums import SessionStatus

_TERMINAL = {s.value for s in SessionStatus if s.is_terminal()}
_WATCH_POLL_SECONDS = 1.0


class CLIError(RuntimeError):
    """A command could not complete — a bad response, or an aborted confirmation."""


class DevMindCLI:
    """One method per operator command; each renders to the injected console."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        console: Console | None = None,
        confirm: Callable[[str], str] = input,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = client
        self._console = console or Console()
        self._confirm = confirm
        self._sleep = sleep

    # --- commands ---------------------------------------------------------

    def run(self, repo: str, issue: int) -> str:
        body = {"repo_url": repo, "issue_number": issue}
        session = self._post(f"{API_V1_PREFIX}/sessions", body)
        session_id = str(session["id"])
        self._console.print(f"[green]started[/] session [bold]{session_id}[/] for {repo}#{issue}")
        return session_id

    def status(self, session_id: str) -> None:
        self._console.print(
            self._session_table(self._get(f"{API_V1_PREFIX}/sessions/{session_id}"))
        )

    def watch(self, session_id: str) -> None:
        after = 0
        while True:
            session = self._get(f"{API_V1_PREFIX}/sessions/{session_id}")
            events = self._get(
                f"{API_V1_PREFIX}/sessions/{session_id}/events", params={"after_sequence": after}
            )
            for event in events:
                after = max(after, int(event["sequence"]))
                self._console.print(
                    f"  [dim]{event['sequence']:>3}[/] [cyan]{event['event_type']}[/] "
                    f"{_compact(event['payload'])}"
                )
            self._console.print(self._session_table(session))
            if session["status"] in _TERMINAL:
                self._console.print(f"[bold]session finished:[/] {session['status']}")
                return
            self._sleep(_WATCH_POLL_SECONDS)

    def review(self, session_id: str) -> None:
        payload = self._get(f"{API_V1_PREFIX}/sessions/{session_id}/approval-request")

        warnings = payload.get("warnings") or []
        if warnings:
            body = "\n".join(f"• {w}" for w in warnings)
            self._console.print(Panel(body, title="WARNINGS", border_style="red"))
        else:
            self._console.print("[green]no warnings[/]")

        summary = payload.get("summary") or {}
        self._console.print(Panel(str(summary.get("markdown", "")), title="Change summary"))

        diff = str(payload.get("diff") or "")
        if diff.strip():
            self._console.print(Syntax(diff, "diff", theme="ansi_dark", word_wrap=True))

        evidence = payload.get("test_evidence") or {}
        self._console.print(f"[bold]test evidence:[/] {_compact(evidence)}")

        for note in payload.get("risk_notes") or []:
            self._console.print(f"  [yellow]risk[/] {note}")

    def approve(self, session_id: str, by: str) -> None:
        typed = self._confirm(f"Type the session id ({session_id}) to confirm approval: ").strip()
        if typed != session_id:
            raise CLIError("confirmation did not match the session id — approval aborted")
        self._post(
            f"{API_V1_PREFIX}/sessions/{session_id}/approval",
            {"decision": "approved", "decided_by": by},
        )
        self._console.print(f"[green]approved[/] session {session_id} as [bold]{by}[/]")

    def reject(self, session_id: str, by: str, reason: str) -> None:
        self._post(
            f"{API_V1_PREFIX}/sessions/{session_id}/approval",
            {"decision": "rejected", "decided_by": by, "reason": reason},
        )
        self._console.print(f"[red]rejected[/] session {session_id} as [bold]{by}[/]: {reason}")

    # --- internals ------------------------------------------------------

    def _get(self, path: str, *, params: dict[str, int] | None = None) -> Any:
        return self._unwrap(self._http.get(path, params=params))

    def _post(self, path: str, body: dict[str, object]) -> dict[str, Any]:
        result = self._unwrap(self._http.post(path, json=body))
        assert isinstance(result, dict)
        return result

    @staticmethod
    def _unwrap(response: httpx.Response) -> Any:
        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("detail", ""))
            except ValueError:
                detail = response.text
            raise CLIError(f"{response.status_code}: {detail or response.reason_phrase}")
        return response.json()

    def _session_table(self, session: dict[str, Any]) -> Table:
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_row("status", f"[bold]{session.get('status')}[/]")
        table.add_row("fix attempts", str(session.get("fix_attempts")))
        table.add_row("steps", str(session.get("total_steps")))
        cost = float(session.get("estimated_cost_usd") or 0.0)
        table.add_row("cost", f"${cost:.2f}")
        if session.get("failure_reason"):
            table.add_row("failure", f"[red]{session['failure_reason']}[/]")
        return table


def _compact(payload: object, limit: int = 120) -> str:
    text = str(payload)
    return text if len(text) <= limit else text[: limit - 1] + "…"
