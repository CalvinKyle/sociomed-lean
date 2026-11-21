from typing import Dict, List

from app.core.cache import get_cached_data
from app.core.config import DEFAULT_CURRENCY, ENABLE_OPEN_DOCS, PUBLIC_BASE_URL, SUPPORT_EMAIL
from app.core.sheet_sync import split_multi_value_cell


CATEGORY_ALIASES = {
    "device": "Devices",
    "devices": "Devices",
}

SPECIALTY_ALIASES = {
    "cardiovascular": "Cardiology",
    "diagnostic imaging": "Radiology & Imaging",
    "laboratory diagnostics": "Laboratory",
    "laboratory medicine": "Laboratory",
    "radiology": "Radiology & Imaging",
    "radiology imaging": "Radiology & Imaging",
    "surgical instruments": "Surgery",
}

GENERIC_SPECIALTIES = {
    "consumables",
    "device",
    "devices",
    "equipment",
    "furniture",
    "imaging",
}

EQUIPMENT_SPECIALTY_PRIORITY = {
    "Laboratory": 0,
    "Nephrology": 1,
    "Cardiology": 2,
    "Radiology & Imaging": 3,
}


def _get_catalog_data() -> Dict:
    return get_cached_data()


def get_products() -> List[Dict]:
    return [product for product in _get_catalog_data().get("products", []) if product.get("active", True)]


def canonical_category(product: Dict) -> str:
    """Present one stable buyer category while source taxonomy is being refined."""
    raw_category = str(product.get("category", "")).strip()
    family_id = str(product.get("product_family_id", "")).strip().upper()
    product_name = str(product.get("name", "")).strip().lower()

    if "REAGENT" in family_id or "reagent" in product_name:
        return "Reagents"
    if family_id.startswith("FAM-INSTR-") or "INSTRUMENT" in family_id:
        return "Instruments"
    if "CONSUMABLE" in family_id and raw_category.casefold() == "imaging":
        return "Consumables"
    if "MONITOR" in family_id and raw_category.casefold() in {"equipment", "imaging"}:
        return "Devices"

    return CATEGORY_ALIASES.get(raw_category.casefold(), raw_category.title())


def get_categories() -> List[str]:
    if has_browse_menu():
        return [row["label"] for row in _menu_nodes("CATEGORY")]
    categories = {
        canonical_category(product)
        for product in get_products()
        if canonical_category(product)
    }
    return sorted(categories)


def get_aliases() -> List[Dict]:
    return list(_get_catalog_data().get("aliases", []))


def product_specialties(product: Dict) -> List[str]:
    specialties = []
    seen = set()
    for value in split_multi_value_cell(product.get("clinical_speciality")):
        normalized = value.replace("_", " ").strip().casefold()
        if not normalized or normalized in GENERIC_SPECIALTIES:
            continue
        display_name = SPECIALTY_ALIASES.get(normalized, normalized.title())
        if display_name.casefold() not in seen:
            specialties.append(display_name)
            seen.add(display_name.casefold())
    return specialties or ["General"]


def get_subcategories_by_category(category: str) -> List[str]:
    if has_browse_menu():
        parent = _category_node(category)
        return [row["label"] for row in _menu_nodes("SPECIALTY") if parent and row.get("parent_node_id") == parent["node_id"]]
    counts: Dict[str, int] = {}
    for product in get_products_by_category(category):
        for specialty in product_specialties(product):
            counts[specialty] = counts.get(specialty, 0) + 1
    category_clean = str(category or "").strip().casefold()
    return sorted(
        counts,
        key=lambda name: (
            EQUIPMENT_SPECIALTY_PRIORITY.get(name, 4)
            if category_clean == "equipment"
            else 0,
            name == "General",
            -counts[name],
            name.casefold(),
        ),
    )


def get_products_by_category(category: str, subcategory: str | None = None) -> List[Dict]:
    if has_browse_menu():
        node = _category_node(category)
        if subcategory and node:
            node = next((row for row in _menu_nodes("SPECIALTY") if row.get("parent_node_id") == node["node_id"] and row.get("label", "").casefold() == subcategory.strip().casefold()), None)
        if not node:
            return []
        curation = {row.get("family_id") or row.get("product_family_id"): row for row in _get_catalog_data().get("parent_products", [])}
        def matches(product):
            placement = curation.get(product.get("product_family_id"), product)
            category_id = placement.get("category_id") or product.get("category_id") or product.get("category")
            departments = split_multi_value_cell(placement.get("department") or product.get("clinical_speciality"))
            return (not node.get("category_id") or str(category_id or "").casefold() == str(node["category_id"]).casefold()) and (not node.get("department") or str(node["department"]).casefold() in [value.casefold() for value in departments])
        return sorted([product for product in get_products() if matches(product)], key=lambda product: str(product.get("name", "")).casefold())
    category_clean = str(category or "").strip().casefold()
    subcategory_clean = str(subcategory or "").strip().casefold()
    products = [
        product
        for product in get_products()
        if canonical_category(product).casefold() == category_clean
        and (
            not subcategory_clean
            or any(
                specialty.casefold() == subcategory_clean
                for specialty in product_specialties(product)
            )
        )
    ]
    return sorted(products, key=lambda product: str(product.get("name", "")).lower())


def get_config() -> Dict[str, str | bool]:
    return {
        "operating_model": "rfq_first",
        "default_currency": DEFAULT_CURRENCY,
        "public_base_url": PUBLIC_BASE_URL,
        "support_email": SUPPORT_EMAIL,
        "open_docs_enabled": ENABLE_OPEN_DOCS,
    }


def has_browse_menu() -> bool:
    return bool(_get_catalog_data().get("browse_menu"))


def _menu_nodes(node_type: str) -> List[Dict]:
    return sorted(
        [row for row in _get_catalog_data().get("browse_menu", []) if str(row.get("node_type", "")).upper() == node_type],
        key=lambda row: (row.get("page") or 0, row.get("position") or 0, row.get("node_id", "")),
    )


def _category_node(category: str):
    return next((row for row in _menu_nodes("CATEGORY") if str(row.get("label", "")).casefold() == category.strip().casefold()), None)
