from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.api.routes import router as api_router
from app.core.config import ENABLE_OPEN_DOCS, PUBLIC_BASE_URL, validate_config
from app.core.logging_config import setup_logging
from app.models.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    setup_logging()
    validate_config()
    init_db()
    print("🚀 SocioMed Lean procurement backend is now running!")
    yield
    # Optional: clean shutdown logic here later

app = FastAPI(
    title="SocioMed Lean",
    description="Procurement-ready WhatsApp marketplace for medical suppliers and buyers.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_OPEN_DOCS else None,
    redoc_url="/redoc" if ENABLE_OPEN_DOCS else None,
    openapi_tags=[
        {"name": "go-to-market", "description": "Endpoints you can hand to procurement teams or a simple landing page."},
    ],
)

# Include all routes
app.include_router(api_router)

@app.get("/")
async def root():
    return {
        "message": "SocioMed Lean procurement API",
        "status": "running",
        "audience": ["procurement teams", "suppliers"],
        "actions": {
            "featured_catalog": "/api/catalog/featured",
            "catalog_search_example": "/api/catalog/search?q=surgical gloves",
            "submit_rfq": "/api/rfqs",
            "capture_lead": "/api/leads",
            "whatsapp_webhook": "/api/webhook",
        },
        "docs": "/docs" if ENABLE_OPEN_DOCS else None,
        "public_base_url": PUBLIC_BASE_URL or None,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
