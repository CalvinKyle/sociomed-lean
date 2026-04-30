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
