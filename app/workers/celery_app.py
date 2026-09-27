from celery import Celery
from app.config import settings

celery_app = Celery(
    "nexusai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # Register the worker module so `celery -A app.workers.celery_app worker`
    # actually knows about nexusai.execute_task. Without this import the worker
    # starts with an EMPTY task registry and silently discards every dispatched
    # message: "Received unregistered task of type 'nexusai.execute_task'"
    # (tasks then sit in `pending` forever — the reported "execution crash").
    include=["app.workers.task_worker"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,   # one task at a time per worker process
    task_acks_late=True,            # ack only after task completes (safer on crash)
    task_reject_on_worker_lost=True,
)
