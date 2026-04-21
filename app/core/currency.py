COUNTRY_CURRENCY = {
    "256": ("UGX", "Uganda Shilling"),
    "254": ("KES", "Kenyan Shilling"),
    "211": ("SSP", "South Sudanese Pound"),
    "250": ("RWF", "Rwandan Franc"),
    "243": ("CDF", "Congolese Franc"),
}

DEFAULT_CURRENCY = "UGX"

def get_currency_for_phone(phone: str) -> str:
    """Detect currency from E.164 phone number prefix."""
    phone = phone.lstrip("+")
    for prefix, (code, _) in COUNTRY_CURRENCY.items():
        if phone.startswith(prefix):
            return code
    return DEFAULT_CURRENCY


def format_price(amount: int, currency: str) -> str:
    """Format price with currency code. Keeps it readable on WhatsApp."""
    return f"{currency} {amount:,}"
