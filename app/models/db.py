from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import DB_MAX_OVERFLOW, DB_POOL_RECYCLE_SECONDS, DB_POOL_SIZE, DATABASE_URL

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
    clinical_speciality = Column(String)
    related_ids = Column(Text)

class Vendor(Base):
    __tablename__ = "vendors"
    vendor_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String)
    email = Column(String)
    region = Column(String)

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
    notes = Column(Text)
    currency = Column(String, default="UGX", nullable=False)
    source = Column(String, default="api", nullable=False)
    status = Column(String, default="new", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status_updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


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
