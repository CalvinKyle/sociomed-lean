import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db import (
    Base,
    ClinicalSpecialty,
    Product,
    ProductAttribute,
    ProductClass,
    ProductFamily,
    ProductSpecialty,
    ProductTaxonomyAssignment,
    TaxonomyVersion,
    TaxonomyVersionFamily,
    load_data,
)
from app.services.taxonomy import (
    InvalidTaxonomyActivation,
    activate_taxonomy_version,
    taxonomy_activation_issues,
)
from sync_sheets_to_db import _sync_taxonomy


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _add_complete_version(db, version_id: str = "2026-09"):
    db.add(Product(product_id="p1", name="Foley catheter", category="Consumables"))
    db.add(
        TaxonomyVersion(
            version_id=version_id,
            name="September taxonomy",
            status="approved",
        )
    )
    db.add(
        ProductClass(
            class_id="CLASS-URINARY",
            name="Urinary drainage",
            approval_status="approved",
        )
    )
    db.add(
        ProductFamily(
            family_id="FAM-FOLEY",
            name="Foley urinary catheters",
            class_id="CLASS-URINARY",
            approval_status="approved",
        )
    )
    db.add(
        TaxonomyVersionFamily(
            version_id=version_id,
            family_id="FAM-FOLEY",
        )
    )
    db.add(
        ProductTaxonomyAssignment(
            version_id=version_id,
            product_id="p1",
            family_id="FAM-FOLEY",
            approval_status="approved",
        )
    )
    db.add(
        ClinicalSpecialty(
            specialty_code="UROLOGY",
            name="Urology",
        )
    )
    db.add(
        ProductSpecialty(
            version_id=version_id,
            product_id="p1",
            specialty_code="UROLOGY",
            is_primary=True,
            approval_status="approved",
        )
    )
    db.add(
        ProductAttribute(
            version_id=version_id,
            product_id="p1",
            attribute_code="size",
            value="16",
            unit="CH",
            approval_status="approved",
        )
    )
    db.commit()


def test_activation_is_blocked_until_family_dictionary_is_approved(db):
    _add_complete_version(db)
    family = db.get(ProductFamily, "FAM-FOLEY")
    family.approval_status = "pending"
    db.commit()

    issues = taxonomy_activation_issues(db, "2026-09")

    assert "1 product families are not approved" in issues
    with pytest.raises(InvalidTaxonomyActivation, match="activation blocked"):
        activate_taxonomy_version(db, "2026-09")


def test_activation_retires_previous_version_and_activates_approved_version(db):
    db.add(TaxonomyVersion(version_id="old", name="Old taxonomy", status="active"))
    db.commit()
    _add_complete_version(db)

    activated = activate_taxonomy_version(db, "2026-09")
    db.commit()

    assert activated.status == "active"
    assert activated.activated_at is not None
    assert db.get(TaxonomyVersion, "old").status == "retired"


def test_active_taxonomy_overlays_family_specialties_and_attributes(db, monkeypatch):
    _add_complete_version(db)
    activate_taxonomy_version(db, "2026-09")
    db.commit()
    monkeypatch.setattr("app.models.db.SessionLocal", sessionmaker(bind=db.get_bind()))

    data = load_data()

    assert data["taxonomy_version"]["version_id"] == "2026-09"
    assert data["products"][0]["product_family_id"] == "FAM-FOLEY"
    assert data["products"][0]["product_family_name"] == "Foley urinary catheters"
    assert data["products"][0]["clinical_speciality"] == "UROLOGY"
    assert data["product_attributes"][0]["value"] == "16"
    assert data["product_attributes"][0]["unit"] == "CH"


def test_normalized_taxonomy_tabs_sync_and_activate_as_one_version(db):
    db.add(Product(product_id="p1", name="Foley catheter", category="Consumables"))
    db.commit()
    taxonomy_data = {
        "taxonomy_versions": [
            {"version_id": "2026-09", "name": "September taxonomy", "status": "active"}
        ],
        "product_classes": [
            {
                "class_id": "CLASS-URINARY",
                "name": "Urinary drainage",
                "approval_status": "approved",
            }
        ],
        "product_families": [
            {
                "family_id": "FAM-FOLEY",
                "name": "Foley urinary catheters",
                "class_id": "CLASS-URINARY",
                "approval_status": "approved",
            }
        ],
        "taxonomy_version_families": [
            {"version_id": "2026-09", "family_id": "FAM-FOLEY"}
        ],
        "product_taxonomy_assignments": [
            {
                "version_id": "2026-09",
                "product_id": "p1",
                "family_id": "FAM-FOLEY",
                "approval_status": "approved",
            }
        ],
        "clinical_specialties": [
            {"specialty_code": "UROLOGY", "name": "Urology", "active": True}
        ],
        "product_specialties": [
            {
                "version_id": "2026-09",
                "product_id": "p1",
                "specialty_code": "UROLOGY",
                "is_primary": True,
                "approval_status": "approved",
            }
        ],
        "product_attributes": [
            {
                "version_id": "2026-09",
                "product_id": "p1",
                "attribute_code": "size",
                "value": "16",
                "unit": "CH",
                "approval_status": "approved",
            }
        ],
    }

    _sync_taxonomy(db, taxonomy_data)
    db.commit()

    assert db.get(TaxonomyVersion, "2026-09").status == "active"
    assert db.get(ProductFamily, "FAM-FOLEY").emdn_code is None
    assert db.get(ProductAttribute, ("2026-09", "p1", "size")).value == "16"
