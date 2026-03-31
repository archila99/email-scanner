from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response

from app.db import init_db
from app.api.routes import router as api_router
from app.config import settings


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Gmail Scanner",
        debug=settings.debug,
        lifespan=_lifespan,
    )

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs", status_code=307)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    app.include_router(api_router)
    return app


app = create_app()

