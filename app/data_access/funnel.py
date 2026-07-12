import logging
from typing import Any, Optional

from app.models.db import FunnelEvent, SessionLocal

logger = logging.getLogger(__name__)


def record_funnel_event(
    event_type: str,
    *,
    source: str,
    actor_id: Optional[str] = None,
    rfq_id: Optional[int] = None,
    data: Optional[dict[str, Any]] = None,
) -> None:
    """Persist analytics without allowing telemetry failure to break buyer flows."""
    db = SessionLocal()
    try:
        db.add(
            FunnelEvent(
                event_type=event_type,
                source=source,
                actor_id=actor_id,
                rfq_id=rfq_id,
                event_data=data or {},
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("funnel_event_persist_failed event_type=%s source=%s", event_type, source)
    finally:
        db.close()
