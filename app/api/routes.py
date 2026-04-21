import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import VERIFY_TOKEN, WHATSAPP_APP_SECRET
from app.core.utils import log_audit_event
from app.models.db import get_db
from app.schemas.schemas import (
    BuyerLeadCreate,
    BuyerLeadResponse,
    CatalogSearchResponse,
    FeaturedCatalogResponse,
    RFQCreate,
    RFQResponse,
)
from app.services.catalog import get_featured_catalog, search_catalog
from app.services.procurement import (
    create_buyer_lead,
    create_rfq_request,
    dispatch_lead_notification,
    dispatch_rfq_notifications,
)
from app.services.tasks import process_whatsapp_message
from app.services.whatsapp_service import (
    extract_message,
)

router = APIRouter(prefix="/api")


def _verify_whatsapp_signature(body: bytes, signature: str | None) -> bool:
    if not WHATSAPP_APP_SECRET:
        return True
    if not signature or not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature.split("=", 1)[1], expected)


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "sociomed-lean",
        "audience": ["procurement-teams", "suppliers"],
    }


@router.get("/catalog/featured", response_model=FeaturedCatalogResponse, tags=["go-to-market"])
async def featured_catalog(
    limit: int = Query(default=6, ge=1, le=20),
    currency: str = Query(default="UGX", description="Currency code (UGX, KES, etc.)")
):
    """Featured catalog offers in buyer's currency."""
    featured = get_featured_catalog(limit=limit, currency=currency)
    return FeaturedCatalogResponse(total_featured=len(featured), featured=featured)

@router.get("/catalog/search", response_model=CatalogSearchResponse, tags=["go-to-market"])
async def public_catalog_search(
    q: str = Query(..., min_length=2, description="Search term from a procurement buyer"),
    limit: int = Query(default=5, ge=1, le=20),
    currency: str = Query(default="UGX", description="Currency code (UGX, KES, etc.)")
):
    """Search catalog with results in buyer's currency."""
    matches = search_catalog(q, limit=limit, currency=currency)
    return CatalogSearchResponse(query=q, total_matches=len(matches), matches=matches)

@router.post("/leads", response_model=BuyerLeadResponse, status_code=201, tags=["go-to-market"])
async def capture_buyer_lead(payload: BuyerLeadCreate, db: Session = Depends(get_db)):
    lead = create_buyer_lead(db, payload)
    await dispatch_lead_notification(lead)
    return BuyerLeadResponse(
        lead_id=lead.id,
        status="captured",
        buyer_name=lead.buyer_name,
        organization=lead.organization,
        created_at=lead.created_at,
    )


@router.post("/rfqs", response_model=RFQResponse, status_code=201, tags=["go-to-market"])
async def create_public_rfq(payload: RFQCreate, db: Session = Depends(get_db)):
    rfq = create_rfq_request(db, payload)
    supplier_notified = await dispatch_rfq_notifications(rfq, payload.vendor_phone)
    return RFQResponse(
        rfq_id=rfq.id,
        status=rfq.status,
        supplier_notified=supplier_notified,
        created_at=rfq.created_at,
    )


@router.get("/webhook")
async def verify_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/webhook")
async def whatsapp_webhook(
    req: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
):
    try:
        body_bytes = await req.body()
        if not _verify_whatsapp_signature(body_bytes, x_hub_signature_256):
            raise HTTPException(status_code=403, detail="invalid webhook signature")

        body = json.loads(body_bytes.decode("utf-8") or "{}")
        message = extract_message(body)

        if not message:
            return {"status": "ignored"}

        process_whatsapp_message.delay(message)

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        log_audit_event("system", "webhook_error", {"error": str(e)})
        return JSONResponse(status_code=500, content={"status": "error"})
