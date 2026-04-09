"""
WhatsAppMessenger — thin wrapper around the Meta Cloud API v19+.
Handles text, interactive list/button messages, and document sends.
"""

import logging
import requests
from typing import Union

logger = logging.getLogger(__name__)


class WhatsAppMessenger:
    def __init__(self, token: str, phone_id: str, api_version: str = "v19.0"):
        self.token = token
        self.phone_id = phone_id
        self.base_url = f"https://graph.facebook.com/{api_version}/{phone_id}/messages"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def send(self, recipient: str, message: Union[str, dict]) -> bool:
        """
        Send a message. Accepts:
          - str  → plain text message
          - dict with type="interactive" → list or button message
          - dict with type="document"   → file/PDF message
        """
        payload = {"messaging_product": "whatsapp", "to": recipient}

        if isinstance(message, str):
            payload["type"] = "text"
            payload["text"] = {"body": message, "preview_url": False}
        elif isinstance(message, dict):
            payload.update(message)
        else:
            logger.error(f"Unknown message type: {type(message)}")
            return False

        try:
            resp = requests.post(self.base_url, headers=self.headers, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.error(f"WhatsApp API {resp.status_code}: {resp.text[:200]}")
                return False
            return True
        except requests.RequestException as e:
            logger.error(f"WhatsApp send failed: {e}")
            return False
