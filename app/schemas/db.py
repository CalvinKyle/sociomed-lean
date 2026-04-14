import os
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models (exact match to your Sheets)
class Product(Base):
    __tablename__ = "products"
    product_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String)

class Vendor(Base):
    __tablename__ = "vendors"
    vendor_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String)

class Inventory(Base):
    __tablename__ = "inventory"
    inventory_id = Column(String, primary_key=True)
    product_id = Column(String, ForeignKey("products.product_id"))
    vendor_id = Column(String, ForeignKey("vendors.vendor_id"))
    brand = Column(String)
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

def init_db():
    Base.metadata.create_all(bind=engine)

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
