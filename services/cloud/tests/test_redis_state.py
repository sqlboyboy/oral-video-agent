from __future__ import annotations

from app.redis_state import RedisState


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.commands = []

    def lrem(self, *args):
        self.commands.append(("lrem", args))
        return self

    def rpush(self, *args):
        self.commands.append(("rpush", args))
        return self

    def hset(self, *args):
        self.commands.append(("hset", args))
        return self

    def hdel(self, *args):
        self.commands.append(("hdel", args))
        return self

    def expire(self, *args):
        self.commands.append(("expire", args))
        return self

    def execute(self):
        for name, args in self.commands:
            getattr(self.redis, name)(*args)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    def ping(self) -> bool:
        return True

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> bool:
        return True

    def lrem(self, key: str, count: int, value: str) -> int:
        items = self.lists.get(key, [])
        before = len(items)
        self.lists[key] = [item for item in items if item != value]
        return before - len(self.lists[key])

    def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def hset(self, key: str, field: str, value: str) -> int:
        self.hashes.setdefault(key, {})[field] = value
        return 1

    def hdel(self, key: str, field: str) -> int:
        return 1 if self.hashes.get(key, {}).pop(field, None) is not None else 0

    def hlen(self, key: str) -> int:
        return len(self.hashes.get(key, {}))

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


def _state() -> RedisState:
    state = RedisState("")
    state._client = FakeRedis()
    return state


def test_redis_state_rate_limit_blocks_after_limit():
    state = _state()

    assert state.allow_rate_limit(key="client:1", limit=2)
    assert state.allow_rate_limit(key="client:1", limit=2)
    assert not state.allow_rate_limit(key="client:1", limit=2)


def test_redis_state_tracks_queued_running_and_finished_jobs():
    state = _state()

    state.note_job_queued({"job_id": "job-1"})
    assert state.queue_snapshot()["queued_list_length"] == 1
    assert state.queue_snapshot()["tracked_jobs"] == 1

    state.note_job_running({"job_id": "job-1"}, worker_id="worker-1")
    assert state.queue_snapshot()["queued_list_length"] == 0

    state.note_job_finished({"job_id": "job-1", "status": "completed"})
    assert state.queue_snapshot()["tracked_jobs"] == 1
