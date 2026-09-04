from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.db import BuyerLead, BuyerProfile, RFQLineItem, RFQRequest
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
    items = payload.resolved_items()
    primary = items[0]
    summary_name = (
        primary.product_name
        if len(items) == 1
        else f"{primary.product_name} +{len(items) - 1} more"
    )

    rfq = RFQRequest(
        buyer_name=payload.buyer_name.strip(),
        organization=payload.organization.strip(),
        phone=payload.phone.strip(),
        email=payload.email,
        product_id=primary.product_id,
        product_name=summary_name,
        vendor_id=primary.vendor_id,
        vendor_name=primary.vendor_name,
        quantity=primary.quantity,
        delivery_location=payload.delivery_location.strip(),
        notes=payload.notes,
        currency=payload.currency,
        source=payload.source,
        status="new",
        procurement_stage=payload.procurement_stage,
        formal_quote=payload.formal_quote,
        required_by=payload.required_by,
        payment_preference=payload.payment_preference,
        destination_country=payload.destination_country,
        equipment_review_required=payload.equipment_review_required,
        manual_review_reason=payload.manual_review_reason,
    )
    db.add(rfq)
    db.flush()

    for item in items:
        db.add(
            RFQLineItem(
                rfq_id=rfq.id,
                product_id=item.product_id,
                product_name=item.product_name.strip(),
                vendor_id=item.vendor_id,
                vendor_name=item.vendor_name,
                quantity=item.quantity,
                uom=item.uom,
                unit_price=item.unit_price,
                line_total=item.unit_price * item.quantity if item.unit_price is not None else None,
            )
        )

    profile = db.get(BuyerProfile, payload.phone.strip())
    if profile is None:
        profile = BuyerProfile(
            phone=payload.phone.strip(),
            contact_name=payload.buyer_name.strip(),
            organization=payload.organization.strip(),
        )
        db.add(profile)
    profile.contact_name = payload.buyer_name.strip()
    profile.organization = payload.organization.strip()
    profile.delivery_location = payload.delivery_location.strip()
    profile.destination_country = payload.destination_country if hasattr(profile, "destination_country") else None
    profile.preferred_currency = payload.currency

    db.commit()
    db.refresh(rfq)
    return rfq


def get_buyer_profile(db: Session, phone: str) -> BuyerProfile | None:
    return db.get(BuyerProfile, phone.strip())


def get_rfq_line_items(db: Session, rfq_id: int) -> list[RFQLineItem]:
    return (
        db.query(RFQLineItem)
        .filter(RFQLineItem.rfq_id == rfq_id)
        .order_by(RFQLineItem.id)
        .all()
    )


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
