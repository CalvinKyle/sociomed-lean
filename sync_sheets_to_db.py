"""
sync_sheets_to_db.py  –  SocioMED Lean
Upsert-safe sync from Google Sheets → PostgreSQL.

The sync validates rows in dependency order, records rejected rows, writes only
created or materially changed records, and keeps before/after history under one
transactional sync version. Redis is cleared after each successful committed run.
"""

import sys
import subprocess
import logging
import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Callable

sys.path.insert(0, ".")

from app.core.sheet_sync import (
    prepare_sheet_data,
    split_multi_value_cell,
    summarize_vendor_phone_issues,
    validate_catalog_snapshot,
)
from app.models.db import (
    SessionLocal,
    Product,
    Vendor,
    Inventory,
    Pricing,
    Alias,
    TaxonomyVersion,
    ProductClass,
    ProductFamily,
    TaxonomyVersionFamily,
    ProductTaxonomyAssignment,
    ClinicalSpecialty,
    ProductSpecialty,
    ProductAttribute,
    SyncVersion,
    CatalogChangeLog,
)
from app.services.taxonomy import activate_taxonomy_version

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ─── helpers ──────────────────────────────────────────────────────────────────

def _coerce_int(value, default=0):
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    return int(float(str(value).replace(",", "").strip()))


def _coerce_float(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace(",", "").strip())


def _coerce_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def _coerce_bool(value, default=False):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "y"}


def _normalize_status(value, default: str) -> str:
    normalized = str(value or default).strip().casefold()
    return normalized or default


def _coerce_text(value):
    return str(value).strip() if value not in (None, "") else None


@dataclass(frozen=True)
class FieldSpec:
    sheet_key: str
    coerce: Callable[[object], object]
    default: object = None
    preserve_blank: bool = False


@dataclass(frozen=True)
class SyncRunResult:
    version_id: int | None
    summary: dict[str, dict[str, int]]


SUMMARY_FIELDS = ("unchanged", "changed", "created", "skipped_invalid")
CORE_TABS = ("products", "vendors", "inventory", "pricing", "aliases")
TAB_ENTITY_TYPES = {
    "products": "product",
    "vendors": "vendor",
    "inventory": "inventory",
    "pricing": "pricing",
    "aliases": "alias",
    "taxonomy_versions": "taxonomy_version",
    "product_classes": "product_class",
    "product_families": "product_family",
    "taxonomy_version_families": "taxonomy_version_family",
    "product_taxonomy_assignments": "product_taxonomy_assignment",
    "clinical_specialties": "clinical_specialty",
    "product_specialties": "product_specialty",
    "product_attributes": "product_attribute",
}


PRODUCT_FIELDS = {
    "name": FieldSpec("name", _coerce_text),
    "category": FieldSpec("category", _coerce_text),
    "clinical_speciality": FieldSpec("clinical_speciality", _coerce_text),
    "related_ids": FieldSpec("related_ids", _coerce_text),
    "product_family_id": FieldSpec("product_family_id", _coerce_text),
    "equipment_review_required": FieldSpec(
        "equipment_review_required",
        lambda value: _coerce_bool(value, default=False),
        default=False,
        preserve_blank=True,
    ),
}
VENDOR_FIELDS = {
    "name": FieldSpec("name", _coerce_text),
    "phone": FieldSpec("phone", _coerce_text),
    "email": FieldSpec("email", _coerce_text),
    "region": FieldSpec("region", _coerce_text),
    "commission_rate": FieldSpec(
        "commission_rate",
        lambda value: _coerce_float(value, default=None),
        preserve_blank=True,
    ),
    "is_own_inventory": FieldSpec(
        "is_own_inventory",
        lambda value: _coerce_bool(value, default=False),
        default=False,
        preserve_blank=True,
    ),
}
INVENTORY_FIELDS = {
    "sku": FieldSpec("sku", _coerce_text),
    "product_id": FieldSpec("product_id", _coerce_text),
    "vendor_id": FieldSpec("vendor_id", _coerce_text),
    "brand": FieldSpec("brand", _coerce_text),
    "uom": FieldSpec("uom", _coerce_text),
    # Inventory.stock_qty has a model default of zero, including on blank inserts.
    "stock_qty": FieldSpec(
        "stock_qty", lambda value: _coerce_int(value, default=0), default=0
    ),
    "lead_time_days": FieldSpec(
        "lead_time_days", lambda value: _coerce_int(value, default=None)
    ),
}
PRICING_FIELDS = {
    "inventory_id": FieldSpec("inventory_id", _coerce_text),
    "min_qty": FieldSpec("min_qty", lambda value: _coerce_int(value, default=0), default=0),
    "max_qty": FieldSpec("max_qty", lambda value: _coerce_int(value, default=None)),
    "unit_price": FieldSpec(
        "unit_price", lambda value: _coerce_int(value, default=0), default=0
    ),
    "price_valid_until": FieldSpec("price_valid_until", _coerce_date),
}
TAXONOMY_VERSION_FIELDS = {
    "name": FieldSpec("name", _coerce_text),
    "status": FieldSpec("status", lambda value: _normalize_status(value, "draft")),
    "effective_date": FieldSpec("effective_date", _coerce_date),
}
PRODUCT_CLASS_FIELDS = {
    "name": FieldSpec("name", _coerce_text),
    "parent_class_id": FieldSpec("parent_class_id", _coerce_text),
    "approval_status": FieldSpec(
        "approval_status", lambda value: _normalize_status(value, "pending")
    ),
}
PRODUCT_FAMILY_FIELDS = {
    "name": FieldSpec("name", _coerce_text),
    "class_id": FieldSpec("class_id", _coerce_text),
    "emdn_code": FieldSpec("emdn_code", _coerce_text),
    "gmdn_code": FieldSpec("gmdn_code", _coerce_text),
    "approval_status": FieldSpec(
        "approval_status", lambda value: _normalize_status(value, "pending")
    ),
}
CLINICAL_SPECIALTY_FIELDS = {
    "name": FieldSpec("name", _coerce_text),
    "active": FieldSpec(
        "active", lambda value: _coerce_bool(value, default=True), default=True
    ),
}
PRODUCT_TAXONOMY_ASSIGNMENT_FIELDS = {
    "family_id": FieldSpec("family_id", _coerce_text),
    "approval_status": FieldSpec(
        "approval_status", lambda value: _normalize_status(value, "pending")
    ),
}
PRODUCT_SPECIALTY_FIELDS = {
    "is_primary": FieldSpec(
        "is_primary", lambda value: _coerce_bool(value, default=False), default=False
    ),
    "approval_status": FieldSpec(
        "approval_status", lambda value: _normalize_status(value, "pending")
    ),
}
PRODUCT_ATTRIBUTE_FIELDS = {
    "value": FieldSpec("value", _coerce_text),
    "unit": FieldSpec("unit", _coerce_text),
    "approval_status": FieldSpec(
        "approval_status", lambda value: _normalize_status(value, "pending")
    ),
}


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _json_state(state: dict[str, object] | None) -> dict[str, object] | None:
    if state is None:
        return None
    return {key: _json_value(value) for key, value in state.items()}


def _blank_summary() -> dict[str, int]:
    return {field: 0 for field in SUMMARY_FIELDS}


def _record_change(
    db,
    *,
    version_id: int,
    entity_type: str,
    entity_id: str,
    change_type: str,
    before_state: dict[str, object] | None,
    after_state: dict[str, object] | None,
    reason: str | None = None,
) -> None:
    db.add(
        CatalogChangeLog(
            version_id=version_id,
            entity_type=entity_type,
            entity_id=entity_id,
            change_type=change_type,
            before_state=_json_state(before_state),
            after_state=_json_state(after_state),
            reason=reason,
        )
    )


def _model_key(row: dict, key_fields: str | tuple[str, ...]):
    if isinstance(key_fields, str):
        return str(row.get(key_fields, "")).strip()
    return tuple(str(row.get(field, "")).strip() for field in key_fields)


def _entity_id_from_key(key) -> str:
    if isinstance(key, tuple):
        return ":".join(key)
    return str(key)


def _desired_state(obj, row: dict, fields: dict[str, FieldSpec]) -> dict[str, object]:
    desired: dict[str, object] = {}
    for model_attr, spec in fields.items():
        raw = row.get(spec.sheet_key)
        if raw in (None, "") and spec.preserve_blank:
            current = getattr(obj, model_attr, spec.default) if obj is not None else spec.default
            desired[model_attr] = spec.coerce(current)
        else:
            desired[model_attr] = spec.coerce(raw)
    return desired


def _current_state(obj, fields: dict[str, FieldSpec]) -> dict[str, object]:
    return {
        model_attr: spec.coerce(getattr(obj, model_attr, spec.default))
        for model_attr, spec in fields.items()
    }


def _sync_model_rows(
    db,
    *,
    version_id: int,
    summary: dict[str, dict[str, int]],
    tab_name: str,
    entity_type: str,
    model_cls,
    key_fields: str | tuple[str, ...],
    rows: list[dict],
    fields: dict[str, FieldSpec],
) -> None:
    incoming_keys = [_model_key(row, key_fields) for row in rows]
    if isinstance(key_fields, str):
        existing = (
            db.query(model_cls)
            .filter(getattr(model_cls, key_fields).in_(incoming_keys))
            .all()
            if incoming_keys
            else []
        )
        existing_by_key = {
            str(getattr(obj, key_fields)): obj for obj in existing
        }
    else:
        # Optional taxonomy link tables are small. One table read avoids a
        # separate network round trip for every composite key.
        existing = db.query(model_cls).all() if incoming_keys else []
        existing_by_key = {
            tuple(str(getattr(obj, field)) for field in key_fields): obj
            for obj in existing
        }

    for row in rows:
        key = _model_key(row, key_fields)
        obj = existing_by_key.get(key)
        before = _current_state(obj, fields) if obj is not None else None
        after = _desired_state(obj, row, fields)
        entity_id = _entity_id_from_key(key)

        if obj is None:
            key_values = (key,) if isinstance(key_fields, str) else key
            key_names = (key_fields,) if isinstance(key_fields, str) else key_fields
            obj = model_cls(**dict(zip(key_names, key_values)))
            for model_attr, value in after.items():
                setattr(obj, model_attr, value)
            db.add(obj)
            existing_by_key[key] = obj
            summary[tab_name]["created"] += 1
            _record_change(
                db,
                version_id=version_id,
                entity_type=entity_type,
                entity_id=entity_id,
                change_type="created",
                before_state=None,
                after_state=after,
            )
            continue

        if before == after:
            summary[tab_name]["unchanged"] += 1
            continue

        for model_attr, value in after.items():
            setattr(obj, model_attr, value)
        summary[tab_name]["changed"] += 1
        _record_change(
            db,
            version_id=version_id,
            entity_type=entity_type,
            entity_id=entity_id,
            change_type="updated",
            before_state=before,
            after_state=after,
        )
    db.flush()


def _sync_taxonomy(db, data: dict[str, list[dict]]) -> None:
    """Upsert optional normalized taxonomy tabs and activate only approved snapshots."""
    version_rows = data.get("taxonomy_versions", [])
    if not version_rows:
        return

    requested_active_versions: list[str] = []
    for row in version_rows:
        version_id = str(row.get("version_id", "")).strip()
        version = db.get(TaxonomyVersion, version_id)
        if version is None:
            version = TaxonomyVersion(version_id=version_id)
            db.add(version)
        version.name = str(row.get("name", "")).strip()
        requested_status = _normalize_status(row.get("status"), "draft")
        if requested_status == "active":
            requested_active_versions.append(version_id)
            version.status = "approved"
        else:
            version.status = requested_status
        version.effective_date = _coerce_date(row.get("effective_date"))

    # Insert class identifiers before assigning self-referencing parents.
    for row in data.get("product_classes", []):
        class_id = str(row.get("class_id", "")).strip()
        product_class = db.get(ProductClass, class_id)
        if product_class is None:
            product_class = ProductClass(class_id=class_id)
            db.add(product_class)
        product_class.name = str(row.get("name", "")).strip()
        product_class.approval_status = _normalize_status(
            row.get("approval_status"), "pending"
        )
        product_class.parent_class_id = None
    db.flush()
    for row in data.get("product_classes", []):
        class_id = str(row.get("class_id", "")).strip()
        db.get(ProductClass, class_id).parent_class_id = (
            str(row.get("parent_class_id", "")).strip() or None
        )

    for row in data.get("product_families", []):
        family_id = str(row.get("family_id", "")).strip()
        family = db.get(ProductFamily, family_id)
        if family is None:
            family = ProductFamily(family_id=family_id)
            db.add(family)
        family.name = str(row.get("name", "")).strip()
        family.class_id = str(row.get("class_id", "")).strip()
        family.emdn_code = str(row.get("emdn_code", "")).strip() or None
        family.gmdn_code = str(row.get("gmdn_code", "")).strip() or None
        family.approval_status = _normalize_status(
            row.get("approval_status"), "pending"
        )

    for row in data.get("clinical_specialties", []):
        specialty_code = str(row.get("specialty_code", "")).strip()
        specialty = db.get(ClinicalSpecialty, specialty_code)
        if specialty is None:
            specialty = ClinicalSpecialty(specialty_code=specialty_code)
            db.add(specialty)
        specialty.name = str(row.get("name", "")).strip()
        specialty.active = _coerce_bool(row.get("active"), default=True)

    db.flush()

    for row in data.get("taxonomy_version_families", []):
        key = (
            str(row.get("version_id", "")).strip(),
            str(row.get("family_id", "")).strip(),
        )
        if db.get(TaxonomyVersionFamily, key) is None:
            db.add(TaxonomyVersionFamily(version_id=key[0], family_id=key[1]))

    for row in data.get("product_taxonomy_assignments", []):
        key = (
            str(row.get("version_id", "")).strip(),
            str(row.get("product_id", "")).strip(),
        )
        assignment = db.get(ProductTaxonomyAssignment, key)
        if assignment is None:
            assignment = ProductTaxonomyAssignment(
                version_id=key[0],
                product_id=key[1],
            )
            db.add(assignment)
        assignment.family_id = str(row.get("family_id", "")).strip()
        assignment.approval_status = _normalize_status(
            row.get("approval_status"), "pending"
        )

    for row in data.get("product_specialties", []):
        key = (
            str(row.get("version_id", "")).strip(),
            str(row.get("product_id", "")).strip(),
            str(row.get("specialty_code", "")).strip(),
        )
        mapping = db.get(ProductSpecialty, key)
        if mapping is None:
            mapping = ProductSpecialty(
                version_id=key[0],
                product_id=key[1],
                specialty_code=key[2],
            )
            db.add(mapping)
        mapping.is_primary = _coerce_bool(row.get("is_primary"), default=False)
        mapping.approval_status = _normalize_status(
            row.get("approval_status"), "pending"
        )

    for row in data.get("product_attributes", []):
        key = (
            str(row.get("version_id", "")).strip(),
            str(row.get("product_id", "")).strip(),
            str(row.get("attribute_code", "")).strip(),
        )
        attribute = db.get(ProductAttribute, key)
        if attribute is None:
            attribute = ProductAttribute(
                version_id=key[0],
                product_id=key[1],
                attribute_code=key[2],
            )
            db.add(attribute)
        attribute.value = str(row.get("value", "")).strip()
        attribute.unit = str(row.get("unit", "")).strip() or None
        attribute.approval_status = _normalize_status(
            row.get("approval_status"), "pending"
        )

    db.flush()
    for version_id in requested_active_versions:
        activate_taxonomy_version(db, version_id)
        logger.info("Taxonomy version activated: %s", version_id)

    logger.info(
        "Taxonomy: %d versions, %d classes, %d families, %d product assignments, "
        "%d specialty mappings, %d attributes",
        len(version_rows),
        len(data.get("product_classes", [])),
        len(data.get("product_families", [])),
        len(data.get("product_taxonomy_assignments", [])),
        len(data.get("product_specialties", [])),
        len(data.get("product_attributes", [])),
    )


def _sync_product_classes_versioned(
    db,
    *,
    version_id: int,
    summary: dict[str, dict[str, int]],
    rows: list[dict],
) -> None:
    pending: list[tuple[ProductClass, str, dict | None, dict]] = []
    class_ids = [str(row.get("class_id", "")).strip() for row in rows]
    existing_by_id = {
        obj.class_id: obj
        for obj in (
            db.query(ProductClass).filter(ProductClass.class_id.in_(class_ids)).all()
            if class_ids
            else []
        )
    }
    for row in rows:
        class_id = str(row.get("class_id", "")).strip()
        obj = existing_by_id.get(class_id)
        before = _current_state(obj, PRODUCT_CLASS_FIELDS) if obj is not None else None
        after = _desired_state(obj, row, PRODUCT_CLASS_FIELDS)
        if obj is None:
            obj = ProductClass(
                class_id=class_id,
                name=after["name"],
                parent_class_id=None,
                approval_status=after["approval_status"],
            )
            db.add(obj)
            existing_by_id[class_id] = obj
        pending.append((obj, class_id, before, after))

    # Self-referencing class parents must exist before parent_class_id is assigned.
    db.flush()
    for obj, class_id, before, after in pending:
        if before == after:
            summary["product_classes"]["unchanged"] += 1
            continue
        for model_attr, value in after.items():
            setattr(obj, model_attr, value)
        change_type = "created" if before is None else "updated"
        summary["product_classes"][
            "created" if before is None else "changed"
        ] += 1
        _record_change(
            db,
            version_id=version_id,
            entity_type="product_class",
            entity_id=class_id,
            change_type=change_type,
            before_state=before,
            after_state=after,
        )
    db.flush()


def _sync_taxonomy_versioned(
    db,
    *,
    version_id: int,
    summary: dict[str, dict[str, int]],
    data: dict[str, list[dict]],
) -> None:
    version_rows = data.get("taxonomy_versions", [])
    if not version_rows:
        return

    requested_active_ids: list[str] = []
    version_before: dict[str, dict | None] = {}
    incoming_version_ids = [
        str(row.get("version_id", "")).strip() for row in version_rows
    ]
    existing_versions = {
        obj.version_id: obj
        for obj in db.query(TaxonomyVersion)
        .filter(TaxonomyVersion.version_id.in_(incoming_version_ids))
        .all()
    }
    for row in version_rows:
        taxonomy_version_id = str(row.get("version_id", "")).strip()
        obj = existing_versions.get(taxonomy_version_id)
        before = _current_state(obj, TAXONOMY_VERSION_FIELDS) if obj is not None else None
        version_before[taxonomy_version_id] = before
        requested_status = _normalize_status(row.get("status"), "draft")
        desired = _desired_state(obj, row, TAXONOMY_VERSION_FIELDS)
        if requested_status == "active":
            requested_active_ids.append(taxonomy_version_id)
            desired["status"] = "active" if before and before["status"] == "active" else "approved"
        if obj is None:
            obj = TaxonomyVersion(version_id=taxonomy_version_id)
            db.add(obj)
            existing_versions[taxonomy_version_id] = obj
        current = _current_state(obj, TAXONOMY_VERSION_FIELDS) if before is not None else None
        if current != desired:
            for model_attr, value in desired.items():
                setattr(obj, model_attr, value)
    db.flush()

    _sync_product_classes_versioned(
        db,
        version_id=version_id,
        summary=summary,
        rows=data.get("product_classes", []),
    )
    _sync_model_rows(
        db,
        version_id=version_id,
        summary=summary,
        tab_name="product_families",
        entity_type="product_family",
        model_cls=ProductFamily,
        key_fields="family_id",
        rows=data.get("product_families", []),
        fields=PRODUCT_FAMILY_FIELDS,
    )
    _sync_model_rows(
        db,
        version_id=version_id,
        summary=summary,
        tab_name="clinical_specialties",
        entity_type="clinical_specialty",
        model_cls=ClinicalSpecialty,
        key_fields="specialty_code",
        rows=data.get("clinical_specialties", []),
        fields=CLINICAL_SPECIALTY_FIELDS,
    )
    _sync_model_rows(
        db,
        version_id=version_id,
        summary=summary,
        tab_name="taxonomy_version_families",
        entity_type="taxonomy_version_family",
        model_cls=TaxonomyVersionFamily,
        key_fields=("version_id", "family_id"),
        rows=data.get("taxonomy_version_families", []),
        fields={},
    )
    _sync_model_rows(
        db,
        version_id=version_id,
        summary=summary,
        tab_name="product_taxonomy_assignments",
        entity_type="product_taxonomy_assignment",
        model_cls=ProductTaxonomyAssignment,
        key_fields=("version_id", "product_id"),
        rows=data.get("product_taxonomy_assignments", []),
        fields=PRODUCT_TAXONOMY_ASSIGNMENT_FIELDS,
    )
    _sync_model_rows(
        db,
        version_id=version_id,
        summary=summary,
        tab_name="product_specialties",
        entity_type="product_specialty",
        model_cls=ProductSpecialty,
        key_fields=("version_id", "product_id", "specialty_code"),
        rows=data.get("product_specialties", []),
        fields=PRODUCT_SPECIALTY_FIELDS,
    )
    _sync_model_rows(
        db,
        version_id=version_id,
        summary=summary,
        tab_name="product_attributes",
        entity_type="product_attribute",
        model_cls=ProductAttribute,
        key_fields=("version_id", "product_id", "attribute_code"),
        rows=data.get("product_attributes", []),
        fields=PRODUCT_ATTRIBUTE_FIELDS,
    )

    previously_active = {
        row.version_id: _current_state(row, TAXONOMY_VERSION_FIELDS)
        for row in db.query(TaxonomyVersion)
        .filter(TaxonomyVersion.status == "active")
        .all()
    }
    for taxonomy_version_id in requested_active_ids:
        obj = db.get(TaxonomyVersion, taxonomy_version_id)
        if obj.status != "active":
            activate_taxonomy_version(db, taxonomy_version_id)
    db.flush()

    affected_version_ids = set(version_before) | set(previously_active)
    for taxonomy_version_id in sorted(affected_version_ids):
        before = version_before.get(
            taxonomy_version_id, previously_active.get(taxonomy_version_id)
        )
        obj = db.get(TaxonomyVersion, taxonomy_version_id)
        after = _current_state(obj, TAXONOMY_VERSION_FIELDS)
        if before == after:
            summary["taxonomy_versions"]["unchanged"] += 1
            continue
        created = before is None
        summary["taxonomy_versions"]["created" if created else "changed"] += 1
        _record_change(
            db,
            version_id=version_id,
            entity_type="taxonomy_version",
            entity_id=taxonomy_version_id,
            change_type="created" if created else "updated",
            before_state=before,
            after_state=after,
        )
    db.flush()


def _sync_aliases(
    db,
    *,
    version_id: int,
    summary: dict[str, dict[str, int]],
    rows: list[dict],
    reconcile_product_ids: set[str],
) -> None:
    target_keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        product_id = str(row.get("product_id", "")).strip()
        for alias in split_multi_value_cell(row.get("alias", "")):
            key = (product_id, alias)
            if key not in seen:
                seen.add(key)
                target_keys.append(key)

    target_product_ids = {product_id for product_id, _ in target_keys}
    loaded_product_ids = reconcile_product_ids | target_product_ids
    existing_rows = (
        db.query(Alias).filter(Alias.product_id.in_(loaded_product_ids)).all()
        if loaded_product_ids
        else []
    )
    existing_by_key: dict[tuple[str, str], Alias] = {}
    duplicate_existing: list[Alias] = []
    for alias_row in existing_rows:
        key = (str(alias_row.product_id), str(alias_row.alias))
        if key in existing_by_key:
            duplicate_existing.append(alias_row)
        else:
            existing_by_key[key] = alias_row

    target_set = set(target_keys)
    for product_id, alias in target_keys:
        key = (product_id, alias)
        if key in existing_by_key:
            summary["aliases"]["unchanged"] += 1
            continue
        db.add(Alias(product_id=product_id, alias=alias))
        summary["aliases"]["created"] += 1
        _record_change(
            db,
            version_id=version_id,
            entity_type="alias",
            entity_id=f"{product_id}:{alias}",
            change_type="created",
            before_state=None,
            after_state={"product_id": product_id, "alias": alias},
        )

    stale_rows = [
        alias_row
        for key, alias_row in existing_by_key.items()
        if key not in target_set and alias_row.product_id in reconcile_product_ids
    ] + [
        alias_row
        for alias_row in duplicate_existing
        if alias_row.product_id in reconcile_product_ids
    ]
    for alias_row in stale_rows:
        before = {"product_id": alias_row.product_id, "alias": alias_row.alias}
        db.delete(alias_row)
        summary["aliases"]["changed"] += 1
        _record_change(
            db,
            version_id=version_id,
            entity_type="alias",
            entity_id=f"{alias_row.product_id}:{alias_row.alias}",
            change_type="removed",
            before_state=before,
            after_state=None,
        )
    db.flush()


def _log_summary(summary: dict[str, dict[str, int]]) -> None:
    for tab_name, counts in summary.items():
        logger.info(
            "%s: %d unchanged, %d changed, %d created, %d skipped_invalid",
            tab_name.replace("_", " ").title(),
            counts["unchanged"],
            counts["changed"],
            counts["created"],
            counts["skipped_invalid"],
        )


def sync_catalog_snapshot(db, data: dict[str, list[dict]], dry_run: bool = False) -> SyncRunResult:
    """Validate and version one prepared catalog snapshot in a single transaction."""
    validation = validate_catalog_snapshot(data)
    filtered = validation.data
    summary = {
        tab_name: _blank_summary()
        for tab_name in dict.fromkeys((*CORE_TABS, *filtered.keys()))
        if tab_name in TAB_ENTITY_TYPES
    }

    sync_version = SyncVersion(
        started_at=datetime.now(UTC).replace(tzinfo=None),
        status="in_progress",
        summary={},
    )
    try:
        db.add(sync_version)
        db.flush()
        version_id = sync_version.version_id

        for issue in validation.skipped:
            summary.setdefault(issue.tab_name, _blank_summary())
            summary[issue.tab_name]["skipped_invalid"] += 1
            _record_change(
                db,
                version_id=version_id,
                entity_type=TAB_ENTITY_TYPES.get(
                    issue.tab_name, issue.tab_name.removesuffix("s")
                ),
                entity_id=issue.entity_id,
                change_type="skipped_invalid",
                before_state=None,
                after_state=None,
                reason=issue.reason,
            )
            logger.warning("Skipped invalid catalog input: %s", issue.reason)

        _sync_model_rows(
            db,
            version_id=version_id,
            summary=summary,
            tab_name="products",
            entity_type="product",
            model_cls=Product,
            key_fields="product_id",
            rows=filtered.get("products", []),
            fields=PRODUCT_FIELDS,
        )
        _sync_model_rows(
            db,
            version_id=version_id,
            summary=summary,
            tab_name="vendors",
            entity_type="vendor",
            model_cls=Vendor,
            key_fields="vendor_id",
            rows=filtered.get("vendors", []),
            fields=VENDOR_FIELDS,
        )
        _sync_model_rows(
            db,
            version_id=version_id,
            summary=summary,
            tab_name="inventory",
            entity_type="inventory",
            model_cls=Inventory,
            key_fields="inventory_id",
            rows=filtered.get("inventory", []),
            fields=INVENTORY_FIELDS,
        )
        _sync_model_rows(
            db,
            version_id=version_id,
            summary=summary,
            tab_name="pricing",
            entity_type="pricing",
            model_cls=Pricing,
            key_fields="pricing_id",
            rows=filtered.get("pricing", []),
            fields=PRICING_FIELDS,
        )
        invalid_alias_product_ids = {
            str(issue.row.get("product_id", "")).strip()
            for issue in validation.skipped
            if issue.tab_name == "aliases"
            and str(issue.row.get("product_id", "")).strip()
        }
        _sync_aliases(
            db,
            version_id=version_id,
            summary=summary,
            rows=filtered.get("aliases", []),
            reconcile_product_ids={
                str(row.get("product_id", "")).strip()
                for row in filtered.get("products", [])
            }
            - invalid_alias_product_ids,
        )

        _sync_taxonomy_versioned(
            db,
            version_id=version_id,
            summary=summary,
            data=filtered,
        )

        sync_version.summary = summary
        sync_version.status = "completed"
        sync_version.completed_at = datetime.now(UTC).replace(tzinfo=None)
        _log_summary(summary)

        if dry_run:
            db.rollback()
            logger.info("Dry run complete: rolled back all staged changes and version history")
            return SyncRunResult(version_id=None, summary=summary)

        db.commit()
        return SyncRunResult(version_id=version_id, summary=summary)
    except Exception:
        db.rollback()
        raise


def list_sync_versions(db, limit: int = 20) -> list[dict]:
    rows = (
        db.query(SyncVersion)
        .order_by(SyncVersion.version_id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "version_id": row.version_id,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "status": row.status,
            "summary": row.summary,
        }
        for row in rows
    ]


def get_catalog_change_history(
    db,
    *,
    version_id: int | None = None,
    entity_id: str | None = None,
) -> list[dict]:
    query = db.query(CatalogChangeLog)
    if version_id is not None:
        query = query.filter(CatalogChangeLog.version_id == version_id)
    if entity_id is not None:
        query = query.filter(CatalogChangeLog.entity_id == entity_id)
    rows = query.order_by(CatalogChangeLog.changed_at.desc(), CatalogChangeLog.id.desc()).all()
    return [
        {
            "id": row.id,
            "version_id": row.version_id,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "change_type": row.change_type,
            "before_state": row.before_state,
            "after_state": row.after_state,
            "reason": row.reason,
            "changed_at": row.changed_at.isoformat() if row.changed_at else None,
        }
        for row in rows
    ]

# ─── main ─────────────────────────────────────────────────────────────────────

def sync_sheets_to_db(dry_run: bool = False):
    from app.integrations.sheets import load_data as load_from_sheets

    logger.info("Starting sync from Google Sheets → PostgreSQL%s …", " (dry run)" if dry_run else "")

    # 1. Run migrations first. Abort if they fail.
    if dry_run:
        logger.info("Dry run: skipping migrations")
    else:
        result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Alembic migration failed:\n%s", result.stderr)
            sys.exit(1)
        logger.info("Migrations OK")

    # 2. Pull from Sheets.
    try:
        raw = load_from_sheets()
    except Exception as exc:
        logger.error("Failed to load from Google Sheets: %s", exc)
        sys.exit(1)

    data = prepare_sheet_data(raw)

    logger.info(
        "Loaded from Sheets: %d products, %d vendors, %d inventory, %d pricing, %d aliases",
        len(data["products"]),
        len(data["vendors"]),
        len(data["inventory"]),
        len(data["pricing"]),
        len(data["aliases"]),
    )

    phone_quality = summarize_vendor_phone_issues(data["vendors"])
    logger.info(
        "Vendor phones — valid: %d, missing: %d, invalid format: %d",
        phone_quality["valid"],
        phone_quality["missing"],
        phone_quality["invalid"],
    )
    if phone_quality["valid"] < 3:
        logger.warning(
            "LAUNCH BLOCKER: fewer than 3 vendors have valid +countrycode phones. "
            "WhatsApp RFQ routing will silently fail."
        )

    # 3. Validate, diff, version, and apply everything in one transaction.
    db = SessionLocal()
    try:
        result = sync_catalog_snapshot(db, data, dry_run=dry_run)
    except Exception as exc:
        logger.error("Sync failed — rolled back: %s", exc)
        raise
    finally:
        db.close()

    # 4. Clear Redis cache AFTER a successful sync.
    if dry_run:
        logger.info("Dry run: Redis cache not cleared")
    else:
        try:
            from app.core.cache import clear_cache
            cleared = clear_cache()
            if cleared:
                logger.info("Redis cache cleared — next request will serve fresh data")
        except Exception as exc:
            logger.warning("Could not clear Redis cache (non-fatal): %s", exc)

    logger.info("Sync complete.")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync SocioMED Google Sheets data into the database.")
    parser.add_argument("--dry-run", action="store_true", help="Preview inserts/updates/deletes and roll them back.")
    history = parser.add_mutually_exclusive_group()
    history.add_argument(
        "--list-versions",
        nargs="?",
        type=int,
        const=20,
        metavar="LIMIT",
        help="List recent catalog sync versions as JSON (default: 20).",
    )
    history.add_argument(
        "--version-changes",
        type=int,
        metavar="VERSION_ID",
        help="List changes recorded for one sync version as JSON.",
    )
    history.add_argument(
        "--entity-history",
        metavar="ENTITY_ID",
        help="List the recorded history for one catalog entity ID as JSON.",
    )
    args = parser.parse_args()
    if (
        args.list_versions is not None
        or args.version_changes is not None
        or args.entity_history is not None
    ):
        history_db = SessionLocal()
        try:
            if args.list_versions is not None:
                payload = list_sync_versions(history_db, limit=args.list_versions)
            else:
                payload = get_catalog_change_history(
                    history_db,
                    version_id=args.version_changes,
                    entity_id=args.entity_history,
                )
            print(json.dumps(payload, indent=2, sort_keys=True))
        finally:
            history_db.close()
    else:
        sync_sheets_to_db(dry_run=args.dry_run)
