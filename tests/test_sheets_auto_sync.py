import asyncio
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main as main_module
from app.api import routes
from app.core import auth
from app.services import sheets_auto_sync


def _admin_client(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)
    monkeypatch.setattr(auth, "API_KEY", "secret")
    return TestClient(app)


def test_scheduler_is_not_started_when_disabled(monkeypatch):
    starts = []
    monkeypatch.setattr(main_module, "SHEETS_AUTO_SYNC_ENABLED", False)
    monkeypatch.setattr(main_module, "validate_config", lambda: None)
    monkeypatch.setattr(
        main_module,
        "start_sheets_sync_scheduler",
        lambda interval: starts.append(interval),
    )

    with TestClient(main_module.app):
        assert main_module.app.state.sheets_sync_scheduler is None

    assert starts == []


def test_scheduler_registers_interval_job_and_starts(monkeypatch):
    calls = []

    class FakeScheduler:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def add_job(self, function, **kwargs):
            calls.append(("add_job", function, kwargs))

        def start(self):
            calls.append(("start",))

    monkeypatch.setattr(sheets_auto_sync, "AsyncIOScheduler", FakeScheduler)

    scheduler = sheets_auto_sync.start_sheets_sync_scheduler(1440)

    assert isinstance(scheduler, FakeScheduler)
    assert calls[0] == ("init", {"timezone": "UTC"})
    assert calls[1][0] == "add_job"
    assert calls[1][1] is sheets_auto_sync.run_sheets_sync
    assert calls[1][2]["minutes"] == 1440
    assert calls[1][2]["max_instances"] == 1
    assert calls[2] == ("start",)


def test_overlap_guard_prevents_concurrent_runs(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_sync():
        calls.append("run")
        started.set()
        assert release.wait(timeout=2)
        return SimpleNamespace(version_id=7, summary={"products": {"created": 1}})

    monkeypatch.setattr(sheets_auto_sync, "_sync_lock", asyncio.Lock())
    monkeypatch.setattr(sheets_auto_sync, "sync_sheets_to_db", fake_sync)
    monkeypatch.setattr(sheets_auto_sync, "log_audit_event", lambda *_args: None)

    async def scenario():
        first_task = asyncio.create_task(sheets_auto_sync.run_sheets_sync("scheduled"))
        ready = await asyncio.to_thread(started.wait, 2)
        assert ready
        second = await sheets_auto_sync.run_sheets_sync("manual")
        release.set()
        first = await first_task
        return first, second

    first, second = asyncio.run(scenario())

    assert calls == ["run"]
    assert first.status == "completed"
    assert second.status == "skipped"
    assert second.reason == "sync_already_running"


def test_manual_trigger_requires_api_key_and_returns_summary(monkeypatch):
    async def fake_run(trigger):
        return sheets_auto_sync.SheetsSyncExecution(
            status="completed",
            trigger=trigger,
            duration_seconds=1.25,
            version_id=9,
            summary={"products": {"unchanged": 10, "changed": 1, "created": 0, "skipped_invalid": 0}},
        )

    monkeypatch.setattr(routes, "run_sheets_sync", fake_run)
    client = _admin_client(monkeypatch)

    unauthorized = client.post("/api/admin/sync-sheets")
    response = client.post(
        "/api/admin/sync-sheets",
        headers={"X-API-Key": "secret"},
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["version_id"] == 9
    assert response.json()["summary"]["products"]["changed"] == 1


def test_failing_sync_is_caught_and_audited(monkeypatch):
    audits = []

    def fail_sync():
        raise RuntimeError("sheet unavailable")

    monkeypatch.setattr(sheets_auto_sync, "_sync_lock", asyncio.Lock())
    monkeypatch.setattr(sheets_auto_sync, "sync_sheets_to_db", fail_sync)
    monkeypatch.setattr(
        sheets_auto_sync,
        "log_audit_event",
        lambda actor, event, data: audits.append((actor, event, data)),
    )

    result = asyncio.run(sheets_auto_sync.run_sheets_sync("scheduled"))

    assert result.status == "failed"
    assert result.summary == {}
    assert result.duration_seconds >= 0
    assert audits[0][1] == "sheets_sync_failed"
    assert audits[0][2]["reason"] == "sheet unavailable"


def test_manual_trigger_returns_failure_without_raising(monkeypatch):
    async def fake_run(trigger):
        return sheets_auto_sync.SheetsSyncExecution(
            status="failed",
            trigger=trigger,
            duration_seconds=0.5,
            summary={},
            reason="sheet sync failed",
        )

    monkeypatch.setattr(routes, "run_sheets_sync", fake_run)
    client = _admin_client(monkeypatch)

    response = client.post(
        "/api/admin/sync-sheets",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 500
    assert response.json()["status"] == "failed"
    assert response.json()["reason"] == "sheet sync failed"
