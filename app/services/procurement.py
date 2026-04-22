from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import SALES_AGENT_PHONE
from app.core.utils import log_audit_event, notify_vendor, send_whatsapp_message
from app.data_access.procurement import create_buyer_lead_record, create_rfq_record, update_rfq_status
from app.models.db import BuyerLead, RFQRequest
from app.schemas.schemas import BuyerLeadCreate, RFQCreate


def create_buyer_lead(db: Session, payload: BuyerLeadCreate) -> BuyerLead:
    lead = create_buyer_lead_record(db, payload)
    log_audit_event(lead.phone, "buyer_lead_created", {"lead_id": lead.id, "organization": lead.organization})
    return lead


def create_rfq_request(db: Session, payload: RFQCreate) -> RFQRequest:
    rfq = create_rfq_record(db, payload)
    log_audit_event(
        rfq.phone,
        "rfq_created",
        {"rfq_id": rfq.id, "product_name": rfq.product_name, "vendor_id": rfq.vendor_id},
    )
    return rfq


def mark_rfq_status(db: Session, rfq_id: int, status: str) -> RFQRequest | None:
    rfq = update_rfq_status(db, rfq_id, status)
    if rfq:
        log_audit_event(rfq.phone, "rfq_status_updated", {"rfq_id": rfq.id, "status": rfq.status})
    return rfq


def _rfq_summary(rfq: RFQRequest) -> str:
    lines = [
        "New procurement RFQ",
        f"RFQ ID: {rfq.id}",
        f"Buyer: {rfq.buyer_name} ({rfq.organization})",
        f"Phone: {rfq.phone}",
        f"Product: {rfq.product_name}",
        f"Quantity: {rfq.quantity}",
        f"Delivery: {rfq.delivery_location}",
    ]
    if rfq.vendor_name:
        lines.append(f"Preferred supplier: {rfq.vendor_name}")
    if rfq.notes:
        lines.append(f"Notes: {rfq.notes}")
    return "\n".join(lines)


async def dispatch_rfq_notifications(rfq: RFQRequest, vendor_phone: Optional[str] = None) -> bool:
    supplier_notified = False

    if vendor_phone:
        supplier_notified = await notify_vendor(vendor_phone, _rfq_summary(rfq))

    if SALES_AGENT_PHONE:
        await send_whatsapp_message(SALES_AGENT_PHONE, _rfq_summary(rfq))

    return supplier_notified


async def dispatch_lead_notification(lead: BuyerLead) -> None:
    if not SALES_AGENT_PHONE:
        return

    message = (
        "New buyer lead\n"
        f"Lead ID: {lead.id}\n"
        f"Buyer: {lead.buyer_name}\n"
        f"Organization: {lead.organization}\n"
        f"Phone: {lead.phone}"
    )
    if lead.use_case:
        message += f"\nNeed: {lead.use_case}"

    await send_whatsapp_message(SALES_AGENT_PHONE, message)
