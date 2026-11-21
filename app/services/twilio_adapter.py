from typing import Mapping, Optional


def _normalize_twilio_sender(sender: str) -> str:
    if sender.lower().startswith("whatsapp:"):
        return sender.split(":", 1)[1]
    return sender


def _twilio_media_message_type(content_type: str) -> str:
    normalized = content_type.lower()
    if normalized.startswith("image/"):
        return "image"
    if normalized.startswith("audio/"):
        return "audio"
    if normalized.startswith("video/"):
        return "video"
    if normalized.startswith("application/") or normalized.startswith("text/"):
        return "document"
    return "media"


def extract_twilio_message(form_data: Mapping[str, str]) -> Optional[dict]:
    """Translate a Twilio Messaging webhook into the app's internal message shape."""
    message_id = form_data.get("MessageSid") or form_data.get("SmsMessageSid")
    sender = form_data.get("From")
    if not message_id or not sender:
        return None

    message = {
        "id": message_id,
        "from": _normalize_twilio_sender(sender),
    }

    latitude = form_data.get("Latitude")
    longitude = form_data.get("Longitude")
    if latitude and longitude:
        message.update(
            {
                "type": "location",
                "location": {"latitude": latitude, "longitude": longitude},
            }
        )
        return message

    body = form_data.get("Body", "")
    if body.strip():
        message.update({"type": "text", "text": {"body": body}})
        return message

    try:
        media_count = int(form_data.get("NumMedia", "0") or "0")
    except ValueError:
        media_count = 0

    if media_count > 0:
        message_type = _twilio_media_message_type(form_data.get("MediaContentType0", ""))
        message.update(
            {
                "type": message_type,
                message_type: {
                    "url": form_data.get("MediaUrl0"),
                    "content_type": form_data.get("MediaContentType0"),
                },
            }
        )
        return message

    message["type"] = "message"
    return message
