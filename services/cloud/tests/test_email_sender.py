import json

import pytest

from app.email_sender import TencentSesEmailSender


class _Response:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._body


def _sender() -> TencentSesEmailSender:
    return TencentSesEmailSender(
        secret_id="test-id",
        secret_key="test-key",
        region="ap-guangzhou",
        from_email="noreply@example.com",
        template_id="123",
    )


def test_send_email_accepts_message_id(monkeypatch):
    sent_payload = {}

    def _urlopen(request, **_kwargs):
        sent_payload.update(json.loads(request.data.decode("utf-8")))
        return _Response(
            {"Response": {"MessageId": "message-1", "RequestId": "request-1"}}
        )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        _urlopen,
    )

    _sender().send_login_code(email="user@example.com", code="123456", ttl_minutes=10)
    assert sent_payload["Subject"] == "杰速口播邮箱验证码"


def test_send_email_raises_business_error_from_http_200(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {
                "Response": {
                    "Error": {
                        "Code": "AuthFailure.UnauthorizedOperation",
                        "Message": "resource has no permission",
                    },
                    "RequestId": "request-2",
                }
            }
        ),
    )

    with pytest.raises(RuntimeError, match="UnauthorizedOperation"):
        _sender().send_login_code(
            email="user@example.com", code="123456", ttl_minutes=10
        )
