"""The single exception handler mapping `DevMindError` to an RFC-7807 response.

No router and no service ever raises `HTTPException` (Claude.md §1) — every domain
failure is a `DevMindError` subclass, and its `.http_status` (set on the exception
itself, see `exceptions/base.py`) is the only place the mapping lives.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from devmind.exceptions import DevMindError

logger = logging.getLogger(__name__)


class ErrorHandlerRegistrar:
    """Registers the RFC-7807 handler on a FastAPI app. One method, one job."""

    def register(self, app: FastAPI) -> None:
        @app.exception_handler(DevMindError)
        async def _handle_devmind_error(request: Request, exc: DevMindError) -> JSONResponse:
            logger.warning(
                "%s: %s", type(exc).__name__, exc.message, extra={"details": exc.details}
            )
            problem_type = "/errors/" + _to_kebab_case(type(exc).__name__)
            return JSONResponse(
                status_code=exc.http_status,
                content={
                    "type": problem_type,
                    "title": type(exc).__name__,
                    "status": exc.http_status,
                    "detail": exc.message,
                    "instance": str(request.url.path),
                    **({"details": exc.details} if exc.details else {}),
                },
            )


def _to_kebab_case(name: str) -> str:
    """`ApprovalRequiredError` -> `approval-required-error`."""
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            result.append("-")
        result.append(char.lower())
    return "".join(result)
