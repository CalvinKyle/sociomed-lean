from typing import Dict, List

from app.core.cache import get_cached_data
from app.core.config import DEFAULT_CURRENCY, ENABLE_OPEN_DOCS, PUBLIC_BASE_URL, SUPPORT_EMAIL


def _get_catalog_data() -> Dict:
    return get_cached_data()


def get_products() -> List[Dict]:
    return list(_get_catalog_data().get("products", []))


def get_categories() -> List[str]:
    categories = {
        str(product.get("category", "")).strip()
        for product in get_products()
        if str(product.get("category", "")).strip()
    }
    return sorted(categories)


def get_aliases() -> List[Dict]:
    return list(_get_catalog_data().get("aliases", []))


def get_config() -> Dict[str, str | bool]:
    return {
        "default_currency": DEFAULT_CURRENCY,
        "public_base_url": PUBLIC_BASE_URL,
        "support_email": SUPPORT_EMAIL,
        "open_docs_enabled": ENABLE_OPEN_DOCS,
    }
