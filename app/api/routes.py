import hashlib
import hmac
import json
import os
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from twilio.request_validator import RequestValidator

from app.core.auth import require_api_key
from app.core.config import (
    ASYNC_WHATSAPP_PROCESSING,
    GOOGLE_CREDS_FILE,
    GOOGLE_CREDS_JSON,
    TWILIO_AUTH_TOKEN,
    TWILIO_STATUS_CALLBACK_URL,
    TWILIO_WEBHOOK_URL,
    VERIFY_TOKEN,
    WHATSAPP_APP_SECRET,
)
from app.core.rate_limit import limiter
from app.core.rfq_status import InvalidRFQStatus
from app.core.utils import (
    claim_whatsapp_message,
    log_audit_event,
    redis_client,
    release_whatsapp_message_claim,
)
from app.data_access.catalog import get_categories
from app.data_access.funnel import record_funnel_event
from app.data_access.procurement import get_rfq_line_items
from app.models.db import RFQRequest, SessionLocal, get_db
from app.schemas.schemas import (
    BuyerLeadCreate,
    BuyerLeadResponse,
    CatalogCategoriesResponse,
    CatalogSearchResponse,
    FeaturedCatalogResponse,
    RFQCreate,
    RFQResponse,
    RFQStatusResponse,
    RFQStatusUpdate,
)
from app.services.catalog import get_featured_catalog, search_catalog
from app.services.procurement import (
    create_buyer_lead,
    create_rfq_request,
    dispatch_lead_notification,
    dispatch_rfq_notifications_detail,
    mark_rfq_status,
    notify_buyer_of_status_change,
)
from app.services.pfi_generator import generate_pfi_pdf, resolve_pfi_number
from app.services.tasks import process_whatsapp_message
from app.services.twilio_adapter import extract_twilio_message
from app.services.whatsapp_processing import process_whatsapp_message_now
from app.services.whatsapp_service import extract_message

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


def _parse_twilio_form(body: bytes) -> dict[str, str]:
    return dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))


def _verify_twilio_signature(
    request: Request,
    form_data: dict[str, str],
    signature: str | None,
    configured_url: str | None,
) -> bool:
    if not TWILIO_AUTH_TOKEN or not signature:
        return False
    request_url = configured_url or str(request.url)
    return RequestValidator(TWILIO_AUTH_TOKEN).validate(request_url, form_data, signature)


def _empty_twiml_response() -> Response:
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
    )


@router.get("/health/liveness")
async def liveness_check():
    return {"status": "ok"}


@router.get("/health", dependencies=[Depends(require_api_key)])
async def health_check():
    checks = {"db": False, "redis": False, "sheets_credentials": False}

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        checks["db"] = True
    except Exception as exc:
        log_audit_event("system", "health_db_failed", {"error": str(exc)})
    finally:
        db.close()

    try:
        checks["redis"] = bool(redis_client.ping())
    except Exception as exc:
        log_audit_event("system", "health_redis_failed", {"error": str(exc)})

    checks["sheets_credentials"] = bool(GOOGLE_CREDS_JSON) or (
        bool(GOOGLE_CREDS_FILE) and os.path.exists(GOOGLE_CREDS_FILE)
    )

    status = "healthy" if all(checks.values()) else "degraded"
    return JSONResponse(
        status_code=200 if status == "healthy" else 503,
        content={
            "status": status,
            "service": "sociomed-lean",
            "audience": ["procurement-teams", "suppliers"],
            "checks": checks,
        },
    )


@router.get("/catalog/featured", response_model=FeaturedCatalogResponse, tags=["go-to-market"])
async def featured_catalog(
    limit: int = Query(default=6, ge=1, le=20),
    currency: str = Query(default="UGX", description="Currency code (UGX, KES, etc.)")
):
    """Featured catalog offers in buyer's currency."""
    featured = get_featured_catalog(limit=limit, currency=currency)
    return FeaturedCatalogResponse(total_featured=len(featured), featured=featured)


@router.get("/catalog/categories", response_model=CatalogCategoriesResponse, tags=["go-to-market"])
async def catalog_categories():
    categories = get_categories()
    return CatalogCategoriesResponse(total_categories=len(categories), categories=categories)


@router.get("/catalog/search", response_model=CatalogSearchResponse, tags=["go-to-market"])
async def public_catalog_search(
    q: str = Query(..., min_length=2, description="Search term from a procurement buyer"),
    limit: int = Query(default=5, ge=1, le=20),
    currency: str = Query(default="UGX", description="Currency code (UGX, KES, etc.)")
):
    """Search catalog with results in buyer's currency."""
    matches = search_catalog(q, limit=limit, currency=currency)
    record_funnel_event(
        "search",
        source="api",
        data={"query": q, "limit": limit, "currency": currency},
    )
    record_funnel_event(
        "results",
        source="api",
        data={"query": q, "result_count": len(matches), "product_ids": [match["product_id"] for match in matches]},
    )
    return CatalogSearchResponse(query=q, total_matches=len(matches), matches=matches)


@router.post(
    "/leads",
    response_model=BuyerLeadResponse,
    status_code=201,
    tags=["go-to-market"],
    dependencies=[Depends(require_api_key)],
)
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


@router.post(
    "/rfqs",
    response_model=RFQResponse,
    status_code=201,
    tags=["go-to-market"],
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("20/minute")
async def create_rfq(request: Request, payload: RFQCreate, db: Session = Depends(get_db)):
    rfq = create_rfq_request(db, payload)
    dispatch = await dispatch_rfq_notifications_detail(rfq, payload.vendor_phone)
    return RFQResponse(
        rfq_id=rfq.id,
        status=rfq.status,
        supplier_notified=dispatch.supplier_notified,
        notification_status=dispatch.status,
        notification_failure_reason=dispatch.failure_reason,
        created_at=rfq.created_at,
    )


@router.patch(
    "/rfqs/{rfq_id}/status",
    response_model=RFQStatusResponse,
    tags=["go-to-market"],
    dependencies=[Depends(require_api_key)],
)
async def update_rfq_status_endpoint(rfq_id: int, payload: RFQStatusUpdate, db: Session = Depends(get_db)):
    try:
        rfq = mark_rfq_status(db, rfq_id, payload.status, order_value=payload.order_value)
    except InvalidRFQStatus as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not rfq:
        raise HTTPException(status_code=404, detail="rfq not found")
    await notify_buyer_of_status_change(rfq)
    return RFQStatusResponse(rfq_id=rfq.id, status=rfq.status)


@router.get(
    "/rfqs/{rfq_id}/pfi.pdf",
    tags=["go-to-market"],
    dependencies=[Depends(require_api_key)],
)
def download_rfq_pfi(rfq_id: int, db: Session = Depends(get_db)):
    rfq = db.query(RFQRequest).filter(RFQRequest.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    line_items = get_rfq_line_items(db, rfq_id)
    if not line_items:
        raise HTTPException(status_code=422, detail="RFQ has no line items to quote yet")

    resolve_pfi_number(rfq)
    pdf_bytes = generate_pfi_pdf(rfq, line_items)
    db.commit()

    safe_reference = rfq.pfi_reference.replace("/", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="PFI_{safe_reference}.pdf"'},
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
@limiter.limit("60/minute")
async def whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
):
    try:
        body_bytes = await request.body()
        if not _verify_whatsapp_signature(body_bytes, x_hub_signature_256):
            raise HTTPException(status_code=403, detail="invalid webhook signature")

        body = json.loads(body_bytes.decode("utf-8") or "{}")
        message = extract_message(body)

        if not message:
            return {"status": "ignored"}

        if not claim_whatsapp_message(message.get("id")):
            log_audit_event(
                message.get("from", "unknown"),
                "webhook_duplicate_message_skipped",
                {"message_id": message.get("id"), "provider": "meta"},
            )
            return {"status": "duplicate_ignored"}

        process_whatsapp_message.delay(message)

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as exc:
        log_audit_event("system", "webhook_error", {"error": str(exc), "provider": "meta"})
        return JSONResponse(status_code=500, content={"status": "error"})


@router.post("/webhook/twilio")
@limiter.limit("60/minute")
async def twilio_whatsapp_webhook(
    request: Request,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
):
    processing_mode = "celery" if ASYNC_WHATSAPP_PROCESSING else "synchronous"

    try:
        body_bytes = await request.body()
        form_data = _parse_twilio_form(body_bytes)
        if not _verify_twilio_signature(request, form_data, x_twilio_signature, TWILIO_WEBHOOK_URL):
            raise HTTPException(status_code=403, detail="invalid Twilio webhook signature")

        message = extract_twilio_message(form_data)
        if not message:
            return _empty_twiml_response()

        message_id = message.get("id")
        if not claim_whatsapp_message(message_id):
            log_audit_event(
                message.get("from", "unknown"),
                "webhook_duplicate_message_skipped",
                {"message_id": message_id, "provider": "twilio"},
            )
            return _empty_twiml_response()

        try:
            if ASYNC_WHATSAPP_PROCESSING:
                process_whatsapp_message.delay(message)
            else:
                await process_whatsapp_message_now(message)
        except Exception:
            release_whatsapp_message_claim(message_id)
            raise

        return _empty_twiml_response()

    except HTTPException:
        raise
    except Exception as exc:
        log_audit_event(
            "system",
            "webhook_error",
            {"error": str(exc), "provider": "twilio", "processing_mode": processing_mode},
        )
        return JSONResponse(status_code=500, content={"status": "error"})


@router.post("/webhook/twilio/status")
@limiter.limit("120/minute")
async def twilio_whatsapp_status_callback(
    request: Request,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
):
    body_bytes = await request.body()
    form_data = _parse_twilio_form(body_bytes)
    if not _verify_twilio_signature(request, form_data, x_twilio_signature, TWILIO_STATUS_CALLBACK_URL):
        raise HTTPException(status_code=403, detail="invalid Twilio status signature")

    log_audit_event(
        form_data.get("To", "unknown"),
        "twilio_whatsapp_delivery_status",
        {
            "message_sid": form_data.get("MessageSid"),
            "message_status": form_data.get("MessageStatus"),
            "error_code": form_data.get("ErrorCode"),
            "error_message": form_data.get("ErrorMessage"),
        },
    )
    return Response(status_code=204)
