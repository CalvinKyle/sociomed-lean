from datetime import datetime

from sqlalchemy import Boolean, JSON, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import DB_MAX_OVERFLOW, DB_POOL_RECYCLE_SECONDS, DB_POOL_SIZE, DATABASE_URL
from app.core.pfi_status import PFI_STATUS_NONE

engine_kwargs = {"echo": False, "future": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs.update(
        {
            "pool_size": DB_POOL_SIZE,
            "max_overflow": DB_MAX_OVERFLOW,
            "pool_pre_ping": True,
            "pool_recycle": DB_POOL_RECYCLE_SECONDS,
        }
    )

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models (exact match to your Sheets)
class Product(Base):
    __tablename__ = "products"
    product_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String)
    item_type = Column(String, default="generic", nullable=False)
    clinical_speciality = Column(String)
    related_ids = Column(Text)

class Vendor(Base):
    __tablename__ = "vendors"
    vendor_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String)
    email = Column(String)
    region = Column(String)
    commission_rate = Column(Float)
    is_own_inventory = Column(Boolean, default=False, nullable=False)

class Inventory(Base):
    __tablename__ = "inventory"
    inventory_id = Column(String, primary_key=True)
    sku = Column(String)
    product_id = Column(String, ForeignKey("products.product_id"))
    vendor_id = Column(String, ForeignKey("vendors.vendor_id"))
    brand = Column(String)
    uom = Column(String)
    stock_qty = Column(Integer, default=0)
    lead_time_days = Column(Integer)

class Pricing(Base):
    __tablename__ = "pricing"
    pricing_id = Column(String, primary_key=True)
    inventory_id = Column(String, ForeignKey("inventory.inventory_id"))
    min_qty = Column(Integer, nullable=False)
    max_qty = Column(Integer)
    unit_price = Column(Integer, nullable=False)

class Alias(Base):
    __tablename__ = "aliases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alias = Column(String, nullable=False)
    product_id = Column(String, ForeignKey("products.product_id"))


class BuyerLead(Base):
    __tablename__ = "buyer_leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    buyer_name = Column(String, nullable=False)
    organization = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String)
    role = Column(String)
    country = Column(String)
    use_case = Column(Text)
    source = Column(String, default="api", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RFQRequest(Base):
    __tablename__ = "rfq_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    buyer_name = Column(String, nullable=False)
    organization = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String)
    product_id = Column(String)
    product_name = Column(String, nullable=False)
    vendor_id = Column(String)
    vendor_name = Column(String)
    quantity = Column(Integer, nullable=False, default=1)
    delivery_location = Column(String, nullable=False)
    procurement_stage = Column(String, default="market_sourcing", nullable=False)
    required_delivery_date = Column(DateTime, nullable=True)
    notes = Column(Text)
    currency = Column(String, default="UGX", nullable=False)
    source = Column(String, default="api", nullable=False)
    status = Column(String, default="new", nullable=False)
    order_value = Column(Integer, nullable=True)
    pfi_reference = Column(String, nullable=True)
    pfi_status = Column(String, default=PFI_STATUS_NONE, nullable=False)
    pfi_issued_at = Column(DateTime, nullable=True)
    manual_review_required = Column(Boolean, default=False, nullable=False)
    manual_review_reason = Column(String, nullable=True)
    requires_credit = Column(Boolean, default=False, nullable=False)
    technical_review_required = Column(Boolean, default=False, nullable=False)
    special_fulfilment_required = Column(Boolean, default=False, nullable=False)
    payment_confirmation_reference = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status_updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "pfi_status IN ('none', 'pending_approval', 'approved', 'held')",
            name="ck_rfq_requests_pfi_status",
        ),
        CheckConstraint(
            "procurement_stage IN ('budgeting', 'approval_stage', 'ready_to_purchase', 'tender', 'market_sourcing')",
            name="ck_rfq_requests_procurement_stage",
        ),
    )


class RFQLineItem(Base):
    __tablename__ = "rfq_line_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rfq_id = Column(Integer, ForeignKey("rfq_requests.id"), nullable=False)
    inventory_id = Column(String)
    product_id = Column(String)
    product_name = Column(String, nullable=False)
    brand = Column(String)
    sku = Column(String)
    item_type = Column(String, default="generic", nullable=False)
    vendor_id = Column(String)
    vendor_name = Column(String)
    is_own_inventory = Column(Boolean, default=False, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    uom = Column(String)
    unit_price = Column(Integer)
    line_total = Column(Integer)
    currency = Column(String, default="UGX", nullable=False)
    price_source = Column(String)
    stock_verification_status = Column(String, default="unknown", nullable=False)
    quoted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_rfq_line_items_rfq_id", "rfq_id"),)


class FunnelEvent(Base):
    __tablename__ = "funnel_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)
    actor_id = Column(String(64))
    source = Column(String(50), nullable=False)
    rfq_id = Column(Integer, ForeignKey("rfq_requests.id"))
    event_data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_funnel_events_event_type_created_at", "event_type", "created_at"),
        Index("ix_funnel_events_rfq_id", "rfq_id"),
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def load_data():
    """Returns EXACT same format as sheets.py so nothing else breaks"""
    db = SessionLocal()
    try:
        return {
            "products": [{c.name: getattr(p, c.name) for c in Product.__table__.columns} for p in db.query(Product).all()],
            "vendors": [{c.name: getattr(v, c.name) for c in Vendor.__table__.columns} for v in db.query(Vendor).all()],
            "inventory": [{c.name: getattr(i, c.name) for c in Inventory.__table__.columns} for i in db.query(Inventory).all()],
            "pricing": [{c.name: getattr(pr, c.name) for c in Pricing.__table__.columns} for pr in db.query(Pricing).all()],
            "aliases": [{c.name: getattr(a, c.name) for c in Alias.__table__.columns} for a in db.query(Alias).all()],
        }
    finally:
        db.close()
