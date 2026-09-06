import re
from dataclasses import dataclass
from typing import Dict, List


REQUIRED_SHEET_COLUMNS = {
    "products": {"product_id", "name", "category"},
    "vendors": {"vendor_id", "name", "phone", "email", "region"},
    "inventory": {"inventory_id", "product_id", "vendor_id", "brand", "uom", "stock_qty", "lead_time_days"},
    "pricing": {"pricing_id", "inventory_id", "min_qty", "max_qty", "unit_price"},
    "aliases": {"alias", "product_id"},
    "taxonomy_versions": {"version_id", "name", "status"},
    "product_classes": {"class_id", "name", "approval_status"},
    "product_families": {"family_id", "name", "class_id", "approval_status"},
    "taxonomy_version_families": {"version_id", "family_id"},
    "product_taxonomy_assignments": {
        "version_id",
        "product_id",
        "family_id",
        "approval_status",
    },
    "clinical_specialties": {"specialty_code", "name"},
    "product_specialties": {
        "version_id",
        "product_id",
        "specialty_code",
        "is_primary",
        "approval_status",
    },
    "product_attributes": {
        "version_id",
        "product_id",
        "attribute_code",
        "value",
        "approval_status",
    },
}

REQUIRED_ROW_VALUES = {
    "products": ("product_id", "name", "category"),
    "vendors": ("vendor_id", "name"),
    "inventory": ("inventory_id", "product_id", "vendor_id"),
    "pricing": ("pricing_id", "inventory_id", "min_qty", "unit_price"),
    "aliases": ("alias", "product_id"),
    "taxonomy_versions": ("version_id", "name", "status"),
    "product_classes": ("class_id", "name", "approval_status"),
    "product_families": ("family_id", "name", "class_id", "approval_status"),
    "taxonomy_version_families": ("version_id", "family_id"),
    "product_taxonomy_assignments": (
        "version_id",
        "product_id",
        "family_id",
        "approval_status",
    ),
    "clinical_specialties": ("specialty_code", "name"),
    "product_specialties": (
        "version_id",
        "product_id",
        "specialty_code",
        "is_primary",
        "approval_status",
    ),
    "product_attributes": (
        "version_id",
        "product_id",
        "attribute_code",
        "value",
        "approval_status",
    ),
}
PRIMARY_KEYS = {
    "products": "product_id",
    "vendors": "vendor_id",
    "inventory": "inventory_id",
    "pricing": "pricing_id",
    "taxonomy_versions": "version_id",
    "product_classes": "class_id",
    "product_families": "family_id",
    "clinical_specialties": "specialty_code",
}

COMPOSITE_PRIMARY_KEYS = {
    "taxonomy_version_families": ("version_id", "family_id"),
    "product_taxonomy_assignments": ("version_id", "product_id"),
    "product_specialties": ("version_id", "product_id", "specialty_code"),
    "product_attributes": ("version_id", "product_id", "attribute_code"),
}

APPROVAL_STATUSES = {"pending", "approved", "revise", "rejected"}
TAXONOMY_VERSION_STATUSES = {"draft", "approved", "active", "retired"}

KNOWN_E164_PREFIXES = ("211", "243", "250", "254", "255", "256", "257", "258")
MULTI_VALUE_SEPARATOR_PATTERN = r"\s*(?:\||;|,)\s*"


@dataclass(frozen=True)
class CatalogValidationIssue:
    tab_name: str
    row_number: int | None
    entity_id: str
    reason: str
    row: Dict


@dataclass(frozen=True)
class CatalogValidationResult:
    data: Dict[str, List[Dict]]
    skipped: List[CatalogValidationIssue]


def normalize_sheet_header(header: str) -> str:
    cleaned = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(header).strip())
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", cleaned)
    return cleaned.strip("_").lower()


def normalize_cell_value(value):
    if isinstance(value, str):
        return value.strip()
    return value


def split_multi_value_cell(value) -> List[str]:
    if value in (None, ""):
        return []
    parts = re.split(MULTI_VALUE_SEPARATOR_PATTERN, str(value).strip())
    return [part.strip() for part in parts if part.strip()]


def normalize_multi_value_cell(value) -> str:
    return " | ".join(split_multi_value_cell(value))


def normalize_vendor_phone(phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", str(phone or "").strip())
    if not cleaned:
        return ""
    if cleaned.startswith("00"):
        return f"+{cleaned[2:]}"
    if cleaned.startswith("+"):
        return cleaned
    digits = re.sub(r"\D", "", cleaned)
    if digits.startswith(KNOWN_E164_PREFIXES):
        return f"+{digits}"
    return cleaned


def normalize_sheet_rows(rows: List[Dict], tab_name: str) -> List[Dict]:
    normalized_rows = []
    for row in rows:
        normalized = {}
        for key, value in row.items():
            normalized_key = normalize_sheet_header(key)
            if normalized_key:
                normalized[normalized_key] = normalize_cell_value(value)
        if tab_name == "products":
            for multi_value_key in ("clinical_speciality", "related_ids"):
                if multi_value_key in normalized:
                    normalized[multi_value_key] = normalize_multi_value_cell(normalized.get(multi_value_key))
        if tab_name == "vendors":
            normalized["phone"] = normalize_vendor_phone(normalized.get("phone", ""))
        normalized_rows.append(normalized)
    return normalized_rows


def prepare_sheet_data(data: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
    normalized_data: Dict[str, List[Dict]] = {}
    for tab_name, rows in data.items():
        normalized_rows = normalize_sheet_rows(rows, tab_name)
        validate_required_columns(tab_name, normalized_rows)
        normalized_data[tab_name] = normalized_rows
    return normalized_data


def _number(value, *, field: str, row_number: int) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"pricing row {row_number}: {field} must be numeric") from exc


def validate_catalog_snapshot(data: Dict[str, List[Dict]]) -> CatalogValidationResult:
    """Return only valid rows, preserving every rejected row and its reasons."""
    reasons: dict[tuple[str, int], list[str]] = {}
    tab_issues: list[CatalogValidationIssue] = []

    def reject(tab_name: str, index: int, reason: str) -> None:
        bucket = reasons.setdefault((tab_name, index), [])
        if reason not in bucket:
            bucket.append(reason)

    def surviving(tab_name: str) -> list[tuple[int, Dict]]:
        return [
            (index, row)
            for index, row in enumerate(data.get(tab_name, []))
            if (tab_name, index) not in reasons
        ]

    def ids(tab_name: str, field: str, *, valid_only: bool) -> set[str]:
        rows = surviving(tab_name) if valid_only else enumerate(data.get(tab_name, []))
        return {
            str(row.get(field, "")).strip()
            for _, row in rows
            if str(row.get(field, "")).strip()
        }

    def reject_fk(
        tab_name: str,
        field: str,
        original_ids: set[str],
        valid_ids: set[str],
    ) -> None:
        for index, row in surviving(tab_name):
            value = str(row.get(field, "")).strip()
            if not value:
                continue
            if value not in original_ids:
                reject(tab_name, index, f"unknown {field} '{value}'")
            elif value not in valid_ids:
                reject(tab_name, index, f"{field} '{value}' did not pass validation")

    for tab_name in ("products", "vendors", "inventory", "pricing"):
        if not data.get(tab_name):
            tab_issues.append(
                CatalogValidationIssue(
                    tab_name=tab_name,
                    row_number=None,
                    entity_id="tab",
                    reason=f"{tab_name}: tab has no data rows",
                    row={},
                )
            )

    for tab_name, required_values in REQUIRED_ROW_VALUES.items():
        for index, row in enumerate(data.get(tab_name, [])):
            missing = [field for field in required_values if row.get(field) in (None, "")]
            if missing:
                reject(tab_name, index, f"missing {', '.join(missing)}")

    for tab_name, primary_key in PRIMARY_KEYS.items():
        seen: dict[str, int] = {}
        for index, row in enumerate(data.get(tab_name, [])):
            value = str(row.get(primary_key, "")).strip()
            if not value:
                continue
            if value in seen:
                reject(
                    tab_name,
                    index,
                    f"duplicate {primary_key} '{value}' "
                    f"(first seen on row {seen[value] + 2})",
                )
            else:
                seen[value] = index

    for tab_name, key_fields in COMPOSITE_PRIMARY_KEYS.items():
        seen: dict[tuple[str, ...], int] = {}
        for index, row in enumerate(data.get(tab_name, [])):
            key = tuple(str(row.get(field, "")).strip() for field in key_fields)
            if not all(key):
                continue
            if key in seen:
                reject(
                    tab_name,
                    index,
                    f"duplicate key {key} (first seen on row {seen[key] + 2})",
                )
            else:
                seen[key] = index

    for index, row in enumerate(data.get("pricing", [])):
        row_number = index + 2
        min_qty = None
        if row.get("min_qty") not in (None, ""):
            try:
                min_qty = _number(row.get("min_qty"), field="min_qty", row_number=row_number)
                if min_qty < 1:
                    reject("pricing", index, "min_qty must be at least 1")
            except ValueError as exc:
                reject("pricing", index, str(exc).split(": ", 1)[-1])
        if row.get("unit_price") not in (None, ""):
            try:
                if _number(row.get("unit_price"), field="unit_price", row_number=row_number) <= 0:
                    reject("pricing", index, "unit_price must be greater than 0")
            except ValueError as exc:
                reject("pricing", index, str(exc).split(": ", 1)[-1])
        if row.get("max_qty") not in (None, ""):
            try:
                max_qty = _number(row.get("max_qty"), field="max_qty", row_number=row_number)
                if min_qty is not None and max_qty < min_qty:
                    reject("pricing", index, "max_qty cannot be less than min_qty")
            except ValueError as exc:
                reject("pricing", index, str(exc).split(": ", 1)[-1])

    for index, row in enumerate(data.get("taxonomy_versions", [])):
        status = str(row.get("status", "")).strip().casefold()
        if status not in TAXONOMY_VERSION_STATUSES:
            reject(
                "taxonomy_versions",
                index,
                f"unsupported status '{row.get('status', '')}'",
            )

    for tab_name in (
        "product_classes",
        "product_families",
        "product_taxonomy_assignments",
        "product_specialties",
        "product_attributes",
    ):
        for index, row in enumerate(data.get(tab_name, [])):
            status = str(row.get("approval_status", "")).strip().casefold()
            if status not in APPROVAL_STATUSES:
                reject(
                    tab_name,
                    index,
                    f"unsupported approval_status '{row.get('approval_status', '')}'",
                )

    original_product_ids = ids("products", "product_id", valid_only=False)
    original_vendor_ids = ids("vendors", "vendor_id", valid_only=False)
    valid_product_ids = ids("products", "product_id", valid_only=True)
    valid_vendor_ids = ids("vendors", "vendor_id", valid_only=True)
    reject_fk("inventory", "product_id", original_product_ids, valid_product_ids)
    reject_fk("inventory", "vendor_id", original_vendor_ids, valid_vendor_ids)

    original_inventory_ids = ids("inventory", "inventory_id", valid_only=False)
    valid_inventory_ids = ids("inventory", "inventory_id", valid_only=True)
    reject_fk("pricing", "inventory_id", original_inventory_ids, valid_inventory_ids)
    reject_fk("aliases", "product_id", original_product_ids, valid_product_ids)

    taxonomy_child_tabs = (
        "product_classes",
        "product_families",
        "taxonomy_version_families",
        "product_taxonomy_assignments",
        "clinical_specialties",
        "product_specialties",
        "product_attributes",
    )
    original_version_ids = ids("taxonomy_versions", "version_id", valid_only=False)
    if not original_version_ids and any(data.get(tab_name) for tab_name in taxonomy_child_tabs):
        reason = "taxonomy_versions: add a version row before importing taxonomy tables"
        for tab_name in taxonomy_child_tabs:
            for index, _ in surviving(tab_name):
                reject(tab_name, index, reason)

    original_class_ids = ids("product_classes", "class_id", valid_only=False)
    while True:
        reason_count = sum(len(values) for values in reasons.values())
        valid_class_ids = ids("product_classes", "class_id", valid_only=True)
        reject_fk(
            "product_classes", "parent_class_id", original_class_ids, valid_class_ids
        )
        if sum(len(values) for values in reasons.values()) == reason_count:
            break

    valid_class_ids = ids("product_classes", "class_id", valid_only=True)
    reject_fk("product_families", "class_id", original_class_ids, valid_class_ids)

    original_family_ids = ids("product_families", "family_id", valid_only=False)
    valid_family_ids = ids("product_families", "family_id", valid_only=True)
    original_specialty_codes = ids(
        "clinical_specialties", "specialty_code", valid_only=False
    )
    valid_specialty_codes = ids(
        "clinical_specialties", "specialty_code", valid_only=True
    )
    valid_version_ids = ids("taxonomy_versions", "version_id", valid_only=True)

    for tab_name in (
        "taxonomy_version_families",
        "product_taxonomy_assignments",
        "product_specialties",
        "product_attributes",
    ):
        reject_fk(tab_name, "version_id", original_version_ids, valid_version_ids)

    reject_fk(
        "taxonomy_version_families",
        "family_id",
        original_family_ids,
        valid_family_ids,
    )
    reject_fk(
        "product_taxonomy_assignments",
        "product_id",
        original_product_ids,
        valid_product_ids,
    )
    reject_fk(
        "product_taxonomy_assignments",
        "family_id",
        original_family_ids,
        valid_family_ids,
    )
    reject_fk(
        "product_specialties", "product_id", original_product_ids, valid_product_ids
    )
    reject_fk(
        "product_specialties",
        "specialty_code",
        original_specialty_codes,
        valid_specialty_codes,
    )
    reject_fk(
        "product_attributes", "product_id", original_product_ids, valid_product_ids
    )

    active_rows = [
        (index, row)
        for index, row in surviving("taxonomy_versions")
        if str(row.get("status", "")).strip().casefold() == "active"
    ]
    for index, _ in active_rows[1:]:
        reject("taxonomy_versions", index, "only one version can be active")

    for version_index, version_row in active_rows[:1]:
        if ("taxonomy_versions", version_index) in reasons:
            continue
        version_id = str(version_row.get("version_id", "")).strip()
        version_errors: list[str] = []
        assignment_rows = [
            row
            for _, row in surviving("product_taxonomy_assignments")
            if str(row.get("version_id", "")).strip() == version_id
        ]
        if len(assignment_rows) != len(original_product_ids):
            version_errors.append(
                f"assigns {len(assignment_rows)} of {len(original_product_ids)} products"
            )
        for tab_name in (
            "product_taxonomy_assignments",
            "product_specialties",
            "product_attributes",
        ):
            pending_count = sum(
                1
                for _, row in surviving(tab_name)
                if str(row.get("version_id", "")).strip() == version_id
                and str(row.get("approval_status", "")).strip().casefold()
                != "approved"
            )
            if pending_count:
                version_errors.append(
                    f"{pending_count} rows in {tab_name} are not approved"
                )

        version_family_ids = {
            str(row.get("family_id", "")).strip()
            for _, row in surviving("taxonomy_version_families")
            if str(row.get("version_id", "")).strip() == version_id
        }
        assigned_family_ids = {
            str(row.get("family_id", "")).strip() for row in assignment_rows
        }
        missing_version_families = assigned_family_ids - version_family_ids
        if missing_version_families:
            version_errors.append(
                f"{len(missing_version_families)} assigned families are missing "
                "from the version dictionary"
            )
        unapproved_family_count = sum(
            1
            for _, row in surviving("product_families")
            if str(row.get("family_id", "")).strip() in version_family_ids
            and str(row.get("approval_status", "")).strip().casefold()
            != "approved"
        )
        if unapproved_family_count:
            version_errors.append(
                f"{unapproved_family_count} product families are not approved"
            )
        version_class_ids = {
            str(row.get("class_id", "")).strip()
            for _, row in surviving("product_families")
            if str(row.get("family_id", "")).strip() in version_family_ids
        }
        unapproved_class_count = sum(
            1
            for _, row in surviving("product_classes")
            if str(row.get("class_id", "")).strip() in version_class_ids
            and str(row.get("approval_status", "")).strip().casefold()
            != "approved"
        )
        if unapproved_class_count:
            version_errors.append(
                f"{unapproved_class_count} product classes are not approved"
            )

        primary_counts: dict[str, int] = {}
        mapped_specialty_codes: set[str] = set()
        for _, row in surviving("product_specialties"):
            if str(row.get("version_id", "")).strip() != version_id:
                continue
            mapped_specialty_codes.add(str(row.get("specialty_code", "")).strip())
            if str(row.get("is_primary", "")).strip().casefold() in {
                "true",
                "yes",
                "1",
                "y",
            }:
                product_id = str(row.get("product_id", "")).strip()
                primary_counts[product_id] = primary_counts.get(product_id, 0) + 1
        duplicate_primaries = sum(1 for count in primary_counts.values() if count > 1)
        if duplicate_primaries:
            version_errors.append(
                f"{duplicate_primaries} products have more than one primary specialty"
            )
        inactive_specialty_count = sum(
            1
            for _, row in surviving("clinical_specialties")
            if str(row.get("specialty_code", "")).strip() in mapped_specialty_codes
            and str(row.get("active", "true")).strip().casefold()
            in {"false", "no", "0", "n"}
        )
        if inactive_specialty_count:
            version_errors.append(
                f"{inactive_specialty_count} mapped clinical specialties are inactive"
            )
        if version_errors:
            reject(
                "taxonomy_versions",
                version_index,
                f"taxonomy version '{version_id}': " + "; ".join(version_errors),
            )

    valid_version_ids = ids("taxonomy_versions", "version_id", valid_only=True)
    for tab_name in (
        "taxonomy_version_families",
        "product_taxonomy_assignments",
        "product_specialties",
        "product_attributes",
    ):
        reject_fk(tab_name, "version_id", original_version_ids, valid_version_ids)

    if not valid_version_ids:
        for tab_name in taxonomy_child_tabs:
            for index, _ in surviving(tab_name):
                reject(tab_name, index, "no taxonomy version passed validation")

    def entity_id(tab_name: str, row: Dict, row_number: int) -> str:
        if tab_name == "aliases":
            product_id = str(row.get("product_id", "")).strip()
            alias = str(row.get("alias", "")).strip()
            return f"{product_id}:{alias}" if product_id or alias else f"row:{row_number}"
        if tab_name in PRIMARY_KEYS:
            value = str(row.get(PRIMARY_KEYS[tab_name], "")).strip()
            return value or f"row:{row_number}"
        if tab_name in COMPOSITE_PRIMARY_KEYS:
            values = [
                str(row.get(field, "")).strip()
                for field in COMPOSITE_PRIMARY_KEYS[tab_name]
            ]
            return ":".join(values) if any(values) else f"row:{row_number}"
        return f"row:{row_number}"

    filtered = {
        tab_name: [
            row
            for index, row in enumerate(rows)
            if (tab_name, index) not in reasons
        ]
        for tab_name, rows in data.items()
    }
    skipped = list(tab_issues)
    for tab_name, rows in data.items():
        for index, row in enumerate(rows):
            row_reasons = reasons.get((tab_name, index))
            if not row_reasons:
                continue
            row_number = index + 2
            skipped.append(
                CatalogValidationIssue(
                    tab_name=tab_name,
                    row_number=row_number,
                    entity_id=entity_id(tab_name, row, row_number),
                    reason=(
                        f"{tab_name} row {row_number}: "
                        + "; ".join(row_reasons)
                    ),
                    row=dict(row),
                )
            )
    return CatalogValidationResult(data=filtered, skipped=skipped)


def validate_required_columns(tab_name: str, rows: List[Dict]) -> None:
    required_columns = REQUIRED_SHEET_COLUMNS.get(tab_name, set())
    if not required_columns or not rows:
        return

    present_columns = set()
    for row in rows:
        present_columns.update(row.keys())

    missing = sorted(required_columns - present_columns)
    if missing:
        raise ValueError(
            f"Sheet tab '{tab_name}' is missing required columns: {', '.join(missing)}. "
            "Use lowercase headers that match the clean 5 blueprint."
        )


def summarize_vendor_phone_issues(vendors: List[Dict]) -> Dict[str, int]:
    missing = 0
    invalid = 0
    valid = 0

    for vendor in vendors:
        phone = vendor.get("phone", "")
        if not phone:
            missing += 1
        elif not phone.startswith("+"):
            invalid += 1
        else:
            valid += 1

    return {"valid": valid, "missing": missing, "invalid": invalid}
