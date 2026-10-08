from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import AccessLogMiddleware
from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.pipeline.graph import reset_graph

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "api ready env=%s log_level=%s ollama=%s model=%s redis=%s",
        settings.environment,
        settings.log_level,
        settings.ollama_base_url,
        settings.ollama_model,
        settings.redis_target,
    )
    yield
    reset_graph()
    logger.info("api stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    application = FastAPI(title="AP document backend", version="0.1.0", lifespan=lifespan)
    # Added first so CORS stays on the outside and this still sees the final status.
    application.add_middleware(AccessLogMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
