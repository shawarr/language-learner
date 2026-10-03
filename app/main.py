"""FastAPI entrypoint. Routers register themselves in app/routers/__init__.py."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth
from .config import settings
from .db import db
from .providers.base import ProviderError
from .providers.llm import LLMUnavailable
from .routers import ALL_ROUTERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.connect()
    await auth.init_secret()
    if not settings.app_password:
        log.error("APP_PASSWORD is not set: nobody can log in")
    log.info("llm primary=%s fallback=%s fast=%s | stt=%s | tts=%s voice=%s",
             settings.llm_primary, settings.llm_fallback, settings.llm_fast,
             settings.stt_provider, settings.tts_provider, settings.tts_voice)
    yield
    await db.close()


app = FastAPI(title="Deutsch Tutor", docs_url=None, redoc_url=None, lifespan=lifespan)

for router in ALL_ROUTERS:
    app.include_router(router, prefix="/api")


@app.exception_handler(LLMUnavailable)
async def _llm_unavailable(_: Request, exc: LLMUnavailable):
    # 503 + retryable flag: the frontend keeps the user's recording/text and offers a retry.
    return JSONResponse(status_code=503, content={"detail": str(exc).split(" | ")[0], "retryable": True})


@app.exception_handler(ProviderError)
async def _provider_error(_: Request, exc: ProviderError):
    return JSONResponse(status_code=503 if exc.retryable else 502,
                        content={"detail": str(exc), "retryable": exc.retryable})


# The PWA shell. Mounted last so /api/* wins. html=True serves index.html for "/".
app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
