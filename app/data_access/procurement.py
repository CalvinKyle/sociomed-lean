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


def update_rfq_status(db: Session, rfq_id: int, status: str) -> RFQRequest | None:
    rfq = db.query(RFQRequest).filter(RFQRequest.id == rfq_id).first()
    if not rfq:
        return None
    rfq.status = status
    db.commit()
    db.refresh(rfq)
    return rfq
