from celery import Celery

from app.config import settings

celery_app = Celery(
    "business_review",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker_tasks"],
)

celery_app.conf.update(
    # Redis broker 默认 visibility_timeout 为 1 小时，超时即重投递、任务从头重跑并
    # 覆盖已有产物；长材料任务因此永远跑不完。置为 12 小时覆盖实际最长耗时
    broker_transport_options={"visibility_timeout": 43200},
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
