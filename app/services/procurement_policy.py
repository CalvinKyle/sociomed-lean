from dataclasses import dataclass
from typing import Mapping, Optional


SALES_NOTIFICATION_REASONS = {
    "formal_purchase",
    "sales_handoff",
    "sourcing_request",
    "unmatched_request",
    "multi_item_request",
    "equipment_technical_review",
}


@dataclass(frozen=True)
class SalesNotificationDecision:
    notify: bool
    reason: Optional[str] = None


def sales_notification_decision(context: Mapping[str, object]) -> SalesNotificationDecision:
    reason = str(context.get("reason") or "").strip().lower()
    if reason in SALES_NOTIFICATION_REASONS:
        return SalesNotificationDecision(True, reason)
    if bool(context.get("formal_purchase")):
        return SalesNotificationDecision(True, "formal_purchase")
    if bool(context.get("equipment_review_required")):
        return SalesNotificationDecision(True, "equipment_technical_review")
    if int(context.get("item_count") or 0) > 1:
        return SalesNotificationDecision(True, "multi_item_request")
    return SalesNotificationDecision(False)


def should_notify_sales(context: Mapping[str, object]) -> bool:
    return sales_notification_decision(context).notify


def is_equipment_product(product: Mapping[str, object]) -> bool:
    haystack = " ".join(
        str(product.get(field) or "").lower()
        for field in ("name", "category", "clinical_speciality")
    )
    return any(
        marker in haystack
        for marker in (
            "equipment",
            "device",
            "monitor",
            "machine",
            "analyzer",
            "chair",
            "ultrasound",
            "x-ray",
            "ventilator",
            "autoclave",
        )
    )
