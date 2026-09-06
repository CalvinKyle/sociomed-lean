from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import router as api_router
from app.core.auth import require_api_key
from app.core.config import ENABLE_OPEN_DOCS, PUBLIC_BASE_URL, WHATSAPP_PROVIDER, validate_config
from app.core.logging_config import setup_logging
from app.core.rate_limit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    setup_logging()
    validate_config()
    print("🚀 SocioMED Lean procurement backend is now running!")
    yield
    # Optional: clean shutdown logic here later


app = FastAPI(
    title="SocioMED Lean",
    description="Procurement-ready WhatsApp marketplace for medical suppliers and buyers.",
    version="2.1.0",
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
        "message": "SocioMED Lean procurement API",
        "status": "running",
        "operating_model": "rfq_first",
        "whatsapp_provider": WHATSAPP_PROVIDER,
        "audience": ["procurement teams", "suppliers"],
        "actions": {
            "featured_catalog": "/api/catalog/featured",
            "browse_categories": "/api/catalog/categories",
            "catalog_search_example": "/api/catalog/search?q=surgical gloves",
            "submit_rfq": "/api/rfqs",
            "capture_lead": "/api/leads",
            "meta_whatsapp_webhook": "/api/webhook",
            "twilio_whatsapp_webhook": "/api/webhook/twilio",
            "twilio_delivery_status": "/api/webhook/twilio/status",
        },
        "docs": "/docs" if ENABLE_OPEN_DOCS else None,
        "public_base_url": PUBLIC_BASE_URL or None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
