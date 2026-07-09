from __future__ import annotations

import time
from typing import Any


class RedisState:
    def __init__(self, redis_url: str, *, prefix: str = "oral-video-cloud") -> None:
        self.redis_url = redis_url.strip()
        self.prefix = prefix
        self._client: Any | None = None
        self.last_error = ""
        if not self.redis_url:
            return
        try:
            import redis

            self._client = redis.Redis.from_url(self.redis_url, decode_responses=True)
        except Exception as exc:  # pragma: no cover - deployment configuration error
            self.last_error = str(exc)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def health(self) -> dict[str, Any]:
        if self._client is None:
            return {"enabled": False, "ok": False, "error": self.last_error}
        try:
            self._client.ping()
            return {"enabled": True, "ok": True, "error": ""}
        except Exception as exc:
            self.last_error = str(exc)
            return {"enabled": True, "ok": False, "error": self.last_error}

    def allow_rate_limit(self, *, key: str, limit: int, window_seconds: int = 60) -> bool:
        if self._client is None or limit <= 0:
            return True
        redis_key = self._key("rate", key, str(int(time.time() // window_seconds)))
        try:
            count = int(self._client.incr(redis_key))
            if count == 1:
                self._client.expire(redis_key, window_seconds + 2)
            return count <= limit
        except Exception as exc:
            self.last_error = str(exc)
            return True

    def note_job_queued(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return
        self._queue_write(job_id=job_id, status="queued", worker_id="")

    def note_job_running(self, job: dict[str, Any], *, worker_id: str) -> None:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return
        self._queue_write(job_id=job_id, status="running", worker_id=worker_id)

    def note_job_finished(self, job: dict[str, Any], *, status: str | None = None) -> None:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return
        self._queue_write(job_id=job_id, status=status or str(job.get("status") or ""), worker_id="")

    def queue_snapshot(self) -> dict[str, Any]:
        if self._client is None:
            return {"enabled": False}
        try:
            return {
                "enabled": True,
                "queued_list_length": int(self._client.llen(self._key("queue", "queued"))),
                "tracked_jobs": int(self._client.hlen(self._key("jobs", "status"))),
                "last_error": self.last_error,
            }
        except Exception as exc:
            self.last_error = str(exc)
            return {"enabled": True, "error": self.last_error}

    def _queue_write(self, *, job_id: str, status: str, worker_id: str) -> None:
        if self._client is None:
            return
        try:
            queued_key = self._key("queue", "queued")
            jobs_key = self._key("jobs", "status")
            worker_key = self._key("jobs", "worker")
            pipe = self._client.pipeline()
            pipe.lrem(queued_key, 0, job_id)
            if status == "queued":
                pipe.rpush(queued_key, job_id)
            pipe.hset(jobs_key, job_id, status)
            if worker_id:
                pipe.hset(worker_key, job_id, worker_id)
            else:
                pipe.hdel(worker_key, job_id)
            pipe.expire(queued_key, 7 * 24 * 3600)
            pipe.expire(jobs_key, 7 * 24 * 3600)
            pipe.expire(worker_key, 7 * 24 * 3600)
            pipe.execute()
        except Exception as exc:
            self.last_error = str(exc)

    def _key(self, *parts: str) -> str:
        return ":".join([self.prefix, *parts])
