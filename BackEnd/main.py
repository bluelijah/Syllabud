from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os

from routes.auth_routes import router as auth_router
from routes.course_routes import router as course_router
from routes.admin_routes import router as admin_router
from database import init_db, engine
from sqlalchemy import text

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup"""
    init_db()
    print("Database initialized")
    yield


backendApp = FastAPI(
    title="Syllabud API",
    description="Your Personalized Course Creator - Learn What Matters",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware - allow frontend origins
cors_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://syllabud.app",
]
# Add production frontend URL from environment variable
frontend_url = os.getenv("FRONTEND_URL")
if frontend_url and frontend_url not in cors_origins:
    cors_origins.append(frontend_url)

print(f"CORS allowed origins: {cors_origins}")

backendApp.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
backendApp.include_router(auth_router)
backendApp.include_router(course_router)
backendApp.include_router(admin_router)


@backendApp.get("/")
async def root():
    return {"message": "Syllabud API", "docs": "/docs"}


@backendApp.get("/test-db")
def test_db():
    """Test database connection"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        return {"status": "success", "database": "connected"}
    except Exception:
        # Log details server-side only; the raw error can include DB host/user
        logger.exception("Database connectivity check failed")
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})
