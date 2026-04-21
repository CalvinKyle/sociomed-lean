# app/core/exchange_rates.py

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Base currency for all Google Sheets pricing
BASE_CURRENCY = "UGX"

# Daily exchange rates (update weekly, or fetch from API)
# Format: {target_currency: units_of_target_per_1_UGX}
EXCHANGE_RATES: Dict[str, float] = {
    "UGX": 1.0,        # Uganda Shilling (base)
    "KES": 0.029,      # Kenyan Shilling (1 UGX ≈ 0.029 KES, ~35 UGX per KES)
    "SSP": 0.34,       # South Sudanese Pound (for future)
    "RWF": 0.36,       # Rwandan Franc (for future)
    "CDF": 0.74,       # Congolese Franc (for future)
}

# Last updated: 2025-01-15
# Source: Google Finance / XE.com
# Update frequency: Weekly (matches your sync cadence)


def convert_price(amount_in_base: int, target_currency: str) -> int:
    """
    Convert a price from base currency (UGX) to target currency.
    
    Args:
        amount_in_base: Price in UGX (from Google Sheets)
        target_currency: Target currency code (KES, UGX, etc.)
    
    Returns:
        Converted price as integer (rounded)
    
    Example:
        >>> convert_price(1000, "KES")  # 1000 UGX → ~29 KES
        29
    """
    if target_currency not in EXCHANGE_RATES:
        logger.warning(f"Currency {target_currency} not supported, using base currency {BASE_CURRENCY}")
        return amount_in_base
    
    if target_currency == BASE_CURRENCY:
        return amount_in_base
    
    rate = EXCHANGE_RATES[target_currency]
    converted = int(round(amount_in_base * rate))
    
    return converted


def convert_price_tier(tier: Dict, target_currency: str) -> Dict:
    """
    Convert a single pricing tier to target currency.
    
    Args:
        tier: Dict with min_qty, max_qty, unit_price (in base currency)
        target_currency: Target currency code
    
    Returns:
        New tier dict with converted unit_price
    """
    return {
        **tier,
        "unit_price": convert_price(tier["unit_price"], target_currency)
    }


def convert_result_prices(result: Dict, target_currency: str) -> Dict:
    """
    Convert all prices in a search result to target currency.
    
    Args:
        result: Search result dict with 'pricing' list and 'default_price'
        target_currency: Target currency code
    
    Returns:
        New result dict with converted prices
    """
    converted_result = {**result}
    
    # Convert pricing tiers
    if "pricing" in result and result["pricing"]:
        converted_result["pricing"] = [
            convert_price_tier(tier, target_currency) 
            for tier in result["pricing"]
        ]
        # Update default_price from first converted tier
        converted_result["default_price"] = converted_result["pricing"][0]["unit_price"]
    
    elif "default_price" in result and result["default_price"]:
        converted_result["default_price"] = convert_price(result["default_price"], target_currency)
    
    return converted_result


# For manual exchange rate updates (weekly task):
def update_exchange_rates(new_rates: Dict[str, float]) -> None:
    """
    Update exchange rates (call this weekly with fresh rates from XE.com).
    In production, fetch from an API like exchangerate-api.com (free tier).
    
    Example:
        >>> update_exchange_rates({"KES": 0.030, "SSP": 0.35})
    """
    global EXCHANGE_RATES
    EXCHANGE_RATES.update(new_rates)
    logger.info(f"Exchange rates updated: {new_rates}")
