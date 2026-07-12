from collections import Counter
from datetime import datetime, timedelta

from app.core.config import SALES_AGENT_PHONE
from app.core.utils import log_audit_event, send_whatsapp_message_result
from app.data_access.procurement import get_recent_rfqs
from app.models.db import SessionLocal, Vendor
from app.services.procurement import estimate_commission


def build_daily_rfq_digest(now: datetime | None = None) -> str:
    current_time = now or datetime.utcnow()
    cutoff = current_time - timedelta(hours=24)
    db = SessionLocal()
    try:
        rfqs = get_recent_rfqs(db, cutoff)
        vendor_ids = {rfq.vendor_id for rfq in rfqs if rfq.vendor_id}
        vendors_by_id = (
            {vendor.vendor_id: vendor for vendor in db.query(Vendor).filter(Vendor.vendor_id.in_(vendor_ids)).all()}
            if vendor_ids
            else {}
        )
    finally:
        db.close()

    new_rfqs = [rfq for rfq in rfqs if rfq.created_at >= cutoff]
    status_changes = [
        rfq
        for rfq in rfqs
        if rfq.status_updated_at >= cutoff and rfq.status_updated_at > rfq.created_at
    ]
    statuses = Counter(rfq.status for rfq in rfqs)

    commission_totals: dict[str, int] = {}
    commission_lines = []
    for rfq in status_changes:
        if rfq.status not in {"confirmed", "fulfilled"}:
            continue
        commission = estimate_commission(rfq, vendors_by_id.get(rfq.vendor_id))
        if commission is None:
            continue
        commission_totals[rfq.currency] = commission_totals.get(rfq.currency, 0) + commission
        commission_lines.append(
            f"#{rfq.id} {rfq.product_name} — order {rfq.order_value:,} {rfq.currency}, "
            f"est. commission {commission:,} {rfq.currency} [{rfq.status}]"
        )

    lines = [
        "SocioMed daily RFQ digest (last 24h)",
        f"New RFQs: {len(new_rfqs)}",
        f"Status changes: {len(status_changes)}",
    ]
    if statuses:
        lines.append("Current statuses: " + ", ".join(f"{status} {count}" for status, count in sorted(statuses.items())))
    if commission_lines:
        totals_text = ", ".join(
            f"{amount:,} {currency}" for currency, amount in sorted(commission_totals.items())
        )
        lines.append(f"\nConfirmed/fulfilled with commission (est. total: {totals_text}):")
        lines.extend(commission_lines)
    if new_rfqs:
        lines.append("\nNew requests:")
        for rfq in new_rfqs[:10]:
            lines.append(f"#{rfq.id} {rfq.product_name} x{rfq.quantity} — {rfq.organization} [{rfq.status}]")
        if len(new_rfqs) > 10:
            lines.append(f"…and {len(new_rfqs) - 10} more")
    return "\n".join(lines)


async def send_daily_rfq_digest() -> bool:
    if not SALES_AGENT_PHONE:
        log_audit_event("system", "daily_rfq_digest_skipped", {"reason": "missing_sales_agent_phone"})
        return False

    result = await send_whatsapp_message_result(SALES_AGENT_PHONE, build_daily_rfq_digest())
    log_audit_event(
        "system",
        "daily_rfq_digest_sent" if result.success else "daily_rfq_digest_failed",
        result.to_audit_data(),
    )
    return result.success
