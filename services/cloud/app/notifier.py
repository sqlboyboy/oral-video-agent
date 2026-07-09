from __future__ import annotations

import json
import urllib.request


class WebhookNotifier:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url.strip()

    def send_text(self, content: str) -> bool:
        if not self.webhook_url:
            return False
        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
            },
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            return 200 <= response.status < 300
