import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import SALES_AGENT_PHONE
from app.core.conversation_copy import conversation_message
from app.core.rfq_status import (
    BUYER_NOTIFIABLE_STATUSES,
    RFQ_STATUSES,
    InvalidRFQStatus,
    is_valid_rfq_status,
)
from app.core.utils import WhatsAppSendResult, log_audit_event, send_whatsapp_message, send_whatsapp_message_result
from app.data_access.funnel import record_funnel_event
from app.data_access.procurement import create_buyer_lead_record, create_rfq_record, update_rfq_status
from app.models.db import BuyerLead, RFQRequest, Vendor
from app.schemas.schemas import BuyerLeadCreate, RFQCreate


@dataclass(frozen=True)
class NotificationAttempt:
    channel: str
    recipient: Optional[str]
    success: bool
    skipped: bool = False
    reason: Optional[str] = None
    status_code: Optional[int] = None
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
    response_body: Optional[str] = None

    @classmethod
    def skipped_attempt(cls, channel: str, reason: str) -> "NotificationAttempt":
        return cls(channel=channel, recipient=None, success=False, skipped=True, reason=reason)

    @classmethod
    def from_send_result(cls, channel: str, result: WhatsAppSendResult) -> "NotificationAttempt":
        return cls(
            channel=channel,
            recipient=result.recipient,
            success=result.success,
            reason=None if result.success else result.error or "send_failed",
            status_code=result.status_code,
            provider_message_id=result.provider_message_id,
            error=result.error,
            response_body=result.response_body[:500] if result.response_body else None,
        )

    @classmethod
    def from_exception(cls, channel: str, recipient: Optional[str], exc: Exception) -> "NotificationAttempt":
        return cls(channel=channel, recipient=recipient, success=False, reason="send_exception", error=str(exc))

    def to_audit_data(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "recipient": self.recipient,
            "success": self.success,
            "skipped": self.skipped,
            "reason": self.reason,
            "status_code": self.status_code,
            "provider_message_id": self.provider_message_id,
            "error": self.error,
            "response_body": self.response_body,
        }


@dataclass(frozen=True)
class RFQNotificationDispatch:
    rfq_id: int
    supplier_attempt: NotificationAttempt
    sales_attempt: NotificationAttempt
    attempts: list[NotificationAttempt] = field(default_factory=list)

    @property
    def supplier_notified(self) -> bool:
        return self.supplier_attempt.success

    @property
    def status(self) -> str:
        if self.supplier_attempt.success:
            return "supplier_notified"
        if self.sales_attempt.success:
            return "manual_routing_required"
        return "notification_failed"

    @property
    def failure_reason(self) -> Optional[str]:
        if self.supplier_attempt.success:
            return None
        return self.supplier_attempt.reason or self.sales_attempt.reason


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
    record_funnel_event(
        "rfq_submitted",
        source=rfq.source,
        actor_id=rfq.phone,
        rfq_id=rfq.id,
        data={"product_id": rfq.product_id, "product_name": rfq.product_name, "quantity": rfq.quantity},
    )
    return rfq


def _normalize_rfq_status(status: str) -> str:
    return re.sub(r"[\s-]+", "_", status.strip().lower())


def mark_rfq_status(
    db: Session,
    rfq_id: int,
    status: str,
    order_value: int | None = None,
) -> RFQRequest | None:
    normalized = _normalize_rfq_status(status)
    if not is_valid_rfq_status(normalized):
        raise InvalidRFQStatus(
            f"'{status}' is not a recognized RFQ status. Use one of: {', '.join(RFQ_STATUSES)}."
        )

    rfq = update_rfq_status(db, rfq_id, normalized, order_value=order_value)
    if rfq:
        log_audit_event(rfq.phone, "rfq_status_updated", {"rfq_id": rfq.id, "status": rfq.status})
        record_funnel_event(
            "rfq_status_changed",
            source="api",
            actor_id=rfq.phone,
            rfq_id=rfq.id,
            data={"status": rfq.status, "order_value": rfq.order_value},
        )
    return rfq


BUYER_STATUS_MESSAGES = {
    "confirmed": "buyer_status_confirmed",
    "fulfilled": "buyer_status_fulfilled",
}


async def notify_buyer_of_status_change(rfq: RFQRequest) -> bool:
    """Notify a buyer when an RFQ reaches a buyer-relevant milestone."""
    if rfq.status not in BUYER_NOTIFIABLE_STATUSES:
        return False

    copy_key = BUYER_STATUS_MESSAGES.get(rfq.status)
    if not copy_key:
        return False

    message = conversation_message(copy_key, rfq_id=rfq.id, product_name=rfq.product_name)
    result = await send_whatsapp_message_result(rfq.phone, message)
    log_audit_event(
        rfq.phone,
        "rfq_status_buyer_notified" if result.success else "rfq_status_buyer_notify_failed",
        {"rfq_id": rfq.id, "status": rfq.status, **result.to_audit_data()},
    )
    return result.success


def estimate_commission(rfq: RFQRequest, vendor: Vendor | None) -> int | None:
    """Estimate commission when both final order value and vendor rate are known."""
    if rfq.order_value is None or not vendor or vendor.commission_rate is None:
        return None
    return round(rfq.order_value * (vendor.commission_rate / 100))


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
    dispatch = await dispatch_rfq_notifications_detail(rfq, vendor_phone)
    return dispatch.supplier_notified


async def _send_notification(channel: str, recipient: Optional[str], message: str) -> NotificationAttempt:
    if not recipient:
        return NotificationAttempt.skipped_attempt(channel, f"missing_{channel}_phone")

    try:
        result = await send_whatsapp_message_result(recipient, message)
        return NotificationAttempt.from_send_result(channel, result)
    except Exception as exc:
        return NotificationAttempt.from_exception(channel, recipient, exc)


def _audit_notification_attempt(rfq: RFQRequest, attempt: NotificationAttempt) -> None:
    if attempt.skipped:
        outcome = "skipped"
    elif attempt.success:
        outcome = "sent"
    else:
        outcome = "failed"

    log_audit_event(
        rfq.phone,
        f"rfq_{attempt.channel}_notification_{outcome}",
        {
            "rfq_id": rfq.id,
            "product_name": rfq.product_name,
            "product_id": rfq.product_id,
            "vendor_id": rfq.vendor_id,
            "vendor_name": rfq.vendor_name,
            **attempt.to_audit_data(),
        },
    )


async def dispatch_rfq_notifications_detail(
    rfq: RFQRequest,
    vendor_phone: Optional[str] = None,
) -> RFQNotificationDispatch:
    summary = _rfq_summary(rfq)
    supplier_attempt = await _send_notification("supplier", vendor_phone, summary)
    _audit_notification_attempt(rfq, supplier_attempt)

    sales_attempt = await _send_notification("sales", SALES_AGENT_PHONE, summary)
    _audit_notification_attempt(rfq, sales_attempt)

    dispatch = RFQNotificationDispatch(
        rfq_id=rfq.id,
        supplier_attempt=supplier_attempt,
        sales_attempt=sales_attempt,
        attempts=[supplier_attempt, sales_attempt],
    )

    if not dispatch.supplier_notified:
        log_audit_event(
            rfq.phone,
            "rfq_manual_routing_required",
            {
                "rfq_id": rfq.id,
                "status": dispatch.status,
                "reason": dispatch.failure_reason,
                "sales_notified": sales_attempt.success,
            },
        )

    record_funnel_event(
        "rfq_notified" if dispatch.supplier_notified else "rfq_notification_failed",
        source=rfq.source,
        actor_id=rfq.phone,
        rfq_id=rfq.id,
        data={
            "status": dispatch.status,
            "supplier_notified": dispatch.supplier_notified,
            "sales_notified": sales_attempt.success,
            "failure_reason": dispatch.failure_reason,
        },
    )

    return dispatch


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
