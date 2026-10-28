import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from reference_app.environment import Settings
from reference_app.observations import ObservationLog, RecordRequests
from reference_app.routers import items, process, requests, streams


class StartupFailure(Exception):
    """The failure the settings asked the lifespan startup for."""


def create_app(settings: Settings) -> FastAPI:
    """
    Create the reference app.

    Its lifespan startup writes the fake ready line and fails as the settings ask, and
    the lifespan and every request are recorded in the observation log.

    Args:
        settings: The settings.

    Returns:
        The app.
    """
    log = ObservationLog(settings.log)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        if settings.fake_ready is not None:
            sys.stdout.write(f"{settings.fake_ready}\n")
            sys.stdout.flush()
        if settings.fail_startup is not None:
            log.record("startup_failure", message=settings.fail_startup)
            raise StartupFailure(settings.fail_startup)
        log.record("startup")
        yield
        log.record("shutdown")

    app = FastAPI(title="pipeapi reference app", version="0.0.0", lifespan=lifespan)
    app.add_middleware(RecordRequests, log=log)
    app.include_router(items.create_router())
    app.include_router(requests.create_router())
    app.include_router(streams.create_router(log))
    app.include_router(process.create_router())
    return app
