from __future__ import annotations

import base64
import hashlib
import hmac
import time

import requests


class FeishuPushError(RuntimeError):
    """Raised when sending a message to Feishu fails."""


def build_signature(secret: str) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(digest).decode("utf-8")
    return timestamp, sign


def chunk_report(report: str, chunk_size: int = 3200) -> list[str]:
    sections = report.split("\n### ")
    chunks = []
    current = sections[0]

    for section in sections[1:]:
        candidate = f"{current}\n### {section}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        chunks.append(current.strip())
        current = f"### {section}"

    if current.strip():
        chunks.append(current.strip())
    return chunks


def send_report(
    webhook_url: str,
    report: str,
    *,
    secret: str | None = None,
    title: str = "GitHub AI 工具日报",
) -> None:
    session = requests.Session()
    for index, chunk in enumerate(chunk_report(report), start=1):
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "blue",
                    "title": {
                        "tag": "plain_text",
                        "content": title if index == 1 else f"{title}（续 {index}）",
                    },
                },
                "elements": [{"tag": "markdown", "content": chunk}],
            },
        }
        if secret:
            timestamp, sign = build_signature(secret)
            payload["timestamp"] = timestamp
            payload["sign"] = sign

        response = session.post(webhook_url, json=payload, timeout=20)
        if response.status_code != 200:
            raise FeishuPushError(
                f"Feishu webhook failed with {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        if data.get("code") not in (0, None):
            raise FeishuPushError(f"Feishu webhook rejected the message: {data}")
