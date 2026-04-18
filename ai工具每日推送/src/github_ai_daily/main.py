from __future__ import annotations

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from github_ai_daily.config import Settings
from github_ai_daily.feishu import send_report
from github_ai_daily.github_api import GitHubAPIError, GitHubClient, Repository
from github_ai_daily.reporting import (
    format_report,
    load_history,
    save_history,
    select_recommendations,
    update_history,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and push a GitHub AI tool daily report.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate the report locally without sending it to Feishu or updating history.",
    )
    return parser.parse_args()


def rough_rank(repo: Repository, today) -> tuple[float, int]:
    days_since_push = max((today - repo.pushed_at.date()).days, 0)
    freshness = max(0, 180 - days_since_push)
    return (repo.stars * 1.5 + repo.forks * 0.4 + freshness, repo.stars)


def main() -> None:
    args = parse_args()
    settings = Settings()
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    client = GitHubClient(token=settings.github_token, api_base=settings.github_api_base)

    all_candidates: dict[str, Repository] = {}
    queries = settings.build_search_queries(today)
    page_size = settings.search_page_size
    readme_fetch_limit = settings.readme_fetch_limit
    if not settings.github_token:
        queries = queries[:6]
        page_size = min(page_size, 10)
        readme_fetch_limit = min(readme_fetch_limit, 12)

    for query in queries:
        try:
            search_results = client.search_repositories(query, per_page=page_size)
        except GitHubAPIError as exc:
            if "rate limit exceeded" in str(exc).lower() and all_candidates:
                break
            raise RuntimeError(
                "GitHub API 触发限流。请为本地预览配置 GITHUB_TOKEN，或等待限流窗口恢复后重试。"
            ) from exc

        for repo in search_results:
            existing = all_candidates.get(repo.full_name)
            if existing and existing.stars > repo.stars:
                continue
            all_candidates[repo.full_name] = repo

    rough_candidates = sorted(
        all_candidates.values(),
        key=lambda repo: rough_rank(repo, today=today),
        reverse=True,
    )

    for repo in rough_candidates[:readme_fetch_limit]:
        try:
            repo.readme = client.fetch_readme(repo.full_name)
        except GitHubAPIError as exc:
            if "rate limit exceeded" in str(exc).lower():
                break
            raise

    history = load_history(settings.history_path)
    recommendations = select_recommendations(
        rough_candidates,
        history,
        today=today,
        limit=settings.max_recommendations,
    )
    if not recommendations:
        raise RuntimeError("未筛选出可用项目，请检查搜索条件或 GitHub API 返回结果。")

    report = format_report(recommendations, today=today)
    settings.report_path.write_text(report, encoding="utf-8")

    if args.dry_run:
        return

    if not settings.feishu_webhook_url:
        raise RuntimeError("缺少 FEISHU_WEBHOOK_URL，无法推送到飞书。")

    send_report(
        settings.feishu_webhook_url,
        report,
        secret=settings.feishu_bot_secret,
        title=f"GitHub AI 工具日报 {today.isoformat()}",
    )

    updated_history = update_history(history, recommendations, today=today)
    save_history(settings.history_path, updated_history)


if __name__ == "__main__":
    main()
