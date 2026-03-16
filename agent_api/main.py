import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_api.auth import seed_api_key
from agent_api.database import SessionLocal, init_db
from agent_api.routers import agents, journal, keys, projects, runs, status, tasks, ui


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_api_key(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Agent Communication API",
    version="1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.include_router(agents.router, prefix="/api")
app.include_router(journal.router, prefix="/api")
app.include_router(keys.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(ui.router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agent_api.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
        reload=True,
    )
