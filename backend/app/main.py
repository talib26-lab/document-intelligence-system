"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.db.database import init_db
from backend.app.api.documents import router as documents_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # create tables on startup if they do not exist
    yield


app = FastAPI(
    title="Document Intelligence System",
    description="Upload invoices, extract structured data with AI, validate and review it.",
    version="0.1.0",
    lifespan=lifespan,
)

# Only our own frontend (running locally) may call this API from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}

app.include_router(documents_router)