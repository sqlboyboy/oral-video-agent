from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .settings import settings


class EmailSender(Protocol):
    def send_login_code(self, *, email: str, code: str, ttl_minutes: int) -> None:
        ...


class ConsoleEmailSender:
    def send_login_code(self, *, email: str, code: str, ttl_minutes: int) -> None:
        print(
            f"[cloud-email] login code for {email}: {code} "
            f"(valid {ttl_minutes} minutes)",
            file=sys.stderr,
        )


@dataclass(frozen=True)
class TencentSesEmailSender:
    secret_id: str
    secret_key: str
    region: str
    from_email: str
    template_id: str
    subject: str = "杰速口播邮箱验证码"

    service: str = "ses"
    host: str = "ses.tencentcloudapi.com"
    version: str = "2020-10-02"

    def send_login_code(self, *, email: str, code: str, ttl_minutes: int) -> None:
        if not all(
            [
                self.secret_id,
                self.secret_key,
                self.region,
                self.from_email,
                self.template_id,
                self.subject,
            ]
        ):
            raise RuntimeError("Tencent SES email provider is not fully configured")
        payload = {
            "FromEmailAddress": self.from_email,
            "Destination": [email],
            "Subject": self.subject,
            "Template": {
                "TemplateID": int(self.template_id),
                "TemplateData": json.dumps(
                    {"code": code, "ttl_minutes": ttl_minutes},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        }
        self._post(action="SendEmail", payload=payload)

    def _post(self, *, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        timestamp = int(dt.datetime.now(dt.timezone.utc).timestamp())
        date = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime("%Y-%m-%d")
        authorization = self._authorization(
            action=action,
            body=body,
            timestamp=timestamp,
            date=date,
        )
        request = urllib.request.Request(
            f"https://{self.host}",
            data=body.encode("utf-8"),
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json; charset=utf-8",
                "Host": self.host,
                "X-TC-Action": action,
                "X-TC-Region": self.region,
                "X-TC-Timestamp": str(timestamp),
                "X-TC-Version": self.version,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Tencent SES {action} failed: {exc.code} {detail}") from exc
        result = json.loads(raw) if raw else {}
        response_body = result.get("Response") if isinstance(result, dict) else None
        response_body = response_body if isinstance(response_body, dict) else {}
        error = response_body.get("Error")
        if isinstance(error, dict):
            code = str(error.get("Code") or "UnknownError")
            message = str(error.get("Message") or "Tencent SES request failed")
            request_id = str(response_body.get("RequestId") or "")
            suffix = f" (RequestId: {request_id})" if request_id else ""
            raise RuntimeError(f"Tencent SES {action} failed: {code}: {message}{suffix}")
        if action == "SendEmail" and not response_body.get("MessageId"):
            request_id = str(response_body.get("RequestId") or "")
            suffix = f" (RequestId: {request_id})" if request_id else ""
            raise RuntimeError(
                f"Tencent SES SendEmail failed: response has no MessageId{suffix}"
            )
        return result

    def _authorization(
        self,
        *,
        action: str,
        body: str,
        timestamp: int,
        date: str,
    ) -> str:
        algorithm = "TC3-HMAC-SHA256"
        canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{self.host}\n"
        signed_headers = "content-type;host"
        hashed_payload = hashlib.sha256(body.encode("utf-8")).hexdigest()
        canonical_request = "\n".join(
            [
                "POST",
                "/",
                "",
                canonical_headers,
                signed_headers,
                hashed_payload,
            ]
        )
        credential_scope = f"{date}/{self.service}/tc3_request"
        string_to_sign = "\n".join(
            [
                algorithm,
                str(timestamp),
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        secret_date = _hmac_sha256(("TC3" + self.secret_key).encode("utf-8"), date)
        secret_service = _hmac_sha256(secret_date, self.service)
        secret_signing = _hmac_sha256(secret_service, "tc3_request")
        signature = hmac.new(
            secret_signing,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return (
            f"{algorithm} Credential={self.secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )


def _hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def create_email_sender() -> EmailSender:
    if settings.email_provider == "tencent-ses":
        return TencentSesEmailSender(
            secret_id=settings.tencentcloud_secret_id,
            secret_key=settings.tencentcloud_secret_key,
            region=settings.ses_region,
            from_email=settings.ses_from_email,
            template_id=settings.ses_login_template_id,
            subject=settings.ses_login_subject,
        )
    return ConsoleEmailSender()
