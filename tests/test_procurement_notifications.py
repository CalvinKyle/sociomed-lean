import asyncio

from app.core.utils import WhatsAppSendResult
from app.models.db import RFQRequest
from app.services import procurement


def _rfq() -> RFQRequest:
    return RFQRequest(
        id=42,
        buyer_name="Buyer",
        organization="Mulago Hospital",
        phone="+256700000000",
        product_id="P-GLOVE",
        product_name="Surgical Gloves",
        vendor_id="V-1",
        vendor_name="MedSource",
        quantity=10,
        delivery_location="Kampala",
        source="test",
    )


def test_dispatch_records_failed_supplier_notification_and_sales_fallback(monkeypatch):
    audit_events = []

    async def fake_send(recipient, _message):
        if recipient == "+256700111111":
            return WhatsAppSendResult(
                recipient=recipient,
                success=False,
                status_code=400,
                error="whatsapp_api_error",
                response_body='{"error":"invalid phone"}',
            )
        return WhatsAppSendResult(recipient=recipient, success=True, status_code=200, provider_message_id="wamid.sales")

    monkeypatch.setattr(procurement, "SALES_AGENT_PHONE", "+256700222222")
    monkeypatch.setattr(procurement, "send_whatsapp_message_result", fake_send)
    monkeypatch.setattr(procurement, "log_audit_event", lambda phone, event, data: audit_events.append((phone, event, data)))

    dispatch = asyncio.run(procurement.dispatch_rfq_notifications_detail(_rfq(), "+256700111111"))

    assert dispatch.supplier_notified is False
    assert dispatch.status == "manual_routing_required"
    assert dispatch.failure_reason == "whatsapp_api_error"
    assert ("+256700000000", "rfq_supplier_notification_failed", audit_events[0][2]) in audit_events
    assert any(event == "rfq_sales_notification_sent" for _, event, _ in audit_events)
    assert any(event == "rfq_manual_routing_required" for _, event, _ in audit_events)


def test_dispatch_audits_missing_vendor_phone_without_failing_rfq(monkeypatch):
    audit_events = []

    async def fake_send(recipient, _message):
        return WhatsAppSendResult(recipient=recipient, success=True, status_code=200)

    monkeypatch.setattr(procurement, "SALES_AGENT_PHONE", "+256700222222")
    monkeypatch.setattr(procurement, "send_whatsapp_message_result", fake_send)
    monkeypatch.setattr(procurement, "log_audit_event", lambda phone, event, data: audit_events.append((phone, event, data)))

    dispatch = asyncio.run(procurement.dispatch_rfq_notifications_detail(_rfq(), None))

    assert dispatch.supplier_notified is False
    assert dispatch.failure_reason == "missing_supplier_phone"
    assert any(event == "rfq_supplier_notification_skipped" for _, event, _ in audit_events)
    assert any(event == "rfq_sales_notification_sent" for _, event, _ in audit_events)


def test_dispatch_captures_send_exceptions_as_audit_failures(monkeypatch):
    audit_events = []

    async def fake_send(_recipient, _message):
        raise TimeoutError("provider timeout")

    monkeypatch.setattr(procurement, "SALES_AGENT_PHONE", "+256700222222")
    monkeypatch.setattr(procurement, "send_whatsapp_message_result", fake_send)
    monkeypatch.setattr(procurement, "log_audit_event", lambda phone, event, data: audit_events.append((phone, event, data)))

    dispatch = asyncio.run(procurement.dispatch_rfq_notifications_detail(_rfq(), "+256700111111"))

    assert dispatch.status == "notification_failed"
    assert dispatch.failure_reason == "send_exception"
    assert any(event == "rfq_supplier_notification_failed" for _, event, _ in audit_events)
    assert any(event == "rfq_sales_notification_failed" for _, event, _ in audit_events)
