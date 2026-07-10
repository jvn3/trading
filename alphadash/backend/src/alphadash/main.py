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
from alphadash.api.auth import router as auth_router
from alphadash.api.chat import router as chat_router
from alphadash.api.journal import router as journal_router
from alphadash.api.notifications import router as notifications_router
from alphadash.api.onboarding import router as onboarding_router
from alphadash.api.orders import router as orders_router
from alphadash.api.portfolio import router as portfolio_router
from alphadash.api.strategies import router as strategies_router
from alphadash.api.suggestions import router as suggestions_router
from alphadash.api.whatif import router as whatif_router
from alphadash.config import Settings, get_settings
from alphadash.db.session import build_engine, build_session_factory
from alphadash.llm.factory import build_llm
from alphadash.providers.factory import build_bundle


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
    app.state.settings = settings
    engine = build_engine(settings)
    if settings.create_all:  # dev/e2e convenience; production schema comes from Alembic
        from alphadash.db.base import Base

        Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.providers = build_bundle(settings)
    app.state.llm = build_llm(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(portfolio_router)
    app.include_router(orders_router)
    app.include_router(suggestions_router)
    app.include_router(chat_router)
    app.include_router(onboarding_router)
    app.include_router(notifications_router)
    app.include_router(journal_router)
    app.include_router(strategies_router)
    app.include_router(whatif_router)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            trading_mode=settings.trading_mode,
        )

    return app


app = create_app()
