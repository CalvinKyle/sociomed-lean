from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_access.procurement import create_rfq_record, get_rfq_line_items
from app.models.db import Base
from app.schemas.schemas import RFQCreate


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _base_payload(**overrides):
    payload = {
        "buyer_name": "Dr. Ali",
        "organization": "Key Care Mobile Medical Services",
        "phone": "+256700000000",
        "delivery_location": "Kampala",
        "currency": "UGX",
        "source": "test",
    }
    payload.update(overrides)
    return payload


def test_legacy_rfq_shape_creates_one_line_item():
    db = _session()
    try:
        rfq = create_rfq_record(
            db,
            RFQCreate(
                **_base_payload(
                    product_id="P-1",
                    product_name="Patient Monitor",
                    quantity=2,
                    vendor_id="V-1",
                    vendor_name="Zelus Life",
                )
            ),
        )

        items = get_rfq_line_items(db, rfq.id)

        assert rfq.product_name == "Patient Monitor"
        assert len(items) == 1
        assert items[0].product_id == "P-1"
        assert items[0].quantity == 2
        assert items[0].line_total is None
    finally:
        db.close()


def test_multi_item_rfq_creates_structured_rows_and_summary_header():
    db = _session()
    try:
        rfq = create_rfq_record(
            db,
            RFQCreate(
                **_base_payload(
                    items=[
                        {
                            "product_id": "P-1",
                            "product_name": "Patient Monitor",
                            "quantity": 2,
                            "unit_price": 1_500_000,
                        },
                        {"product_name": "ECG Machine", "quantity": 1, "unit_price": 8_000_000},
                        {"product_name": "Ultrasound Gel", "quantity": 10},
                    ]
                )
            ),
        )

        items = get_rfq_line_items(db, rfq.id)

        assert rfq.product_name == "Patient Monitor +2 more"
        assert len(items) == 3
        assert items[0].line_total == 3_000_000
        assert items[2].line_total is None
    finally:
        db.close()
