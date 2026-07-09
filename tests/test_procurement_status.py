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
    rfq = type("RFQ", (), {"id": 7, "phone": "+256700000000", "status": "new"})()
    db = _FakeDb(rfq)
    monkeypatch.setattr(procurement, "log_audit_event", lambda phone, event, data: audit_events.append((phone, event, data)))

    updated = procurement.mark_rfq_status(db, 7, " Quoted ")

    assert updated is rfq
    assert updated.status == "quoted"
    assert db.committed
    assert db.refreshed
    assert audit_events == [
        ("+256700000000", "rfq_status_updated", {"rfq_id": 7, "status": "quoted"})
    ]


def test_mark_rfq_status_normalizes_multi_word_status(monkeypatch):
    rfq = type("RFQ", (), {"id": 8, "phone": "+256700000000", "status": "new"})()
    db = _FakeDb(rfq)
    monkeypatch.setattr(procurement, "log_audit_event", lambda *_args: None)

    updated = procurement.mark_rfq_status(db, 8, " In Review ")

    assert updated.status == "in_review"
