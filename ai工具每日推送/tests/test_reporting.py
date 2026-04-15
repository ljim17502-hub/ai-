from __future__ import annotations

import unittest
from datetime import datetime, timezone

from github_ai_daily.github_api import Repository
from github_ai_daily.reporting import detect_directions, detect_revisit, extract_tags


def build_repo(**overrides) -> Repository:
    now = datetime(2026, 4, 15, tzinfo=timezone.utc)
    payload = {
        "full_name": "demo/project",
        "name": "project",
        "html_url": "https://github.com/demo/project",
        "description": "A multimodal video generation workflow toolkit",
        "stars": 1200,
        "forks": 120,
        "watchers": 1200,
        "topics": ["multimodal", "video-generation", "workflow"],
        "homepage": None,
        "language": "Python",
        "license_name": "MIT",
        "created_at": now,
        "updated_at": now,
        "pushed_at": now,
        "default_branch": "main",
        "readme": "Supports text-to-video, image-to-video and workflow orchestration with Gradio demo.",
    }
    payload.update(overrides)
    return Repository(**payload)


class ReportingTests(unittest.TestCase):
    def test_detect_directions(self) -> None:
        repo = build_repo()
        directions = detect_directions(repo)
        self.assertIn("视频", directions)
        self.assertIn("多模态理解", directions)
        self.assertIn("生产工作流", directions)

    def test_extract_tags(self) -> None:
        repo = build_repo()
        tags = extract_tags(repo)
        self.assertIn("workflow", tags)
        self.assertIn("文生视频".lower(), tags)
        self.assertIn("python", tags)

    def test_detect_revisit_when_star_growth_is_significant(self) -> None:
        repo = build_repo(stars=1500)
        history = {
            "recommended": {
                "demo/project": {
                    "last_recommended_at": "2026-03-20",
                    "stars": 1200,
                    "forks": 100,
                    "pushed_at": "2026-03-20T00:00:00+00:00",
                }
            }
        }
        revisit = detect_revisit(repo, history, today=datetime(2026, 4, 15).date())
        self.assertTrue(revisit["is_revisit"])
        self.assertFalse(revisit["skip"])


if __name__ == "__main__":
    unittest.main()
