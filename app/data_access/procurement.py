from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.db import BuyerLead, RFQRequest
from app.schemas.schemas import BuyerLeadCreate, RFQCreate


def create_buyer_lead_record(db: Session, payload: BuyerLeadCreate) -> BuyerLead:
    lead = BuyerLead(
        buyer_name=payload.buyer_name.strip(),
        organization=payload.organization.strip(),
        phone=payload.phone.strip(),
        email=payload.email,
        role=payload.role,
        country=payload.country,
        use_case=payload.use_case,
        source=payload.source,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def create_rfq_record(db: Session, payload: RFQCreate) -> RFQRequest:
    rfq = RFQRequest(
        buyer_name=payload.buyer_name.strip(),
        organization=payload.organization.strip(),
        phone=payload.phone.strip(),
        email=payload.email,
        product_id=payload.product_id,
        product_name=payload.product_name.strip(),
        vendor_id=payload.vendor_id,
        vendor_name=payload.vendor_name,
        quantity=payload.quantity,
        delivery_location=payload.delivery_location.strip(),
        notes=payload.notes,
        currency=payload.currency,
        source=payload.source,
        status="new",
    )
    db.add(rfq)
    db.commit()
    db.refresh(rfq)
    return rfq


def update_rfq_status(
    db: Session,
    rfq_id: int,
    status: str,
    order_value: int | None = None,
) -> RFQRequest | None:
    rfq = db.query(RFQRequest).filter(RFQRequest.id == rfq_id).first()
    if not rfq:
        return None
    rfq.status = status
    rfq.status_updated_at = datetime.utcnow()
    if order_value is not None:
        rfq.order_value = order_value
    db.commit()
    db.refresh(rfq)
    return rfq


def get_recent_rfqs(db: Session, since: datetime | None = None) -> list[RFQRequest]:
    cutoff = since or datetime.utcnow() - timedelta(hours=24)
    return (
        db.query(RFQRequest)
        .filter(or_(RFQRequest.created_at >= cutoff, RFQRequest.status_updated_at >= cutoff))
        .order_by(RFQRequest.created_at.desc())
        .all()
    )
