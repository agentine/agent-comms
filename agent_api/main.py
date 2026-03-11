import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_api.database import init_db
from agent_api.routers import journal, tasks, ui


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Agent Communication API", version="1.0", lifespan=lifespan)
app.include_router(journal.router)
app.include_router(tasks.router)
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
