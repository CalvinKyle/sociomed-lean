from datetime import datetime, timedelta
import pytest
from fastapi import HTTPException
from app.services import quote_workflow as w
from app.data_access.procurement import create_rfq_record, get_rfq_line_items
from app.schemas.schemas import RFQCreate
from tests.test_rfq_line_items import _session, _base_payload

@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(w, 'audit', lambda *a, **kw: None)
    with _session() as session:
        yield session

def make(db, **kw):
    return create_rfq_record(db, RFQCreate(**_base_payload(items=[dict(product_name='Monitor', quantity=2, unit_price=100)], **kw)))

def test_quote_review_approval_lpo_and_edit_lock(db):
    r = make(db, equipment_review_required=True)
    with pytest.raises(HTTPException, match='technical review'):
        w.set_status(db, r.id, 'quoted')
    w.technical_review(db, r.id, 'Owner')
    w.set_status(db, r.id, 'quoted')
    assert r.order_value == 200 and r.quoted_at
    w.approve(db, [r.id], 'Owner')
    assert r.status == 'approved' and r.approved_at
    w.issue_lpo(db, r.id, 'LPO-1')
    assert r.lpo_reference == 'LPO-1'
    for status in w.LOCKED:
        r.status = status
        with pytest.raises(HTTPException, match='locked'):
            w.edit_line(db, r.id, {'quantity': 5})


def test_line_maths_unpriced_and_invalidation(db):
    r = make(db)
    line = get_rfq_line_items(db, r.id)[0]
    w.edit_line(db, r.id, {'quantity': 3, 'unit_price': 50}, line.id)
    assert line.line_total == 150 and r.order_value == 150
    w.edit_line(db, r.id, {'product_name': 'Gloves', 'quantity': 10, 'unit_price': None})
    assert r.order_value is None
    with pytest.raises(HTTPException, match='Every line'):
        w.set_status(db, r.id, 'quoted')
    with pytest.raises(HTTPException): w.approve(db, [r.id], 'Owner')
    with pytest.raises(HTTPException): w.issue_lpo(db, r.id, 'LPO')
    for status in ['approved', 'lpo_issued']:
        with pytest.raises(HTTPException): w.set_status(db, r.id, status)


def test_rolling_cap_counts_single_batch_and_reapprovals(db, monkeypatch):
    clock = datetime(2026, 1, 1, 12)
    monkeypatch.setattr(w, 'now', lambda: clock)
    monkeypatch.setenv('LPO_APPROVAL_BATCH_SIZE', '2')
    rs = [make(db) for _ in range(3)]
    for r in rs: w.set_status(db, r.id, 'quoted')
    with pytest.raises(HTTPException): w.approve(db, [r.id for r in rs], 'Owner')
    with pytest.raises(HTTPException): w.approve(db, [rs[0].id] * 2, 'Owner')
    w.approve(db, [rs[0].id], 'Owner')
    w.approve(db, [rs[1].id], 'Owner')
    with pytest.raises(HTTPException, match='Rolling'): w.approve(db, [rs[2].id], 'Owner')
    clock += timedelta(minutes=120)
    w.approve(db, [rs[2].id], 'Owner')
    assert rs[2].status == 'approved'


def test_migrations_blank_upgrade_and_downgrade(tmp_path, monkeypatch):
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine, inspect
    from app.core import config
    url = 'sqlite:///' + str(tmp_path / 'migration.db')
    monkeypatch.setattr(config, 'DATABASE_URL', url)
    cfg = Config('alembic.ini')
    command.upgrade(cfg, 'head')
    engine = create_engine(url)
    assert 'technical_reviewed_at' in {c['name'] for c in inspect(engine).get_columns('rfq_requests')}
    command.downgrade(cfg, '-1')
    assert 'technical_reviewed_at' not in {c['name'] for c in inspect(engine).get_columns('rfq_requests')}
    command.upgrade(cfg, 'head')
    engine.dispose()
