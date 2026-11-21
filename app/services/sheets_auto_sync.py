import asyncio
import logging
from dataclasses import asdict, dataclass
from time import monotonic
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.utils import log_audit_event
from sync_sheets_to_db import sync_sheets_to_db


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SheetsSyncExecution:
    status: str
    trigger: str
    duration_seconds: float
    version_id: int | None = None
    summary: dict[str, dict[str, int]] | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_sync_lock = asyncio.Lock()


async def run_sheets_sync(trigger: str) -> SheetsSyncExecution:
    """Run the canonical sync once without blocking the event loop or overlapping."""
    if _sync_lock.locked():
        result = SheetsSyncExecution(
            status="skipped",
            trigger=trigger,
            duration_seconds=0.0,
            summary={},
            reason="sync_already_running",
        )
        logger.warning("Google Sheets sync skipped because another run is active")
        log_audit_event("system", "sheets_sync_skipped", result.as_dict())
        return result

    async with _sync_lock:
        started = monotonic()
        try:
            sync_result = await asyncio.to_thread(sync_sheets_to_db)
        except (Exception, SystemExit) as exc:
            result = SheetsSyncExecution(
                status="failed",
                trigger=trigger,
                duration_seconds=round(monotonic() - started, 3),
                summary={},
                reason=str(exc) or type(exc).__name__,
            )
            logger.exception("Google Sheets sync failed")
            log_audit_event("system", "sheets_sync_failed", result.as_dict())
            return result

        result = SheetsSyncExecution(
            status="completed",
            trigger=trigger,
            duration_seconds=round(monotonic() - started, 3),
            version_id=sync_result.version_id,
            summary=sync_result.summary,
        )
        logger.info(
            "Google Sheets sync completed in %.3f seconds (version %s)",
            result.duration_seconds,
            result.version_id,
        )
        log_audit_event("system", "sheets_sync_completed", result.as_dict())
        return result


def start_sheets_sync_scheduler(interval_minutes: int) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_sheets_sync,
        trigger="interval",
        minutes=interval_minutes,
        kwargs={"trigger": "scheduled"},
        id="google-sheets-catalog-sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Google Sheets auto-sync scheduled every %d minutes", interval_minutes)
    return scheduler
