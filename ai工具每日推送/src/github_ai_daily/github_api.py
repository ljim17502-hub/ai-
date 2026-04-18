from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


def parse_github_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass
class Repository:
    full_name: str
    name: str
    html_url: str
    description: str
    stars: int
    forks: int
    watchers: int
    topics: list[str]
    homepage: str | None
    language: str | None
    license_name: str | None
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime
    default_branch: str
    readme: str = ""

    @property
    def owner(self) -> str:
        return self.full_name.split("/", maxsplit=1)[0]

    def as_text_blob(self) -> str:
        parts = [self.name, self.description, " ".join(self.topics), self.readme]
        return "\n".join(part for part in parts if part).lower()


class GitHubAPIError(RuntimeError):
    """Raised when the GitHub API returns an unexpected response."""


class GitHubClient:
    def __init__(self, token: str | None = None, api_base: str = "https://api.github.com") -> None:
        self.api_base = api_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": "github-ai-daily-push",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        acceptable_statuses: set[int] | None = None,
    ) -> requests.Response:
        url = f"{self.api_base}/{path.lstrip('/')}"
        response = self.session.request(method, url, params=params, timeout=30)
        acceptable = acceptable_statuses or {200}
        if response.status_code in acceptable:
            return response

        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            reset_at = response.headers.get("X-RateLimit-Reset", "unknown")
            raise GitHubAPIError(f"GitHub API rate limit exceeded. Reset at {reset_at}.")

        message = response.text[:400]
        raise GitHubAPIError(
            f"GitHub API request failed: {response.status_code} {response.reason}. {message}"
        )

    def search_repositories(self, query: str, per_page: int = 20) -> list[Repository]:
        response = self._request(
            "GET",
            "/search/repositories",
            params={"q": query, "sort": "updated", "order": "desc", "per_page": per_page},
        )
        items = response.json().get("items", [])
        time.sleep(0.3)
        return [self._parse_repository(item) for item in items]

    def fetch_readme(self, full_name: str) -> str:
        response = self._request(
            "GET",
            f"/repos/{full_name}/readme",
            acceptable_statuses={200, 404},
        )
        if response.status_code == 404:
            return ""

        payload = response.json()
        content = payload.get("content", "")
        if not content:
            return ""
        try:
            decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
        except ValueError:
            return ""
        time.sleep(0.15)
        return decoded[:12000]

    def _parse_repository(self, item: dict[str, Any]) -> Repository:
        license_info = item.get("license") or {}
        return Repository(
            full_name=item["full_name"],
            name=item["name"],
            html_url=item["html_url"],
            description=(item.get("description") or "").strip(),
            stars=int(item.get("stargazers_count", 0)),
            forks=int(item.get("forks_count", 0)),
            watchers=int(item.get("watchers_count", 0)),
            topics=item.get("topics") or [],
            homepage=item.get("homepage"),
            language=item.get("language"),
            license_name=license_info.get("spdx_id") or license_info.get("name"),
            created_at=parse_github_datetime(item["created_at"]),
            updated_at=parse_github_datetime(item["updated_at"]),
            pushed_at=parse_github_datetime(item["pushed_at"]),
            default_branch=item.get("default_branch") or "main",
        )
