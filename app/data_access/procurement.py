from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.db import BuyerLead, RFQLineItem, RFQRequest
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
        procurement_stage=payload.procurement_stage,
        required_delivery_date=payload.required_delivery_date,
        notes=payload.notes,
        currency=payload.currency,
        source=payload.source,
        status="new",
        manual_review_required=payload.manual_review_required,
        manual_review_reason=payload.manual_review_reason,
        requires_credit=payload.requires_credit,
        technical_review_required=payload.technical_review_required,
        special_fulfilment_required=payload.special_fulfilment_required,
    )
    db.add(rfq)
    db.flush()

    for item in items:
        db.add(
            RFQLineItem(
                rfq_id=rfq.id,
                inventory_id=item.inventory_id,
                product_id=item.product_id,
                product_name=item.product_name.strip(),
                brand=item.brand,
                sku=item.sku,
                item_type=item.item_type,
                vendor_id=item.vendor_id,
                vendor_name=item.vendor_name,
                is_own_inventory=item.is_own_inventory,
                quantity=item.quantity,
                uom=item.uom,
                unit_price=item.unit_price,
                line_total=item.unit_price * item.quantity if item.unit_price is not None else None,
                currency=item.currency or payload.currency,
                price_source=item.price_source,
                stock_verification_status=item.stock_verification_status,
            )
        )

    db.commit()
    db.refresh(rfq)
    return rfq


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
    payment_confirmation_reference: str | None = None,
) -> RFQRequest | None:
    rfq = db.query(RFQRequest).filter(RFQRequest.id == rfq_id).first()
    if not rfq:
        return None
    changed = rfq.status != status
    rfq.status = status
    if order_value is not None:
        changed = changed or rfq.order_value != order_value
        rfq.order_value = order_value
    if payment_confirmation_reference is not None:
        changed = changed or rfq.payment_confirmation_reference != payment_confirmation_reference
        rfq.payment_confirmation_reference = payment_confirmation_reference
    if changed:
        rfq.status_updated_at = datetime.utcnow()
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
