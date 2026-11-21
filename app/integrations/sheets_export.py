"""Best-effort, serialized operations snapshots. Postgres remains authoritative."""
import asyncio
import logging
import os
import threading
from datetime import date, datetime

from app.models.db import SessionLocal, RFQRequest, RFQLineItem, BuyerLead

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_tasks = set()


def log_export_configuration():
    if not os.getenv('OPS_SHEET_NAME'):
        logger.info('Operations sheet export disabled: OPS_SHEET_NAME unset')


def _rows(db, model):
    # Supplier information is deliberately absent, even from the operations view.
    columns = [c.name for c in model.__table__.columns if not c.name.startswith('vendor_')]
    rows = [columns]
    for record in db.query(model).order_by(model.id).all():
        values = [getattr(record, c) for c in columns]
        rows.append([v.isoformat() if isinstance(v, (date, datetime)) else '' if v is None else v for v in values])
    return rows


def export_ops(client=None):
    name = os.getenv('OPS_SHEET_NAME')
    if not name:
        return {'status': 'disabled'}
    from app.core.config import SHEET_NAME
    if name == SHEET_NAME:
        logger.error('Operations export rejected: destination is the catalogue')
        return {'status': 'failed'}
    with _lock:
        try:
            if client is None:
                from app.integrations.google_credentials import sheets_client
                client = sheets_client()
            sheet = client.open(name)
            with SessionLocal() as db:
                snapshots = [(tab, _rows(db, model)) for tab, model in
                             [('rfqs', RFQRequest), ('rfq_lines', RFQLineItem), ('leads', BuyerLead)]]
            from gspread.exceptions import WorksheetNotFound
            for tab, rows in snapshots:
                try:
                    worksheet = sheet.worksheet(tab)
                except WorksheetNotFound:
                    worksheet = sheet.add_worksheet(title=tab, rows=max(100, len(rows)), cols=len(rows[0]))
                worksheet.clear()
                worksheet.update(values=rows, range_name='A1', value_input_option='RAW')
            return {'status': 'completed'}
        except Exception:
            # Provider errors can contain credentials or buyer values; do not log them.
            logger.warning('Operations export failed; database records retained')
            return {'status': 'failed'}


def schedule_ops_export():
    if not os.getenv('OPS_SHEET_NAME'):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Sync service callers still receive a nonblocking best-effort export.
        threading.Thread(target=export_ops, daemon=True).start()
        return
    task = loop.create_task(asyncio.to_thread(export_ops))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
