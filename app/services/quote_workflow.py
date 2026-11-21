"""Shared operations/API quote workflow; approval budget is global and rolling."""
from datetime import datetime, timedelta, UTC
import os
import threading
from fastapi import HTTPException
from sqlalchemy import text
from app.models.db import RFQRequest, RFQLineItem
from app.data_access.procurement import get_rfq_line_items
from app.core.utils import log_audit_event
from app.data_access.funnel import record_funnel_event

LOCKED = {'lpo_issued', 'confirmed', 'fulfilled', 'cancelled', 'lost'}
_approval_lock = threading.Lock()


def now():
    return datetime.now(UTC).replace(tzinfo=None)


def batch_size():
    return max(1, int(os.getenv('LPO_APPROVAL_BATCH_SIZE', '50')))


def get_rfq(db, rfq_id):
    rfq = db.query(RFQRequest).filter(RFQRequest.id == rfq_id).with_for_update().first()
    if rfq is None:
        raise HTTPException(404, 'RFQ not found')
    return rfq


def audit(rfq, event, **data):
    log_audit_event(rfq.phone, event, {'rfq_id': rfq.id, **data})
    record_funnel_event(event, source='ops', actor_id=rfq.phone, rfq_id=rfq.id, data=data)


def recalculate(db, rfq):
    db.flush()
    lines = get_rfq_line_items(db, rfq.id)
    for line in lines:
        line.line_total = line.quantity * line.unit_price if line.unit_price is not None else None
    rfq.order_value = sum(line.line_total for line in lines) if lines and all(line.unit_price and line.unit_price > 0 for line in lines) else None


def edit_line(db, rfq_id, values, line_id=None):
    rfq = get_rfq(db, rfq_id)
    if rfq.status in LOCKED:
        raise HTTPException(409, 'Line items are locked at this status')
    if line_id is None:
        line = RFQLineItem(rfq_id=rfq.id)
        db.add(line)
    else:
        line = db.query(RFQLineItem).filter(RFQLineItem.rfq_id == rfq.id, RFQLineItem.id == line_id).first()
        if line is None:
            raise HTTPException(404, 'Line item not found')
    for key, value in values.items():
        if key not in {'product_name', 'quantity', 'uom', 'unit_price'}:
            continue
        if key in {'quantity', 'unit_price'} and (value is None and key == 'quantity' or value is not None and value <= 0):
            raise HTTPException(422, f'{key} must be positive')
        if key == 'product_name' and not (value or '').strip():
            raise HTTPException(422, 'Product name is required')
        setattr(line, key, value)
    # Changes invalidate a prior quote/approval/review, requiring a fresh decision.
    rfq.status = 'new'
    rfq.quoted_at = None
    rfq.approved_by = None
    rfq.technical_reviewed_at = None
    rfq.technical_reviewed_by = None
    # Keep approved_at as approval-budget history; reapproval consumes another slot
    # via a separate immutable approval event (see approve).
    recalculate(db, rfq)
    db.commit()
    audit(rfq, 'rfq_line_edited', line_id=line.id)
    return rfq


def technical_review(db, rfq_id, reviewed_by):
    rfq = get_rfq(db, rfq_id)
    if rfq.status in LOCKED:
        raise HTTPException(409, 'RFQ is locked')
    rfq.technical_reviewed_at, rfq.technical_reviewed_by = now(), reviewed_by
    db.commit()
    audit(rfq, 'rfq_technical_reviewed', reviewed_by=reviewed_by)
    return rfq


def set_status(db, rfq_id, status, order_value=None):
    rfq = get_rfq(db, rfq_id)
    if status in {'approved', 'lpo_issued'}:
        raise HTTPException(409, 'Use the approval or LPO action')
    if rfq.status in LOCKED and status in {'new', 'quoted'}:
        raise HTTPException(409, 'Cannot reopen a locked RFQ')
    if status == 'quoted':
        if rfq.status not in {'new', 'quoted'}:
            raise HTTPException(409, 'Only a new RFQ can be quoted')
        recalculate(db, rfq)
        if rfq.order_value is None:
            raise HTTPException(409, 'Every line must have a positive unit price before quoting')
        if rfq.equipment_review_required and not rfq.technical_reviewed_at:
            raise HTTPException(409, 'Equipment requires a recorded technical review before quoting')
        rfq.quoted_at = now()
    elif order_value is not None:
        rfq.order_value = order_value
    rfq.status, rfq.status_updated_at = status, now()
    db.commit()
    audit(rfq, 'rfq_status_changed', status=status)
    return rfq


def approve(db, rfq_ids, approved_by):
    from app.models.db import ApprovalEvent
    if not rfq_ids or len(rfq_ids) != len(set(rfq_ids)) or len(rfq_ids) > batch_size():
        raise HTTPException(409, f'Provide 1 to {batch_size()} distinct RFQ ids')
    with _approval_lock:
        # Cross-worker serialization in Postgres, not just the process lock.
        if db.bind.dialect.name == 'postgresql':
            db.execute(text('SELECT pg_advisory_xact_lock(78421031)'))
        cutoff = now() - timedelta(minutes=max(1, int(os.getenv('LPO_APPROVAL_WINDOW_MINUTES', '120'))))
        used = db.query(ApprovalEvent).filter(ApprovalEvent.approved_at > cutoff).count()
        if used + len(rfq_ids) > batch_size():
            raise HTTPException(409, 'Rolling approval limit reached; wait for earlier approvals to leave the window')
        rfqs = [get_rfq(db, i) for i in sorted(rfq_ids)]
        if any(r.status != 'quoted' for r in rfqs):
            raise HTTPException(409, 'Only quoted RFQs can be approved; no changes made')
        for rfq in rfqs:
            rfq.status = 'approved'
            rfq.approved_at = rfq.status_updated_at = now()
            rfq.approved_by = approved_by
            db.add(ApprovalEvent(rfq_id=rfq.id, approved_at=rfq.approved_at, approved_by=approved_by))
        db.commit()
    for rfq in rfqs:
        audit(rfq, 'rfq_approved', approved_by=approved_by)
    return rfqs


def issue_lpo(db, rfq_id, reference):
    rfq = get_rfq(db, rfq_id)
    if rfq.status != 'approved':
        raise HTTPException(409, 'Only approved RFQs can receive an LPO')
    rfq.lpo_reference, rfq.lpo_issued_at = reference, now()
    rfq.status, rfq.status_updated_at = 'lpo_issued', now()
    db.commit()
    audit(rfq, 'rfq_lpo_issued', lpo_reference=reference)
    return rfq
