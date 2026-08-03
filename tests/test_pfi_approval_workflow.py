import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.pfi_status import (
    PFI_STATUS_APPROVED,
    PFI_STATUS_HELD,
    PFI_STATUS_NONE,
    PFI_STATUS_PENDING_APPROVAL,
)
from app.core.utils import WhatsAppSendResult
from app.data_access.procurement import create_rfq_record
from app.models.db import Base, RFQRequest
from app.schemas.schemas import RFQCreate
from app.services import procurement


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _create_rfq(db, *, items):
    return create_rfq_record(
        db,
        RFQCreate(
            buyer_name="Dr. Ali",
            organization="Mulago Hospital",
            phone="+256700000001",
            delivery_location="Kampala",
            currency="UGX",
            source="test",
            items=items,
        ),
    )


@pytest.mark.parametrize("vendor_id", ["ZELUS-OWN", "PARTNER-1"])
def test_fully_priced_owned_or_partner_rfq_generates_one_pending_pfi_alert(monkeypatch, vendor_id):
    db = _session()
    sent = []
    generated = []

    async def fake_send(recipient, message):
        sent.append((recipient, message))
        return WhatsAppSendResult(recipient=recipient, success=True, status_code=200)

    monkeypatch.setattr(procurement, "SALES_AGENT_PHONE", "+256700000099")
    monkeypatch.setattr(procurement, "send_whatsapp_message_result", fake_send)
    monkeypatch.setattr(procurement, "generate_pfi_pdf", lambda rfq, items: generated.append((rfq.id, len(items))) or b"%PDF")
    monkeypatch.setattr(procurement, "log_audit_event", lambda *_args, **_kwargs: None)

    try:
        rfq = _create_rfq(
            db,
            items=[
                {
                    "product_name": "Patient Monitor",
                    "vendor_id": vendor_id,
                    "vendor_name": "Must Stay Internal",
                    "quantity": 2,
                    "uom": "unit",
                    "unit_price": 1_500_000,
                }
            ],
        )

        first = asyncio.run(procurement.generate_pfi_for_eligible_rfq(db, rfq))
        second = asyncio.run(procurement.generate_pfi_for_eligible_rfq(db, rfq))

        assert first.generated is True
        assert first.alert_sent is True
        assert first.total == 3_000_000
        assert second.generated is False
        assert rfq.pfi_status == PFI_STATUS_PENDING_APPROVAL
        assert rfq.pfi_reference
        assert generated == [(rfq.id, 1)]
        assert len(sent) == 1
        assert sent[0][0] == "+256700000099"
        assert f"RFQ ID: {rfq.id}" in sent[0][1]
        assert "Total: UGX 3,000,000" in sent[0][1]
        assert f"YES {rfq.id}" in sent[0][1]
        assert "Must Stay Internal" not in sent[0][1]
    finally:
        db.close()


def test_multi_item_rfq_with_one_unpriced_line_skips_pfi_and_alert(monkeypatch):
    db = _session()
    generated = []
    sent = []

    async def fake_send(*args):
        sent.append(args)
        return WhatsAppSendResult(recipient=args[0], success=True)

    monkeypatch.setattr(procurement, "SALES_AGENT_PHONE", "+256700000099")
    monkeypatch.setattr(procurement, "send_whatsapp_message_result", fake_send)
    monkeypatch.setattr(procurement, "generate_pfi_pdf", lambda *_args: generated.append(True))
    monkeypatch.setattr(procurement, "log_audit_event", lambda *_args, **_kwargs: None)

    try:
        rfq = _create_rfq(
            db,
            items=[
                {"product_name": "Gloves", "quantity": 10, "unit_price": 10_000},
                {"product_name": "Special Tubing", "quantity": 2, "unit_price": None},
            ],
        )

        result = asyncio.run(procurement.generate_pfi_for_eligible_rfq(db, rfq))

        assert result.generated is False
        assert result.reason == "unpriced_line_item"
        assert rfq.pfi_status == PFI_STATUS_NONE
        assert rfq.pfi_reference is None
        assert generated == []
        assert sent == []
    finally:
        db.close()


@pytest.mark.parametrize(
    ("command", "expected_status", "buyer_message_count"),
    [("yes 1", PFI_STATUS_APPROVED, 1), ("NO 1", PFI_STATUS_HELD, 0)],
)
def test_operator_yes_or_no_updates_only_pending_pfi(monkeypatch, command, expected_status, buyer_message_count):
    db = _session()
    sent = []

    async def fake_send(recipient, message):
        sent.append((recipient, message))
        return WhatsAppSendResult(recipient=recipient, success=True, status_code=200)

    monkeypatch.setattr(procurement, "send_whatsapp_message_result", fake_send)
    monkeypatch.setattr(procurement, "log_audit_event", lambda *_args, **_kwargs: None)

    try:
        rfq = _create_rfq(
            db,
            items=[{"product_name": "Gloves", "quantity": 10, "unit_price": 10_000}],
        )
        rfq.pfi_status = PFI_STATUS_PENDING_APPROVAL
        db.commit()

        handled = asyncio.run(
            procurement.handle_operator_pfi_command(db, "+256700000099", command)
        )

        db.refresh(rfq)
        assert handled is True
        assert rfq.pfi_status == expected_status
        assert len(sent) == buyer_message_count
        if sent:
            assert sent[0][0] == rfq.phone
            assert sent[0][1] == procurement.PFI_APPROVED_BUYER_MESSAGE
            assert "%PDF" not in sent[0][1]
    finally:
        db.close()


def test_ambiguous_or_non_pending_operator_commands_are_ignored(monkeypatch):
    db = _session()
    monkeypatch.setattr(procurement, "log_audit_event", lambda *_args, **_kwargs: None)

    try:
        rfq = _create_rfq(
            db,
            items=[{"product_name": "Gloves", "quantity": 1, "unit_price": 10_000}],
        )

        assert procurement.parse_operator_pfi_command("YES") is None
        assert procurement.parse_operator_pfi_command("YES 1 please") is None
        assert procurement.parse_operator_pfi_command("MAYBE 1") is None
        assert asyncio.run(procurement.handle_operator_pfi_command(db, "operator", "YES 1")) is False
        assert rfq.pfi_status == PFI_STATUS_NONE
    finally:
        db.close()

