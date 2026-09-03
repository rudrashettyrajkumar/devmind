"""`devmind` CLI entry point — argument parsing and dispatch (E11-F3).

`main(argv)` is pure dispatch: parse, build an `httpx.Client` against the configured
API base URL, hand off to `DevMindCLI`. Kept separate from `client.py` so the command
logic is testable without going through argparse.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

import httpx

from devmind.cli.client import CLIError, DevMindCLI

_DEFAULT_BASE_URL = "http://127.0.0.1:8000"
_ENV_BASE_URL = "DEVMIND_API_URL"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devmind", description="Operate a DevMind run.")
    parser.add_argument(
        "--api-url",
        default=os.environ.get(_ENV_BASE_URL, _DEFAULT_BASE_URL),
        help=f"API base URL (default: ${_ENV_BASE_URL} or {_DEFAULT_BASE_URL})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="start a session")
    run.add_argument("repo", help="repository URL")
    run.add_argument("issue", type=int, help="issue number")

    for name, help_text in (
        ("watch", "live view of a running session"),
        ("review", "render the approval payload"),
        ("status", "one-shot session status"),
    ):
        single = sub.add_parser(name, help=help_text)
        single.add_argument("session_id")

    approve = sub.add_parser("approve", help="approve a session (requires typed confirmation)")
    approve.add_argument("session_id")
    approve.add_argument("--by", required=True, help="the approving human's name")

    reject = sub.add_parser("reject", help="reject a session")
    reject.add_argument("session_id")
    reject.add_argument("--by", required=True, help="the deciding human's name")
    reject.add_argument("--reason", required=True, help="why (required for a rejection)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with httpx.Client(base_url=args.api_url, timeout=30.0) as http:
        cli = DevMindCLI(http)
        try:
            _dispatch(cli, args)
        except CLIError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except httpx.HTTPError as exc:
            print(f"error: could not reach {args.api_url}: {exc}", file=sys.stderr)
            return 2
    return 0


def _dispatch(cli: DevMindCLI, args: argparse.Namespace) -> None:
    if args.command == "run":
        cli.run(args.repo, args.issue)
    elif args.command == "watch":
        cli.watch(args.session_id)
    elif args.command == "review":
        cli.review(args.session_id)
    elif args.command == "status":
        cli.status(args.session_id)
    elif args.command == "approve":
        cli.approve(args.session_id, args.by)
    elif args.command == "reject":
        cli.reject(args.session_id, args.by, args.reason)
    else:  # pragma: no cover - argparse `required=True` prevents this
        raise CLIError(f"unknown command {args.command!r}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
