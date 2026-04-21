from celery import Celery
from app.core.config import build_redis_url

# Celery app
celery_app = Celery(
    "sociomed_tasks",
    broker=build_redis_url(db=0),
    backend=build_redis_url(db=1),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=60,          # prevent stuck tasks
    worker_prefetch_multiplier=1, # good for WhatsApp (one message at a time)
)
