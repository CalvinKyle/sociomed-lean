from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.db import (
    ClinicalSpecialty,
    Product,
    ProductAttribute,
    ProductClass,
    ProductFamily,
    ProductSpecialty,
    ProductTaxonomyAssignment,
    TaxonomyVersion,
    TaxonomyVersionFamily,
)


APPROVED = "approved"
ACTIVE = "active"
RETIRED = "retired"


class InvalidTaxonomyActivation(ValueError):
    """Raised when a taxonomy version has not completed its approval gates."""


def taxonomy_activation_issues(db: Session, version_id: str) -> list[str]:
    """Return every condition that prevents safe activation of a taxonomy version."""
    version = db.get(TaxonomyVersion, version_id)
    if not version:
        return [f"taxonomy version '{version_id}' does not exist"]

    issues: list[str] = []
    if version.status != APPROVED:
        issues.append(
            f"taxonomy version '{version_id}' must have status 'approved' before activation"
        )

    assignments = (
        db.query(ProductTaxonomyAssignment)
        .filter(ProductTaxonomyAssignment.version_id == version_id)
        .all()
    )
    product_count = db.query(func.count(Product.product_id)).scalar() or 0
    if not assignments:
        issues.append("taxonomy version has no product-family assignments")
    elif len(assignments) != product_count:
        issues.append(
            f"taxonomy version assigns {len(assignments)} of {product_count} catalog products"
        )

    unapproved_assignments = [
        assignment.product_id
        for assignment in assignments
        if assignment.approval_status != APPROVED
    ]
    if unapproved_assignments:
        issues.append(
            f"{len(unapproved_assignments)} product-family assignments are not approved"
        )

    version_family_ids = {
        row.family_id
        for row in db.query(TaxonomyVersionFamily)
        .filter(TaxonomyVersionFamily.version_id == version_id)
        .all()
    }
    assigned_family_ids = {assignment.family_id for assignment in assignments}
    missing_version_families = assigned_family_ids - version_family_ids
    if missing_version_families:
        issues.append(
            f"{len(missing_version_families)} assigned families are missing from the version dictionary"
        )

    families = (
        db.query(ProductFamily)
        .filter(ProductFamily.family_id.in_(version_family_ids))
        .all()
        if version_family_ids
        else []
    )
    if version_family_ids and len(families) != len(version_family_ids):
        issues.append("the version dictionary references missing product families")

    unapproved_families = [
        family.family_id for family in families if family.approval_status != APPROVED
    ]
    if unapproved_families:
        issues.append(f"{len(unapproved_families)} product families are not approved")

    class_ids = {family.class_id for family in families}
    classes = (
        db.query(ProductClass).filter(ProductClass.class_id.in_(class_ids)).all()
        if class_ids
        else []
    )
    if class_ids and len(classes) != len(class_ids):
        issues.append("one or more product families reference a missing product class")
    unapproved_classes = [
        product_class.class_id
        for product_class in classes
        if product_class.approval_status != APPROVED
    ]
    if unapproved_classes:
        issues.append(f"{len(unapproved_classes)} product classes are not approved")

    specialty_rows = (
        db.query(ProductSpecialty)
        .filter(ProductSpecialty.version_id == version_id)
        .all()
    )
    unapproved_specialties = [
        row for row in specialty_rows if row.approval_status != APPROVED
    ]
    if unapproved_specialties:
        issues.append(
            f"{len(unapproved_specialties)} product-specialty mappings are not approved"
        )

    mapped_specialty_codes = {row.specialty_code for row in specialty_rows}
    specialty_definitions = (
        db.query(ClinicalSpecialty)
        .filter(ClinicalSpecialty.specialty_code.in_(mapped_specialty_codes))
        .all()
        if mapped_specialty_codes
        else []
    )
    inactive_specialties = [
        specialty.specialty_code
        for specialty in specialty_definitions
        if not specialty.active
    ]
    if inactive_specialties:
        issues.append(
            f"{len(inactive_specialties)} mapped clinical specialties are inactive"
        )

    duplicate_primary_rows = (
        db.query(ProductSpecialty.product_id)
        .filter(
            ProductSpecialty.version_id == version_id,
            ProductSpecialty.is_primary.is_(True),
        )
        .group_by(ProductSpecialty.product_id)
        .having(func.count(ProductSpecialty.specialty_code) > 1)
        .all()
    )
    if duplicate_primary_rows:
        issues.append(
            f"{len(duplicate_primary_rows)} products have more than one primary specialty"
        )

    attribute_rows = (
        db.query(ProductAttribute)
        .filter(ProductAttribute.version_id == version_id)
        .all()
    )
    unapproved_attributes = [
        row for row in attribute_rows if row.approval_status != APPROVED
    ]
    if unapproved_attributes:
        issues.append(f"{len(unapproved_attributes)} product attributes are not approved")

    return issues


def activate_taxonomy_version(db: Session, version_id: str) -> TaxonomyVersion:
    """Activate one fully approved version and retire the previous active version."""
    issues = taxonomy_activation_issues(db, version_id)
    if issues:
        raise InvalidTaxonomyActivation(
            "Taxonomy activation blocked:\n- " + "\n- ".join(issues)
        )

    version = db.get(TaxonomyVersion, version_id)
    now = datetime.now(UTC).replace(tzinfo=None)
    (
        db.query(TaxonomyVersion)
        .filter(
            TaxonomyVersion.status == ACTIVE,
            TaxonomyVersion.version_id != version_id,
        )
        .update({TaxonomyVersion.status: RETIRED}, synchronize_session=False)
    )
    version.status = ACTIVE
    version.approved_at = version.approved_at or now
    version.activated_at = now
    db.flush()
    return version
