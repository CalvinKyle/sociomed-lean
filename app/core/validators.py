import re

from app.core.states import is_valid_state


MESSAGE_TEXT_PATTERN = re.compile(r"^[\w\s.,?!/+():&%-]{1,1000}$")
PHONE_PATTERN = re.compile(r"^\+\d{10,15}$")


def validate_whatsapp_message(message):
    return isinstance(message, str) and bool(message.strip()) and len(message.strip()) <= 1000


def validate_product_query(query):
    return isinstance(query, str) and len(query.strip()) >= 2 and bool(MESSAGE_TEXT_PATTERN.match(query.strip()))


def validate_quantity(quantity):
    return isinstance(quantity, int) and quantity > 0


def validate_phone_number(phone):
    return isinstance(phone, str) and bool(PHONE_PATTERN.match(phone.strip()))


def validate_facility_name(name):
    return isinstance(name, str) and 2 <= len(name.strip()) <= 160


def validate_delivery_location(location):
    return isinstance(location, str) and 2 <= len(location.strip()) <= 200


def validate_product_exists(product_id, products):
    return any(product.get("product_id") == product_id for product in products)


def validate_state(state):
    return is_valid_state(state)
