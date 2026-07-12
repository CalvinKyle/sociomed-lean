import asyncio

import pytest

from app.core.rfq_status import InvalidRFQStatus
from app.core.utils import WhatsAppSendResult
from app.services import procurement


class _FakeQuery:
    def __init__(self, rfq):
        self.rfq = rfq

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.rfq


class _FakeDb:
    def __init__(self, rfq):
        self.rfq = rfq
        self.committed = False
        self.refreshed = False

    def query(self, _model):
        return _FakeQuery(self.rfq)

    def commit(self):
        self.committed = True

    def refresh(self, _rfq):
        self.refreshed = True


def test_mark_rfq_status_updates_through_data_access(monkeypatch):
    audit_events = []
    funnel_events = []
    rfq = type("RFQ", (), {"id": 7, "phone": "+256700000000", "status": "new", "order_value": None})()
    db = _FakeDb(rfq)
    monkeypatch.setattr(procurement, "log_audit_event", lambda phone, event, data: audit_events.append((phone, event, data)))
    monkeypatch.setattr(procurement, "record_funnel_event", lambda *args, **kwargs: funnel_events.append((args, kwargs)))

    updated = procurement.mark_rfq_status(db, 7, " Quoted ")

    assert updated is rfq
    assert updated.status == "quoted"
    assert db.committed
    assert db.refreshed
    assert audit_events == [
        ("+256700000000", "rfq_status_updated", {"rfq_id": 7, "status": "quoted"})
    ]
    assert funnel_events[0][0] == ("rfq_status_changed",)


def test_mark_rfq_status_rejects_unknown_status(monkeypatch):
    rfq = type("RFQ", (), {"id": 8, "phone": "+256700000000", "status": "new", "order_value": None})()
    db = _FakeDb(rfq)

    with pytest.raises(InvalidRFQStatus, match="new, quoted, confirmed"):
        procurement.mark_rfq_status(db, 8, " In Review ")

    assert not db.committed


def test_mark_rfq_status_persists_order_value(monkeypatch):
    rfq = type("RFQ", (), {"id": 9, "phone": "+256700000000", "status": "new", "order_value": None})()
    db = _FakeDb(rfq)
    monkeypatch.setattr(procurement, "log_audit_event", lambda *_args: None)
    monkeypatch.setattr(procurement, "record_funnel_event", lambda *_args, **_kwargs: None)

    updated = procurement.mark_rfq_status(db, 9, "confirmed", order_value=1_000_000)

    assert updated.order_value == 1_000_000


def test_estimate_commission_requires_value_and_rate():
    rfq = type("RFQ", (), {"order_value": 200_000})()
    vendor = type("Vendor", (), {"commission_rate": 8.5})()

    assert procurement.estimate_commission(rfq, vendor) == 17_000
    assert procurement.estimate_commission(type("RFQ", (), {"order_value": None})(), vendor) is None
    assert procurement.estimate_commission(rfq, type("Vendor", (), {"commission_rate": None})()) is None


def test_notify_buyer_only_for_buyer_milestones(monkeypatch):
    sent = []
    audits = []

    async def fake_send(phone, message):
        sent.append((phone, message))
        return WhatsAppSendResult(recipient=phone, success=True)

    monkeypatch.setattr(procurement, "send_whatsapp_message_result", fake_send)
    monkeypatch.setattr(procurement, "log_audit_event", lambda *args: audits.append(args))
    quoted = type("RFQ", (), {"id": 10, "phone": "+256700000000", "status": "quoted", "product_name": "Gloves"})()
    confirmed = type("RFQ", (), {"id": 10, "phone": "+256700000000", "status": "confirmed", "product_name": "Gloves"})()

    assert asyncio.run(procurement.notify_buyer_of_status_change(quoted)) is False
    assert asyncio.run(procurement.notify_buyer_of_status_change(confirmed)) is True
    assert len(sent) == 1
    assert "RFQ #10" in sent[0][1]
    assert audits[0][1] == "rfq_status_buyer_notified"
