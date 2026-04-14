from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.api.routes import router as api_router
from app.core.config import validate_config
from app.core.logging_config import setup_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    setup_logging()
    validate_config()
    print("🚀 SocioMed Lean WhatsApp Marketplace is now running!")
    yield
    # Optional: clean shutdown logic here later

app = FastAPI(
    title="SocioMed Lean",
    description="WhatsApp-native medical supplies marketplace",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",      # Keep Swagger UI for easy testing
    redoc_url="/redoc"
)

# Include all routes
app.include_router(api_router)

# Optional: Root endpoint for quick status check
@app.get("/")
async def root():
    return {
        "message": "SocioMed Lean WhatsApp Marketplace",
        "status": "running",
        "webhook": "/api/webhook"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
