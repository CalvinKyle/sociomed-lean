"""Load editable, buyer-facing WhatsApp copy from one reviewed JSON file."""

from functools import lru_cache
import json
from pathlib import Path
from typing import Mapping


COPY_PATH = Path(__file__).resolve().parents[1] / "content" / "conversation_copy.json"


@lru_cache(maxsize=1)
def load_conversation_copy() -> Mapping[str, str]:
    with COPY_PATH.open(encoding="utf-8") as copy_file:
        payload = json.load(copy_file)

    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
    ):
        raise ValueError(f"Conversation copy must be a string-to-string JSON object: {COPY_PATH}")
    return payload


def conversation_message(key: str, **values: object) -> str:
    """Return a named buyer message and safely interpolate its documented fields."""
    try:
        template = load_conversation_copy()[key]
    except KeyError as exc:
        raise KeyError(f"Unknown conversation copy key: {key}") from exc

    try:
        return template.format(**values)
    except KeyError as exc:
        missing_field = exc.args[0]
        raise KeyError(f"Missing field '{missing_field}' for conversation copy key '{key}'") from exc


def clear_conversation_copy_cache() -> None:
    """Allow tests or an administrative reload to pick up an edited copy file."""
    load_conversation_copy.cache_clear()
