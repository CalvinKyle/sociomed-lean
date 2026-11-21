import re
from fastapi.testclient import TestClient
from app.main import app
from app.models.db import get_db
from app.core import config
from tests.test_quote_workflow import make
from tests.test_rfq_line_items import _session
from app.services import quote_workflow as w


def test_console_auth_csrf_escape_edit_and_approve(monkeypatch):
    monkeypatch.setattr(config, 'API_KEY', 'test-key')
    monkeypatch.setattr(config, 'PUBLIC_BASE_URL', '')
    monkeypatch.setattr(w, 'audit', lambda *a, **kw: None)
    db = _session()
    # Use the same in-memory connection across the ASGI test thread.
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import Session
    from app.models.db import Base
    db.close()
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    r = make(db)
    r.buyer_name = '<script>alert(1)</script>'
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    try:
        assert client.get('/ops').status_code == 401
        client.auth = ('owner', 'test-key')
        page = client.get(f'/ops/{r.id}')
        assert '&lt;script&gt;' in page.text and '<script>' not in page.text
        token = re.search('name="csrf" value="([^"]+)"', page.text)[1]
        assert client.post(f'/ops/{r.id}/approve', data={'csrf': token, 'approved_by': 'Owner'}).status_code == 403
        headers = {'Origin': 'http://testserver'}
        assert client.post(f'/ops/{r.id}/approve', data={'csrf': 'bad', 'approved_by': 'Owner'}, headers=headers).status_code == 403
        from app.data_access.procurement import get_rfq_line_items
        line = get_rfq_line_items(db, r.id)[0]
        for action, values in [(f'line/{line.id}', {'quantity': '3', 'unit_price': '250', 'uom': 'piece'}), ('status', {'status': 'quoted'}), ('approve', {'approved_by': 'Owner'})]:
            result = client.post(f'/ops/{r.id}/{action}', data={'csrf': token, **values}, headers=headers, follow_redirects=False)
            assert result.status_code == 303, result.text
        assert r.order_value == 750 and r.status == 'approved'
        monkeypatch.setattr(config, 'API_KEY', None)
        assert client.get('/ops').status_code == 503
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()
