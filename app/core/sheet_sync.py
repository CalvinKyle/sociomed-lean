import re
from typing import Dict, List


REQUIRED_SHEET_COLUMNS = {
    "products": {"product_id", "name", "category"},
    "vendors": {"vendor_id", "name", "phone", "email", "region"},
    "inventory": {"inventory_id", "product_id", "vendor_id", "brand", "uom", "stock_qty", "lead_time_days"},
    "pricing": {"pricing_id", "inventory_id", "min_qty", "max_qty", "unit_price"},
    "aliases": {"alias", "product_id"},
}

REQUIRED_ROW_VALUES = {
    "products": ("product_id", "name", "category"),
    "vendors": ("vendor_id", "name"),
    "inventory": ("inventory_id", "product_id", "vendor_id"),
    "pricing": ("pricing_id", "inventory_id", "min_qty", "unit_price"),
    "aliases": ("alias", "product_id"),
}
PRIMARY_KEYS = {
    "products": "product_id",
    "vendors": "vendor_id",
    "inventory": "inventory_id",
    "pricing": "pricing_id",
}

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
