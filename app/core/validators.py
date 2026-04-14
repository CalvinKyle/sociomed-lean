import re

# Validate and sanitize WhatsApp messages

def validate_whatsapp_message(message):
    """
    Validates the content of a WhatsApp message.
    Allows alphanumeric characters, spaces, and common punctuation.
    """
    return bool(re.match(r'^[\w .,?!]*(\s[\w .,?!]*)*$', message))

# Validate and sanitize product queries

def validate_product_query(query):
    """
    Validates product query strings to be alphanumeric and spaces.
    """
    return bool(re.match(r'^[\w ]+$', query))

# Validate quantities

def validate_quantity(quantity):
    """
    Validates that the quantity is a positive integer.
    """
    return isinstance(quantity, int) and quantity > 0

# Validate phone numbers

def validate_phone_number(phone):
    """
    Validates phone numbers in international format.
    Example: +1234567890 or 0123456789.
    """
    return bool(re.match(r'^(\+\d{1,3}[- ]?)?\d{10,15}$', phone))

# Validate facility names

def validate_facility_name(name):
    """
    Validates facility names to contain only alphanumeric characters and space.
    """
    return bool(re.match(r'^[\w ]+$', name))
