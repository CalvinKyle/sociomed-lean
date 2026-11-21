from app.integrations import sheets_export as exports
from tests.test_rfq_line_items import _session


def test_export_disabled(monkeypatch):
    monkeypatch.delenv('OPS_SHEET_NAME', raising=False)
    assert exports.export_ops(object()) == {'status': 'disabled'}


def test_export_tabs_and_failure(monkeypatch):
    monkeypatch.setenv('OPS_SHEET_NAME', 'pilot-ops-test')
    monkeypatch.setattr(exports, 'SessionLocal', _session)
    written = {}
    class Worksheet:
        def __init__(self, name): self.name = name
        def clear(self): pass
        def update(self, **kw):
            assert kw['value_input_option'] == 'RAW'
            written[self.name] = kw['values']
    class Client:
        def open(self, name): return self
        def worksheet(self, name): return Worksheet(name)
    assert exports.export_ops(Client())['status'] == 'completed'
    assert set(written) == {'rfqs', 'rfq_lines', 'leads'}
    assert 'quantity' in written['rfq_lines'][0]
    assert exports.export_ops(object())['status'] == 'failed'


def test_catalogue_destination_rejected(monkeypatch):
    from app.core.config import SHEET_NAME
    monkeypatch.setenv('OPS_SHEET_NAME', SHEET_NAME)
    assert exports.export_ops(object())['status'] == 'failed'
