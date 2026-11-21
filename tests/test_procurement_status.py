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


def test_mark_rfq_status_validates_and_delegates(monkeypatch):
    from app.services import quote_workflow
    calls = []
    monkeypatch.setattr(quote_workflow, 'set_status', lambda *args: calls.append(args) or 'updated')
    assert procurement.mark_rfq_status(None, 7, ' Quoted ') == 'updated'
    assert calls == [(None, 7, 'quoted', None)]
    with pytest.raises(InvalidRFQStatus):
        procurement.mark_rfq_status(None, 7, 'Invalid')


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
