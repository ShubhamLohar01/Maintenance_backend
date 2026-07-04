import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import LocalBase, RdsBase, local_engine, rds_engine
from .api import (
    auth, machines, energy, breakdowns, floors, mt_machines,
    preventive_maintenance, machine_transfers, breakdown_records,
    live, reports, head, floor_readings, asset_schedules, devices,
)


class JSONErrorMiddleware:
    """Pure-ASGI catch-all: any unhandled exception becomes a JSON 500, never an
    HTML debug page or plain-text body. FastAPI still returns its own JSON for
    HTTPException / validation errors; this only fires for genuine 500s."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def _send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:  # noqa: BLE001
            logging.getLogger("uvicorn.error").exception(
                "Unhandled error on %s %s", scope.get("method"), scope.get("path")
            )
            if started:
                raise  # headers already sent; cannot replace the response
            await JSONResponse(
                status_code=500, content={"detail": "Internal server error"}
            )(scope, receive, send)


def create_app() -> FastAPI:
    LocalBase.metadata.create_all(bind=local_engine)
    # RDS may be briefly unreachable (DNS/network) — don't let that crash startup.
    # Tables get created on the next boot where RDS is reachable; per-request
    # endpoints reconnect on their own once connectivity returns.
    try:
        RdsBase.metadata.create_all(bind=rds_engine)
    except Exception as exc:  # noqa: BLE001
        # NOTE: do NOT `import logging` here — a function-local import would make
        # `logging` local to create_app, shadowing the module-level import and
        # breaking the nested _log_validation_error closure (NameError -> every 422
        # would 500). `logging` is already imported at module top.
        logging.getLogger("uvicorn.error").warning(
            "RDS unreachable at startup (%s) — skipped table create; "
            "RDS endpoints will work once connectivity returns.", type(exc).__name__
        )

    app = FastAPI(
        title="FactoryOps Maintenance Backend",
        version="0.1.0",
        description="Backend for the FactoryOps Phase-1 mobile app "
                    "(Power Consumption + Breakdowns + Floor utility data).",
        debug=False,  # never render HTML tracebacks to API clients
    )

    # Catch-all so any unhandled exception returns JSON, never an HTML debug page.
    # Added before CORS so CORS ends up outermost and still tags error responses.
    app.add_middleware(JSONErrorMiddleware)

    # CORS — mobile app + dev tooling
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def _log_validation_error(request: Request, exc: RequestValidationError):
        logging.getLogger("uvicorn.error").warning(
            "422 on %s %s -> %s", request.method, request.url.path, exc.errors()
        )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    app.include_router(auth.router)
    app.include_router(machines.router)
    app.include_router(energy.router)
    app.include_router(breakdowns.router)
    app.include_router(floors.router)
    app.include_router(mt_machines.router)
    app.include_router(preventive_maintenance.router)
    app.include_router(machine_transfers.router)
    app.include_router(breakdown_records.router)
    app.include_router(live.router)
    app.include_router(reports.router)
    app.include_router(head.router)
    app.include_router(floor_readings.router)
    app.include_router(asset_schedules.router)
    app.include_router(devices.router)

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
