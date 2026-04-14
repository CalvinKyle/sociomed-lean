from fastapi import FastAPI
from app.api.routes import router as api_router
from app.core.config import validate_config
from app.core.logging_config import setup_logging
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    validate_config()
    print("🚀 SocioMed Lean WhatsApp Marketplace started successfully!")
    yield

app = FastAPI(
    title="SocioMed Lean",
    description="WhatsApp-native medical supplies marketplace",
    version="2.0.0",
    lifespan=lifespan
)

# Include all routes
app.include_router(api_router, prefix="")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
