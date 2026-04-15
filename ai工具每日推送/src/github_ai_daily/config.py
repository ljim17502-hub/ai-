from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    data_dir: Path = ROOT_DIR / "data"
    history_path: Path = ROOT_DIR / "data" / "history.json"
    report_path: Path = ROOT_DIR / "data" / "last_report.md"
    github_api_base: str = "https://api.github.com"
    github_token: str | None = os.getenv("GITHUB_TOKEN") or None
    feishu_webhook_url: str | None = os.getenv("FEISHU_WEBHOOK_URL") or None
    feishu_bot_secret: str | None = os.getenv("FEISHU_BOT_SECRET") or None
    timezone: str = os.getenv("TIMEZONE", "Asia/Shanghai")
    max_recommendations: int = int(os.getenv("MAX_RECOMMENDATIONS", "10"))
    github_search_days: int = int(os.getenv("GITHUB_SEARCH_DAYS", "240"))
    readme_fetch_limit: int = int(os.getenv("README_FETCH_LIMIT", "40"))
    search_page_size: int = int(os.getenv("SEARCH_PAGE_SIZE", "20"))

    def build_search_queries(self, today: date) -> list[str]:
        cutoff = today - timedelta(days=self.github_search_days)
        base_filters = (
            f"archived:false is:public mirror:false pushed:>={cutoff.isoformat()} stars:>=10"
        )
        return [
            f'("text-to-image" OR diffusion) {base_filters}',
            f'("image editing" OR inpainting OR upscaling OR segmentation) {base_filters}',
            f'("video generation" OR "text-to-video" OR "image-to-video") {base_filters}',
            f'("video editing" OR "frame interpolation" OR "video super resolution" OR denoise) {base_filters}',
            f'("vision language model" OR VLM OR "multimodal understanding") {base_filters}',
            f'(multimodal AND (image OR video OR vision)) {base_filters}',
            f'("digital human" OR "virtual human" OR "lip sync" OR "motion drive") {base_filters}',
            f'("3D generation" OR gaussian OR NeRF OR "4D generation") {base_filters}',
            f'((workflow OR agent OR pipeline) AND (image OR video OR multimodal)) {base_filters}',
            f'((training OR inference OR deployment OR acceleration) AND (diffusion OR VLM OR multimodal)) {base_filters}',
        ]
