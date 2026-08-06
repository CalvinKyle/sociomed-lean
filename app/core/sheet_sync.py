import re
from typing import Dict, List


REQUIRED_SHEET_COLUMNS = {
    "products": {"product_id", "name", "category"},
    "vendors": {"vendor_id", "name", "phone", "email", "region"},
    "inventory": {"inventory_id", "product_id", "vendor_id", "brand", "uom", "stock_qty", "lead_time_days"},
    "pricing": {"pricing_id", "inventory_id", "min_qty", "max_qty", "unit_price"},
    "aliases": {"alias", "product_id"},
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
            item_type = str(normalized.get("item_type") or "generic").strip().lower()
            if item_type not in {"consumable", "equipment", "generic"}:
                raise ValueError(f"Invalid products.item_type '{item_type}'. Use consumable, equipment, or generic.")
            normalized["item_type"] = item_type
            for multi_value_key in ("clinical_speciality", "related_ids"):
                if multi_value_key in normalized:
                    normalized[multi_value_key] = normalize_multi_value_cell(normalized.get(multi_value_key))
        if tab_name == "vendors":
            normalized["phone"] = normalize_vendor_phone(normalized.get("phone", ""))
        normalized_rows.append(normalized)
    return normalized_rows


def prepare_sheet_data(data: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
    missing_tabs = sorted(set(REQUIRED_SHEET_COLUMNS) - set(data))
    if missing_tabs:
        raise ValueError(f"Google Sheet is missing required tabs: {', '.join(missing_tabs)}")
    normalized_data: Dict[str, List[Dict]] = {}
    for tab_name, rows in data.items():
        normalized_rows = normalize_sheet_rows(rows, tab_name)
        validate_required_columns(tab_name, normalized_rows)
        normalized_data[tab_name] = normalized_rows
    validate_sheet_relationships(normalized_data)
    validate_inventory_uom(normalized_data.get("inventory", []))
    validate_pricing_rows(normalized_data.get("pricing", []))
    return normalized_data


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


def _ids(rows: List[Dict], field_name: str, tab_name: str) -> set[str]:
    values = [str(row.get(field_name) or "").strip() for row in rows]
    missing_rows = [index + 2 for index, value in enumerate(values) if not value]
    if missing_rows:
        raise ValueError(f"{tab_name}.{field_name} is blank on row(s): {missing_rows}")
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"{tab_name}.{field_name} contains duplicate IDs: {', '.join(duplicates)}")
    return set(values)


def validate_sheet_relationships(data: Dict[str, List[Dict]]) -> None:
    product_ids = _ids(data.get("products", []), "product_id", "products")
    vendor_ids = _ids(data.get("vendors", []), "vendor_id", "vendors")
    inventory_ids = _ids(data.get("inventory", []), "inventory_id", "inventory")
    _ids(data.get("pricing", []), "pricing_id", "pricing")

    errors: list[str] = []
    for row_number, row in enumerate(data.get("inventory", []), start=2):
        if str(row.get("product_id") or "").strip() not in product_ids:
            errors.append(f"inventory row {row_number} references an unknown product_id")
        if str(row.get("vendor_id") or "").strip() not in vendor_ids:
            errors.append(f"inventory row {row_number} references an unknown vendor_id")
    for row_number, row in enumerate(data.get("pricing", []), start=2):
        if str(row.get("inventory_id") or "").strip() not in inventory_ids:
            errors.append(f"pricing row {row_number} references an unknown inventory_id")
    for row_number, row in enumerate(data.get("aliases", []), start=2):
        if str(row.get("product_id") or "").strip() not in product_ids:
            errors.append(f"aliases row {row_number} references an unknown product_id")
    for row_number, product in enumerate(data.get("products", []), start=2):
        unknown_related = [
            related_id
            for related_id in split_multi_value_cell(product.get("related_ids"))
            if related_id not in product_ids
        ]
        if unknown_related:
            errors.append(
                f"products row {row_number} references unknown related_ids: {', '.join(unknown_related)}"
            )
    if errors:
        raise ValueError("Sheet relationship validation failed: " + "; ".join(errors))


def validate_inventory_uom(inventory_rows: List[Dict]) -> None:
    missing_rows = [
        index + 2
        for index, row in enumerate(inventory_rows)
        if not str(row.get("uom") or "").strip()
    ]
    if missing_rows:
        raise ValueError(f"inventory.uom is required on row(s): {missing_rows}")


def _sheet_int(value, field_name: str, row_number: int, *, allow_blank: bool = False) -> int | None:
    if value in (None, "") and allow_blank:
        return None
    try:
        parsed = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"pricing row {row_number} has invalid {field_name}") from None
    return parsed


def validate_pricing_rows(pricing_rows: List[Dict]) -> None:
    from app.services.pricing import validate_pricing_tiers

    by_inventory: dict[str, list[dict]] = {}
    for row_number, row in enumerate(pricing_rows, start=2):
        normalized = {
            **row,
            "min_qty": _sheet_int(row.get("min_qty"), "min_qty", row_number),
            "max_qty": _sheet_int(row.get("max_qty"), "max_qty", row_number, allow_blank=True),
            "unit_price": _sheet_int(row.get("unit_price"), "unit_price", row_number),
        }
        by_inventory.setdefault(str(row.get("inventory_id") or "").strip(), []).append(normalized)
        row.update(normalized)

    errors = []
    for inventory_id, tiers in sorted(by_inventory.items()):
        validation = validate_pricing_tiers(tiers)
        if not validation.valid:
            errors.append(f"{inventory_id}: {validation.reason_code} ({validation.detail})")
    if errors:
        raise ValueError("Pricing tier validation failed: " + "; ".join(errors))
