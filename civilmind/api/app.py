"""FastAPI application factory."""

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from civilmind.settings import settings

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting CivilMind AI", version="0.1.0")
    app.state.services = {}
    yield
    for name, client in app.state.services.items():
        try:
            if hasattr(client, "close"):
                await client.close()
            elif hasattr(client, "aclose"):
                await client.aclose()
            logger.info("Closed service", service=name)
        except Exception as e:
            logger.error("Error closing service", service=name, error=str(e))


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="AI Architecture & Construction Copilot",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(400)
    async def bad_request_handler(request: Request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse(status_code=404, content={"detail": "Resource not found"})

    @app.exception_handler(500)
    async def server_error_handler(request: Request, exc):
        logger.error("Internal server error", error=str(exc))
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    from civilmind.api.routes.health import router as health_router
    from civilmind.api.routes.upload import router as upload_router

    app.include_router(health_router)
    app.include_router(upload_router)

    return app


app = create_app()
