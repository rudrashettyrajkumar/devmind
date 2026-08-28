"""`GET /health` — interface layer only, no business logic (Claude.md §1)."""

from fastapi import APIRouter, Request

from devmind.schemas.health import HealthRead

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthRead)
async def get_health(request: Request) -> HealthRead:
    """Reads the values `ApplicationFactory`'s lifespan resolved once at startup —
    this endpoint never re-probes anything itself.
    """
    return HealthRead(
        status="ok",
        version=request.app.state.version,
        database=request.app.state.database_status,
        sandbox_backend=request.app.state.sandbox_backend,
        provider_reachable=request.app.state.provider_reachable,
    )
