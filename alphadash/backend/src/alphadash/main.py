"""FastAPI application entrypoint.

S0.1 scaffold: an app factory, CORS for the frontend dev server, and a ``/health`` endpoint that
also reports the trading mode so the paper-only invariant is observable from the very first commit.
Feature routers (portfolio, suggestions, agent, ...) are mounted here from later sessions.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from alphadash import __version__
from alphadash.config import Settings, get_settings


class HealthResponse(BaseModel):
    """Shape returned by ``GET /health`` (frozen contract for S0.1)."""

    status: str
    version: str
    trading_mode: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Accepts injected settings to keep tests hermetic."""
    settings = settings or get_settings()
    app = FastAPI(
        title="AlphaDash",
        version=__version__,
        description="Beginner strategy-agent product — paper-trading first.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            trading_mode=settings.trading_mode,
        )

    return app


app = create_app()
