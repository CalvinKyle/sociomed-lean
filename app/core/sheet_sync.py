import re
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


def validate_catalog_snapshot(data: Dict[str, List[Dict]]) -> None:
    """Fail a catalog sync before any database writes when key rows or links are unsafe."""
    errors: list[str] = []

    for tab_name in ("products", "vendors", "inventory", "pricing"):
        if not data.get(tab_name):
            errors.append(f"{tab_name}: tab has no data rows")

    for tab_name, required_values in REQUIRED_ROW_VALUES.items():
        for row_number, row in enumerate(data.get(tab_name, []), start=2):
            missing = [field for field in required_values if row.get(field) in (None, "")]
            if missing:
                errors.append(f"{tab_name} row {row_number}: missing {', '.join(missing)}")

    for tab_name, primary_key in PRIMARY_KEYS.items():
        seen: dict[str, int] = {}
        for row_number, row in enumerate(data.get(tab_name, []), start=2):
            value = str(row.get(primary_key, "")).strip()
            if not value:
                continue
            if value in seen:
                errors.append(
                    f"{tab_name} row {row_number}: duplicate {primary_key} '{value}' "
                    f"(first seen on row {seen[value]})"
                )
            else:
                seen[value] = row_number

    for tab_name, key_fields in COMPOSITE_PRIMARY_KEYS.items():
        seen: dict[tuple[str, ...], int] = {}
        for row_number, row in enumerate(data.get(tab_name, []), start=2):
            key = tuple(str(row.get(field, "")).strip() for field in key_fields)
            if not all(key):
                continue
            if key in seen:
                errors.append(
                    f"{tab_name} row {row_number}: duplicate key {key} "
                    f"(first seen on row {seen[key]})"
                )
            else:
                seen[key] = row_number

    product_ids = {str(row.get("product_id", "")).strip() for row in data.get("products", [])}
    vendor_ids = {str(row.get("vendor_id", "")).strip() for row in data.get("vendors", [])}
    inventory_ids = {str(row.get("inventory_id", "")).strip() for row in data.get("inventory", [])}

    for row_number, row in enumerate(data.get("inventory", []), start=2):
        product_id = str(row.get("product_id", "")).strip()
        vendor_id = str(row.get("vendor_id", "")).strip()
        if product_id and product_id not in product_ids:
            errors.append(f"inventory row {row_number}: unknown product_id '{product_id}'")
        if vendor_id and vendor_id not in vendor_ids:
            errors.append(f"inventory row {row_number}: unknown vendor_id '{vendor_id}'")

    for row_number, row in enumerate(data.get("pricing", []), start=2):
        inventory_id = str(row.get("inventory_id", "")).strip()
        if inventory_id and inventory_id not in inventory_ids:
            errors.append(f"pricing row {row_number}: unknown inventory_id '{inventory_id}'")
        if row.get("min_qty") not in (None, ""):
            try:
                min_qty = _number(row.get("min_qty"), field="min_qty", row_number=row_number)
                if min_qty < 1:
                    errors.append(f"pricing row {row_number}: min_qty must be at least 1")
            except ValueError as exc:
                errors.append(str(exc))
                min_qty = None
        else:
            min_qty = None
        if row.get("unit_price") not in (None, ""):
            try:
                if _number(row.get("unit_price"), field="unit_price", row_number=row_number) <= 0:
                    errors.append(f"pricing row {row_number}: unit_price must be greater than 0")
            except ValueError as exc:
                errors.append(str(exc))
        if row.get("max_qty") not in (None, ""):
            try:
                max_qty = _number(row.get("max_qty"), field="max_qty", row_number=row_number)
                if min_qty is not None and max_qty < min_qty:
                    errors.append(f"pricing row {row_number}: max_qty cannot be less than min_qty")
            except ValueError as exc:
                errors.append(str(exc))

    for row_number, row in enumerate(data.get("aliases", []), start=2):
        product_id = str(row.get("product_id", "")).strip()
        if product_id and product_id not in product_ids:
            errors.append(f"aliases row {row_number}: unknown product_id '{product_id}'")

    version_ids = {
        str(row.get("version_id", "")).strip()
        for row in data.get("taxonomy_versions", [])
        if str(row.get("version_id", "")).strip()
    }
    class_ids = {
        str(row.get("class_id", "")).strip()
        for row in data.get("product_classes", [])
        if str(row.get("class_id", "")).strip()
    }
    family_ids = {
        str(row.get("family_id", "")).strip()
        for row in data.get("product_families", [])
        if str(row.get("family_id", "")).strip()
    }
    specialty_codes = {
        str(row.get("specialty_code", "")).strip()
        for row in data.get("clinical_specialties", [])
        if str(row.get("specialty_code", "")).strip()
    }
    taxonomy_child_tabs = (
        "product_classes",
        "product_families",
        "taxonomy_version_families",
        "product_taxonomy_assignments",
        "clinical_specialties",
        "product_specialties",
        "product_attributes",
    )
    if not version_ids and any(data.get(tab_name) for tab_name in taxonomy_child_tabs):
        errors.append(
            "taxonomy_versions: add a version row before importing taxonomy tables"
        )

    for row_number, row in enumerate(data.get("taxonomy_versions", []), start=2):
        status = str(row.get("status", "")).strip().casefold()
        if status not in TAXONOMY_VERSION_STATUSES:
            errors.append(
                f"taxonomy_versions row {row_number}: unsupported status '{row.get('status', '')}'"
            )

    approval_tabs = (
        "product_classes",
        "product_families",
        "product_taxonomy_assignments",
        "product_specialties",
        "product_attributes",
    )
    for tab_name in approval_tabs:
        for row_number, row in enumerate(data.get(tab_name, []), start=2):
            status = str(row.get("approval_status", "")).strip().casefold()
            if status not in APPROVAL_STATUSES:
                errors.append(
                    f"{tab_name} row {row_number}: unsupported approval_status "
                    f"'{row.get('approval_status', '')}'"
                )

    for row_number, row in enumerate(data.get("product_classes", []), start=2):
        parent_class_id = str(row.get("parent_class_id", "")).strip()
        if parent_class_id and parent_class_id not in class_ids:
            errors.append(
                f"product_classes row {row_number}: unknown parent_class_id '{parent_class_id}'"
            )

    for row_number, row in enumerate(data.get("product_families", []), start=2):
        class_id = str(row.get("class_id", "")).strip()
        if class_id and class_id not in class_ids:
            errors.append(f"product_families row {row_number}: unknown class_id '{class_id}'")

    for row_number, row in enumerate(data.get("taxonomy_version_families", []), start=2):
        version_id = str(row.get("version_id", "")).strip()
        family_id = str(row.get("family_id", "")).strip()
        if version_id and version_id not in version_ids:
            errors.append(
                f"taxonomy_version_families row {row_number}: unknown version_id '{version_id}'"
            )
        if family_id and family_id not in family_ids:
            errors.append(
                f"taxonomy_version_families row {row_number}: unknown family_id '{family_id}'"
            )

    for row_number, row in enumerate(data.get("product_taxonomy_assignments", []), start=2):
        version_id = str(row.get("version_id", "")).strip()
        product_id = str(row.get("product_id", "")).strip()
        family_id = str(row.get("family_id", "")).strip()
        if version_id and version_id not in version_ids:
            errors.append(
                f"product_taxonomy_assignments row {row_number}: unknown version_id '{version_id}'"
            )
        if product_id and product_id not in product_ids:
            errors.append(
                f"product_taxonomy_assignments row {row_number}: unknown product_id '{product_id}'"
            )
        if family_id and family_id not in family_ids:
            errors.append(
                f"product_taxonomy_assignments row {row_number}: unknown family_id '{family_id}'"
            )

    for row_number, row in enumerate(data.get("product_specialties", []), start=2):
        version_id = str(row.get("version_id", "")).strip()
        product_id = str(row.get("product_id", "")).strip()
        specialty_code = str(row.get("specialty_code", "")).strip()
        if version_id and version_id not in version_ids:
            errors.append(
                f"product_specialties row {row_number}: unknown version_id '{version_id}'"
            )
        if product_id and product_id not in product_ids:
            errors.append(
                f"product_specialties row {row_number}: unknown product_id '{product_id}'"
            )
        if specialty_code and specialty_code not in specialty_codes:
            errors.append(
                f"product_specialties row {row_number}: unknown specialty_code '{specialty_code}'"
            )

    for row_number, row in enumerate(data.get("product_attributes", []), start=2):
        version_id = str(row.get("version_id", "")).strip()
        product_id = str(row.get("product_id", "")).strip()
        if version_id and version_id not in version_ids:
            errors.append(
                f"product_attributes row {row_number}: unknown version_id '{version_id}'"
            )
        if product_id and product_id not in product_ids:
            errors.append(
                f"product_attributes row {row_number}: unknown product_id '{product_id}'"
            )

    active_versions = [
        str(row.get("version_id", "")).strip()
        for row in data.get("taxonomy_versions", [])
        if str(row.get("status", "")).strip().casefold() == "active"
    ]
    if len(active_versions) > 1:
        errors.append("taxonomy_versions: only one version can be active")

    for version_id in active_versions:
        assignment_rows = [
            row
            for row in data.get("product_taxonomy_assignments", [])
            if str(row.get("version_id", "")).strip() == version_id
        ]
        if len(assignment_rows) != len(product_ids):
            errors.append(
                f"taxonomy version '{version_id}': assigns {len(assignment_rows)} "
                f"of {len(product_ids)} products"
            )
        for tab_name in (
            "product_taxonomy_assignments",
            "product_specialties",
            "product_attributes",
        ):
            pending_count = sum(
                1
                for row in data.get(tab_name, [])
                if str(row.get("version_id", "")).strip() == version_id
                and str(row.get("approval_status", "")).strip().casefold() != "approved"
            )
            if pending_count:
                errors.append(
                    f"taxonomy version '{version_id}': {pending_count} rows in "
                    f"{tab_name} are not approved"
                )

        version_family_ids = {
            str(row.get("family_id", "")).strip()
            for row in data.get("taxonomy_version_families", [])
            if str(row.get("version_id", "")).strip() == version_id
        }
        assigned_family_ids = {
            str(row.get("family_id", "")).strip() for row in assignment_rows
        }
        missing_version_families = assigned_family_ids - version_family_ids
        if missing_version_families:
            errors.append(
                f"taxonomy version '{version_id}': {len(missing_version_families)} "
                "assigned families are missing from the version dictionary"
            )
        unapproved_family_count = sum(
            1
            for row in data.get("product_families", [])
            if str(row.get("family_id", "")).strip() in version_family_ids
            and str(row.get("approval_status", "")).strip().casefold() != "approved"
        )
        if unapproved_family_count:
            errors.append(
                f"taxonomy version '{version_id}': {unapproved_family_count} "
                "product families are not approved"
            )
        version_class_ids = {
            str(row.get("class_id", "")).strip()
            for row in data.get("product_families", [])
            if str(row.get("family_id", "")).strip() in version_family_ids
        }
        unapproved_class_count = sum(
            1
            for row in data.get("product_classes", [])
            if str(row.get("class_id", "")).strip() in version_class_ids
            and str(row.get("approval_status", "")).strip().casefold() != "approved"
        )
        if unapproved_class_count:
            errors.append(
                f"taxonomy version '{version_id}': {unapproved_class_count} "
                "product classes are not approved"
            )

        primary_counts: dict[str, int] = {}
        for row in data.get("product_specialties", []):
            if str(row.get("version_id", "")).strip() != version_id:
                continue
            if str(row.get("is_primary", "")).strip().casefold() not in {
                "true",
                "yes",
                "1",
                "y",
            }:
                continue
            product_id = str(row.get("product_id", "")).strip()
            primary_counts[product_id] = primary_counts.get(product_id, 0) + 1
        duplicate_primaries = sum(1 for count in primary_counts.values() if count > 1)
        if duplicate_primaries:
            errors.append(
                f"taxonomy version '{version_id}': {duplicate_primaries} products "
                "have more than one primary specialty"
            )
        mapped_specialty_codes = {
            str(row.get("specialty_code", "")).strip()
            for row in data.get("product_specialties", [])
            if str(row.get("version_id", "")).strip() == version_id
        }
        inactive_specialty_count = sum(
            1
            for row in data.get("clinical_specialties", [])
            if str(row.get("specialty_code", "")).strip() in mapped_specialty_codes
            and str(row.get("active", "true")).strip().casefold()
            in {"false", "no", "0", "n"}
        )
        if inactive_specialty_count:
            errors.append(
                f"taxonomy version '{version_id}': {inactive_specialty_count} "
                "mapped clinical specialties are inactive"
            )

    if errors:
        preview = "\n- ".join(errors[:25])
        suffix = f"\n- ... and {len(errors) - 25} more" if len(errors) > 25 else ""
        raise ValueError(f"Catalog snapshot validation failed:\n- {preview}{suffix}")


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
