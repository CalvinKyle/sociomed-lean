from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler

from app.api.routes import router as api_router
from app.core.auth import require_api_key
from app.core.config import ENABLE_OPEN_DOCS, PUBLIC_BASE_URL, validate_config
from app.core.logging_config import setup_logging
from app.core.rate_limit import limiter

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    setup_logging()
    validate_config()
    print("🚀 SocioMed Lean procurement backend is now running!")
    yield
    # Optional: clean shutdown logic here later

app = FastAPI(
    title="SocioMed Lean",
    description="Procurement-ready WhatsApp medical-supply sourcing for buyers.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_OPEN_DOCS else None,
    redoc_url="/redoc" if ENABLE_OPEN_DOCS else None,
    openapi_tags=[
        {"name": "go-to-market", "description": "Endpoints you can hand to procurement teams or a simple landing page."},
    ],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Include all routes
app.include_router(api_router)

@app.get("/", dependencies=[Depends(require_api_key)])
async def root():
    return {
        "message": "SocioMed Lean procurement API",
        "status": "running",
        "operating_model": "rfq_first",
        "audience": ["procurement teams", "suppliers"],
        "actions": {
            "featured_catalog": "/api/catalog/featured",
            "browse_categories": "/api/catalog/categories",
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
