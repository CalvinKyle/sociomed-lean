from datetime import UTC, datetime

from sqlalchemy import Boolean, JSON, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine, text
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
    product_family_id = Column(String)
    equipment_review_required = Column(Boolean, default=False, nullable=False)

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
    price_valid_until = Column(Date)

class Alias(Base):
    __tablename__ = "aliases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alias = Column(String, nullable=False)
    product_id = Column(String, ForeignKey("products.product_id"))


class SyncVersion(Base):
    __tablename__ = "sync_versions"

    version_id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )
    completed_at = Column(DateTime)
    status = Column(String, nullable=True)
    summary = Column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_sync_versions_started_at", "started_at"),)


class CatalogChangeLog(Base):
    __tablename__ = "catalog_change_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(
        Integer,
        ForeignKey("sync_versions.version_id"),
        nullable=False,
    )
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    change_type = Column(String, nullable=False)
    before_state = Column(JSON)
    after_state = Column(JSON)
    reason = Column(String)
    changed_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_catalog_change_log_version_id", "version_id"),
        Index(
            "ix_catalog_change_log_entity_id_changed_at",
            "entity_id",
            "changed_at",
        ),
    )


class TaxonomyVersion(Base):
    __tablename__ = "taxonomy_versions"

    version_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft")
    effective_date = Column(Date)
    approved_at = Column(DateTime)
    activated_at = Column(DateTime)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_taxonomy_versions_status", "status"),
        Index(
            "uq_taxonomy_versions_one_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )


class ProductClass(Base):
    __tablename__ = "product_classes"

    class_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    parent_class_id = Column(String, ForeignKey("product_classes.class_id"))
    approval_status = Column(String, nullable=False, default="pending")


class ProductFamily(Base):
    __tablename__ = "product_families"

    family_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    class_id = Column(String, ForeignKey("product_classes.class_id"), nullable=False)
    emdn_code = Column(String)
    gmdn_code = Column(String)
    approval_status = Column(String, nullable=False, default="pending")

    __table_args__ = (Index("ix_product_families_class_id", "class_id"),)


class TaxonomyVersionFamily(Base):
    __tablename__ = "taxonomy_version_families"

    version_id = Column(String, ForeignKey("taxonomy_versions.version_id"), primary_key=True)
    family_id = Column(String, ForeignKey("product_families.family_id"), primary_key=True)


class ProductTaxonomyAssignment(Base):
    __tablename__ = "product_taxonomy_assignments"

    version_id = Column(String, ForeignKey("taxonomy_versions.version_id"), primary_key=True)
    product_id = Column(String, ForeignKey("products.product_id"), primary_key=True)
    family_id = Column(String, ForeignKey("product_families.family_id"), nullable=False)
    approval_status = Column(String, nullable=False, default="pending")

    __table_args__ = (Index("ix_product_taxonomy_assignments_family_id", "family_id"),)


class ClinicalSpecialty(Base):
    __tablename__ = "clinical_specialties"

    specialty_code = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    active = Column(Boolean, default=True, nullable=False)


class ProductSpecialty(Base):
    __tablename__ = "product_specialties"

    version_id = Column(String, ForeignKey("taxonomy_versions.version_id"), primary_key=True)
    product_id = Column(String, ForeignKey("products.product_id"), primary_key=True)
    specialty_code = Column(String, ForeignKey("clinical_specialties.specialty_code"), primary_key=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    approval_status = Column(String, nullable=False, default="pending")

    __table_args__ = (
        Index("ix_product_specialties_product_version", "product_id", "version_id"),
    )


class ProductAttribute(Base):
    __tablename__ = "product_attributes"

    version_id = Column(String, ForeignKey("taxonomy_versions.version_id"), primary_key=True)
    product_id = Column(String, ForeignKey("products.product_id"), primary_key=True)
    attribute_code = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    unit = Column(String)
    approval_status = Column(String, nullable=False, default="pending")

    __table_args__ = (Index("ix_product_attributes_product_version", "product_id", "version_id"),)


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


class BuyerProfile(Base):
    __tablename__ = "buyer_profiles"

    phone = Column(String, primary_key=True)
    contact_name = Column(String, nullable=False)
    organization = Column(String, nullable=False)
    role = Column(String)
    country = Column(String)
    delivery_location = Column(String)
    preferred_currency = Column(String, default="UGX", nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


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
    procurement_stage = Column(String, default="formal_purchase", nullable=False)
    formal_quote = Column(Boolean, default=True, nullable=False)
    required_by = Column(String)
    payment_preference = Column(String)
    destination_country = Column(String)
    equipment_review_required = Column(Boolean, default=False, nullable=False)
    manual_review_reason = Column(String)
    order_value = Column(Integer, nullable=True)
    pfi_reference = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status_updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RFQLineItem(Base):
    __tablename__ = "rfq_line_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rfq_id = Column(Integer, ForeignKey("rfq_requests.id"), nullable=False)
    product_id = Column(String)
    product_name = Column(String, nullable=False)
    vendor_id = Column(String)
    vendor_name = Column(String)
    quantity = Column(Integer, nullable=False, default=1)
    uom = Column(String)
    unit_price = Column(Integer)
    line_total = Column(Integer)
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
    """Load catalog data, overlaying only the currently active taxonomy version."""
    db = SessionLocal()
    try:
        product_rows = [
            {column.name: getattr(product, column.name) for column in Product.__table__.columns}
            for product in db.query(Product).all()
        ]
        active_version = (
            db.query(TaxonomyVersion)
            .filter(TaxonomyVersion.status == "active")
            .order_by(
                TaxonomyVersion.activated_at.desc(),
                TaxonomyVersion.created_at.desc(),
            )
            .first()
        )

        family_rows = []
        specialty_rows = []
        attribute_rows = []
        class_rows = []
        active_version_payload = None
        if active_version:
            active_version_payload = {
                column.name: getattr(active_version, column.name)
                for column in TaxonomyVersion.__table__.columns
            }
            assignments = (
                db.query(ProductTaxonomyAssignment)
                .filter(ProductTaxonomyAssignment.version_id == active_version.version_id)
                .all()
            )
            assignment_by_product = {
                assignment.product_id: assignment for assignment in assignments
            }
            version_family_ids = {
                row.family_id
                for row in db.query(TaxonomyVersionFamily)
                .filter(TaxonomyVersionFamily.version_id == active_version.version_id)
                .all()
            }
            families = (
                db.query(ProductFamily)
                .filter(ProductFamily.family_id.in_(version_family_ids))
                .all()
                if version_family_ids
                else []
            )
            families_by_id = {family.family_id: family for family in families}
            family_rows = [
                {column.name: getattr(family, column.name) for column in ProductFamily.__table__.columns}
                for family in families
            ]
            class_ids = {family.class_id for family in families}
            classes = (
                db.query(ProductClass).filter(ProductClass.class_id.in_(class_ids)).all()
                if class_ids
                else []
            )
            class_rows = [
                {
                    column.name: getattr(product_class, column.name)
                    for column in ProductClass.__table__.columns
                }
                for product_class in classes
            ]

            specialties = (
                db.query(ProductSpecialty)
                .filter(ProductSpecialty.version_id == active_version.version_id)
                .order_by(
                    ProductSpecialty.product_id,
                    ProductSpecialty.is_primary.desc(),
                    ProductSpecialty.specialty_code,
                )
                .all()
            )
            specialties_by_product: dict[str, list[str]] = {}
            for specialty in specialties:
                specialties_by_product.setdefault(specialty.product_id, []).append(
                    specialty.specialty_code
                )
            specialty_rows = [
                {
                    column.name: getattr(specialty, column.name)
                    for column in ProductSpecialty.__table__.columns
                }
                for specialty in specialties
            ]

            attributes = (
                db.query(ProductAttribute)
                .filter(ProductAttribute.version_id == active_version.version_id)
                .order_by(ProductAttribute.product_id, ProductAttribute.attribute_code)
                .all()
            )
            attribute_rows = [
                {
                    column.name: getattr(attribute, column.name)
                    for column in ProductAttribute.__table__.columns
                }
                for attribute in attributes
            ]

            for product in product_rows:
                assignment = assignment_by_product.get(product["product_id"])
                if assignment:
                    family = families_by_id.get(assignment.family_id)
                    product["product_family_id"] = assignment.family_id
                    product["product_family_name"] = family.name if family else None
                mapped_specialties = specialties_by_product.get(product["product_id"])
                if mapped_specialties:
                    product["clinical_speciality"] = " | ".join(mapped_specialties)

        return {
            "products": product_rows,
            "vendors": [{c.name: getattr(v, c.name) for c in Vendor.__table__.columns} for v in db.query(Vendor).all()],
            "inventory": [{c.name: getattr(i, c.name) for c in Inventory.__table__.columns} for i in db.query(Inventory).all()],
            "pricing": [{c.name: getattr(pr, c.name) for c in Pricing.__table__.columns} for pr in db.query(Pricing).all()],
            "aliases": [{c.name: getattr(a, c.name) for c in Alias.__table__.columns} for a in db.query(Alias).all()],
            "taxonomy_version": active_version_payload,
            "product_classes": class_rows,
            "product_families": family_rows,
            "product_specialties": specialty_rows,
            "product_attributes": attribute_rows,
        }
    finally:
        db.close()
