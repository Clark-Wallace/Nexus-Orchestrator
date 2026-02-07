"""FastAPI application factory for the Nexus Orchestrator web interface."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from web.websocket import OrchestratorWSManager


def create_app(
    projects_dir: str | Path = "projects",
    docs_dir: str | Path = "constitutional_docs",
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        projects_dir: Path to the projects directory.
        docs_dir: Path to the constitutional docs directory.

    Returns:
        Configured FastAPI instance.
    """
    app = FastAPI(
        title="Nexus Orchestrator",
        version="0.1.0",
        description="Constitutional multi-agent engineering — web interface",
    )

    # Store shared state
    app.state.projects_dir = Path(projects_dir)
    app.state.docs_dir = Path(docs_dir)
    app.state.ws_manager = OrchestratorWSManager()

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "ok", "version": "0.1.0"}

    # Include route modules
    from web.routes.projects import router as projects_router
    from web.routes.gates import router as gates_router
    from web.routes.artifacts import router as artifacts_router
    from web.routes.lineage import router as lineage_router
    from web.routes.costs import router as costs_router
    from web.routes.export import router as export_router

    app.include_router(projects_router, prefix="/api")
    app.include_router(gates_router, prefix="/api")
    app.include_router(artifacts_router, prefix="/api")
    app.include_router(lineage_router, prefix="/api")
    app.include_router(costs_router, prefix="/api")
    app.include_router(export_router, prefix="/api")

    # WebSocket endpoint
    @app.websocket("/ws/{project_id}")
    async def websocket_endpoint(websocket: WebSocket, project_id: str):
        await app.state.ws_manager.handle_connection(websocket, project_id)

    return app
