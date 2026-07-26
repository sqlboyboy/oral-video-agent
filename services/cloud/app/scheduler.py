from __future__ import annotations

import logging
import time

from .settings import settings
from .object_storage import object_storage
from .redis_state import RedisState
from .store import QueueStore


logger = logging.getLogger("oral_video_cloud.scheduler")
store = QueueStore(settings.database_path, database_url=settings.database_url)
redis_state = RedisState(settings.redis_url)


def run_once() -> dict[str, int]:
    stale_uploads = store.purge_stale_uploading_jobs(
        timeout_seconds=settings.uploading_job_timeout_seconds,
    )
    stale_upload_objects_deleted = 0
    for cos_key in stale_uploads["cos_keys"]:
        try:
            object_storage.delete_object(cos_key=cos_key)
            stale_upload_objects_deleted += 1
        except Exception:
            logger.exception("failed to delete stale upload object %s", cos_key)
    if stale_uploads["jobs"]:
        logger.warning(
            "purged stale uploading jobs: %s",
            stale_uploads["job_ids"],
        )
    timed_out_jobs = store.timeout_stale_queued_jobs(
        timeout_seconds=settings.queued_job_timeout_seconds,
    )
    for job in timed_out_jobs:
        redis_state.note_job_finished(job, status="timed_out")
    if timed_out_jobs:
        logger.warning("timed out stale queued jobs: %s", [job["job_id"] for job in timed_out_jobs])
    failed_jobs = store.fail_stale_running_jobs(
        timeout_seconds=settings.running_job_timeout_seconds,
        preprocess_timeout_seconds=settings.preprocess_running_job_timeout_seconds,
    )
    if failed_jobs:
        logger.warning("released stale running jobs: %s", [job["job_id"] for job in failed_jobs])
    expired_invalid_jobs = store.purge_expired_invalid_jobs(
        retention_seconds=settings.invalid_job_retention_seconds,
    )
    invalid_job_objects_deleted = 0
    for cos_key in expired_invalid_jobs["cos_keys"]:
        try:
            object_storage.delete_object(cos_key=cos_key)
            invalid_job_objects_deleted += 1
        except Exception:
            logger.exception("failed to delete invalid job object %s", cos_key)
    if expired_invalid_jobs["jobs"]:
        logger.info(
            "purged expired invalid jobs: %s",
            expired_invalid_jobs["job_ids"],
        )
    deleted_outputs = 0
    for asset in store.list_expired_output_assets(limit=100):
        try:
            object_storage.delete_object(cos_key=asset["cos_key"])
            store.mark_asset_deleted(asset_id=asset["asset_id"])
            deleted_outputs += 1
        except Exception:
            logger.exception("failed to delete expired output asset %s", asset["asset_id"])
    deleted_stale_inputs = 0
    for asset in store.list_stale_input_assets(
        older_than_hours=settings.object_storage_stale_input_cleanup_hours,
        limit=100,
    ):
        try:
            object_storage.delete_object(cos_key=asset["cos_key"])
            store.mark_asset_deleted(asset_id=asset["asset_id"])
            deleted_stale_inputs += 1
        except Exception:
            logger.exception("failed to delete stale input asset %s", asset["asset_id"])
    return {
        "stale_upload_jobs_purged": stale_uploads["jobs"],
        "stale_upload_objects_deleted": stale_upload_objects_deleted,
        "stale_queued_timed_out": len(timed_out_jobs),
        "stale_running_failed": len(failed_jobs),
        "expired_invalid_jobs_purged": expired_invalid_jobs["jobs"],
        "invalid_job_objects_deleted": invalid_job_objects_deleted,
        "expired_outputs_deleted": deleted_outputs,
        "stale_inputs_deleted": deleted_stale_inputs,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("scheduler started")
    while True:
        try:
            result = run_once()
            logger.info("scheduler tick: %s", result)
        except Exception:
            logger.exception("scheduler tick failed")
        time.sleep(max(5, settings.scheduler_interval_seconds))


if __name__ == "__main__":
    main()
