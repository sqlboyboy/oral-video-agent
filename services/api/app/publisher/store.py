import json
from pathlib import Path
from typing import Dict, List

from ..models import storage_dir
from .models import PublishJob, PublisherAccount


class PublisherStore:
    def __init__(self) -> None:
        self._accounts_path = storage_dir("publisher") / "accounts.json"
        self._jobs_path = storage_dir("publisher") / "jobs.json"
        self._accounts: Dict[str, PublisherAccount] = {}
        self._jobs: Dict[str, PublishJob] = {}
        self._load()

    def _load(self) -> None:
        if self._accounts_path.exists():
            data = json.loads(self._accounts_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                data = [data]
            self._accounts = {
                item["account_id"]: PublisherAccount.model_validate(item)
                for item in data
            }
        if self._jobs_path.exists():
            data = json.loads(self._jobs_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                data = [data]
            self._jobs = {
                item["job_id"]: PublishJob.model_validate(item)
                for item in data
            }

    def _save_accounts(self) -> None:
        self._accounts_path.parent.mkdir(parents=True, exist_ok=True)
        data = [item.model_dump(mode="json") for item in self._accounts.values()]
        self._accounts_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_jobs(self) -> None:
        self._jobs_path.parent.mkdir(parents=True, exist_ok=True)
        data = [item.model_dump(mode="json") for item in self._jobs.values()]
        self._jobs_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_accounts(self) -> List[PublisherAccount]:
        return list(self._accounts.values())

    def find_account_by_platform_and_nickname(
        self,
        platform: str,
        nickname: str,
    ) -> PublisherAccount | None:
        normalized = nickname.strip().casefold()
        for account in self._accounts.values():
            if account.platform.value != platform:
                continue
            if account.nickname.strip().casefold() == normalized:
                return account
        return None

    def list_jobs(self) -> List[PublishJob]:
        return list(self._jobs.values())

    def get_account(self, account_id: str) -> PublisherAccount:
        if account_id not in self._accounts:
            raise KeyError(account_id)
        return self._accounts[account_id]

    def get_job(self, job_id: str) -> PublishJob:
        if job_id not in self._jobs:
            raise KeyError(job_id)
        return self._jobs[job_id]

    def put_account(self, account: PublisherAccount) -> PublisherAccount:
        self._accounts[account.account_id] = account
        self._save_accounts()
        return account

    def put_job(self, job: PublishJob) -> PublishJob:
        self._jobs[job.job_id] = job
        self._save_jobs()
        return job

    def clear_all(self) -> None:
        self._accounts.clear()
        self._jobs.clear()
        self._save_accounts()
        self._save_jobs()

    def clear_for_tests(self) -> None:
        self.clear_all()


publisher_store = PublisherStore()
