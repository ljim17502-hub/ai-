from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from github_ai_daily.github_api import Repository


KEYWORD_GROUPS = {
    "图片": [
        "text-to-image",
        "image generation",
        "image editing",
        "image-to-image",
        "inpainting",
        "upscaling",
        "super-resolution",
        "segmentation",
        "matting",
        "style transfer",
    ],
    "视频": [
        "text-to-video",
        "image-to-video",
        "video generation",
        "video editing",
        "frame interpolation",
        "video super resolution",
        "lipsync",
        "lip sync",
        "motion",
        "avatar",
        "video understanding",
    ],
    "多模态理解": [
        "multimodal",
        "vision language",
        "vlm",
        "vla",
        "retrieval",
        "cross-modal",
        "grounding",
        "ocr",
        "document understanding",
    ],
    "生产工作流": [
        "workflow",
        "agent",
        "automation",
        "pipeline",
        "studio",
        "comfyui",
        "webui",
        "orchestration",
    ],
    "模型训练 / 推理 / 部署": [
        "training",
        "finetune",
        "inference",
        "deployment",
        "serving",
        "accelerat",
        "quantization",
        "tensorrt",
        "vllm",
    ],
    "3D/4D": ["3d", "4d", "gaussian", "nerf", "mesh", "avatar"],
}


CAPABILITY_MAP = {
    "文生图": ["text-to-image", "txt2img", "diffusion"],
    "图生图": ["image-to-image", "img2img"],
    "图像编辑 / 修复": ["image editing", "inpainting", "restoration"],
    "超分辨率": ["upscaling", "super-resolution", "super resolution"],
    "抠图 / 分割": ["segmentation", "matting", "mask"],
    "风格迁移": ["style transfer", "style"],
    "文生视频": ["text-to-video", "video generation"],
    "图生视频": ["image-to-video"],
    "视频编辑": ["video editing", "editing"],
    "补帧": ["frame interpolation"],
    "视频超分": ["video super resolution"],
    "视频去噪": ["video denoise", "denoise"],
    "VLM / 视觉语言理解": ["vision language", "vision-language", "vlm", "llava"],
    "图文/多模态检索": ["retrieval", "search"],
    "工作流 / Agent": ["workflow", "agent", "pipeline", "comfyui"],
    "训练 / 微调": ["training", "finetune", "fine-tuning"],
    "推理 / 部署": ["inference", "deployment", "serving"],
    "加速 / 量化": ["accelerat", "quantization", "tensorrt", "onnx"],
    "数字人 / 虚拟人": ["digital human", "virtual human", "avatar"],
    "动作驱动 / 口型同步": ["motion", "lip sync", "lipsync"],
    "3D/4D 生成": ["3d", "4d", "gaussian", "nerf", "mesh"],
}


PERMISSIVE_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0"}
COPYLEFT_LICENSES = {"GPL-3.0", "AGPL-3.0", "LGPL-3.0", "GPL-2.0", "LGPL-2.1"}


@dataclass
class Recommendation:
    repo: Repository
    score: float
    directions: list[str]
    tags: list[str]
    is_revisit: bool
    revisit_reason: str | None
    overview: str
    detail: str
    recommendation_reason: str
    usage_barrier: str
    maturity: str
    commercial_reference: str
    demo_info: str
    paper_info: str


def load_history(path: Path) -> dict:
    if not path.exists():
        return {"recommended": {}, "reports": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_history(path: Path, history: dict) -> None:
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def select_recommendations(
    repos: Iterable[Repository],
    history: dict,
    *,
    today: date,
    limit: int = 10,
) -> list[Recommendation]:
    ranked = []
    for repo in repos:
        score = score_repository(repo, today=today)
        if score < 14:
            continue
        revisit_state = detect_revisit(repo, history, today=today)
        if revisit_state["skip"]:
            continue
        recommendation = build_recommendation(
            repo,
            today=today,
            score=score + revisit_state["bonus"],
            is_revisit=revisit_state["is_revisit"],
            revisit_reason=revisit_state["reason"],
        )
        ranked.append(recommendation)

    ranked.sort(key=lambda item: item.score, reverse=True)

    chosen = ranked[:limit]
    if len(chosen) < limit:
        fallback = []
        seen = {item.repo.full_name for item in chosen}
        for repo in repos:
            if repo.full_name in seen:
                continue
            revisit_state = detect_revisit(repo, history, today=today)
            if revisit_state["skip"]:
                continue
            fallback.append(
                build_recommendation(
                    repo,
                    today=today,
                    score=score_repository(repo, today=today),
                    is_revisit=revisit_state["is_revisit"],
                    revisit_reason=revisit_state["reason"],
                )
            )
        fallback.sort(key=lambda item: item.score, reverse=True)
        for item in fallback:
            if len(chosen) >= limit:
                break
            chosen.append(item)
    return chosen


def score_repository(repo: Repository, *, today: date) -> float:
    blob = repo.as_text_blob()
    relevance = 0.0
    for keywords in KEYWORD_GROUPS.values():
        matches = sum(1 for keyword in keywords if keyword in blob)
        relevance += min(matches * 1.6, 6.0)

    directions = detect_directions(repo)
    if len(directions) >= 2:
        relevance += 2.0
    if "生产工作流" in directions and "模型训练 / 推理 / 部署" in directions:
        relevance += 2.0

    days_since_push = max((today - repo.pushed_at.date()).days, 0)
    activity = max(0.0, 16.0 - min(days_since_push, 120) / 8)

    community = min(18.0, math.log10(repo.stars + 1) * 6.5 + math.log10(repo.forks + 1) * 2.2)
    freshness = 4.0 if (today - repo.created_at.date()).days <= 180 and repo.stars >= 50 else 0.0
    production = score_production_signals(repo)
    readme_quality = 3.0 if len(repo.readme) >= 800 else 1.0 if len(repo.readme) >= 200 else 0.0

    return relevance + activity + community + freshness + production + readme_quality


def score_production_signals(repo: Repository) -> float:
    blob = repo.as_text_blob()
    score = 0.0
    markers = [
        "docker",
        "api",
        "sdk",
        "gradio",
        "streamlit",
        "huggingface",
        "demo",
        "serving",
        "workflow",
        "deploy",
    ]
    score += min(6.0, sum(1.2 for marker in markers if marker in blob))
    if repo.homepage:
        score += 1.0
    return score


def detect_revisit(repo: Repository, history: dict, *, today: date) -> dict[str, object]:
    previous = history.get("recommended", {}).get(repo.full_name)
    if not previous:
        return {"skip": False, "is_revisit": False, "reason": None, "bonus": 0.0}

    previous_stars = int(previous.get("stars", 0))
    last_recommended_at = datetime.fromisoformat(previous["last_recommended_at"]).date()
    days_since_last = (today - last_recommended_at).days
    star_delta = repo.stars - previous_stars

    star_threshold = max(100, int(previous_stars * 0.15))
    if days_since_last >= 14 and star_delta >= star_threshold:
        return {
            "skip": False,
            "is_revisit": True,
            "reason": f"回访项目：较上次新增 {star_delta} Star，社区热度有明显抬升。",
            "bonus": 2.0,
        }

    pushed_at_before = previous.get("pushed_at")
    if pushed_at_before and days_since_last >= 21:
        previous_pushed_at = datetime.fromisoformat(pushed_at_before.replace("Z", "+00:00")).date()
        if repo.pushed_at.date() > previous_pushed_at and star_delta >= max(40, int(previous_stars * 0.05)):
            return {
                "skip": False,
                "is_revisit": True,
                "reason": "回访项目：最近仍在持续更新，且社区关注度继续上升。",
                "bonus": 1.5,
            }

    return {"skip": True, "is_revisit": False, "reason": None, "bonus": -100.0}


def build_recommendation(
    repo: Repository,
    *,
    today: date,
    score: float,
    is_revisit: bool,
    revisit_reason: str | None,
) -> Recommendation:
    directions = detect_directions(repo)
    tags = extract_tags(repo)
    capabilities = detect_capabilities(repo)
    overview = build_overview(repo, capabilities, directions)
    detail = build_detail(repo, capabilities, directions)
    recommendation_reason = build_recommendation_reason(repo, directions, capabilities, today=today)
    usage_barrier = assess_usage_barrier(repo)
    maturity = assess_maturity(repo)
    commercial_reference = assess_commercial_reference(repo)
    demo_info = detect_demo_info(repo)
    paper_info = detect_paper_info(repo)
    return Recommendation(
        repo=repo,
        score=score,
        directions=directions,
        tags=tags,
        is_revisit=is_revisit,
        revisit_reason=revisit_reason,
        overview=overview,
        detail=detail,
        recommendation_reason=recommendation_reason,
        usage_barrier=usage_barrier,
        maturity=maturity,
        commercial_reference=commercial_reference,
        demo_info=demo_info,
        paper_info=paper_info,
    )


def detect_directions(repo: Repository) -> list[str]:
    blob = repo.as_text_blob()
    directions: list[str] = []
    for direction, keywords in KEYWORD_GROUPS.items():
        if any(keyword in blob for keyword in keywords):
            directions.append(direction)
    if not directions:
        directions.append("多模态理解")
    return directions


def extract_tags(repo: Repository) -> list[str]:
    blob = repo.as_text_blob()
    tags = list(repo.topics)
    for capability, keywords in CAPABILITY_MAP.items():
        if any(keyword in blob for keyword in keywords):
            tags.append(capability.lower())
    if repo.language:
        tags.append(repo.language.lower())

    deduped = []
    seen = set()
    for tag in tags:
        normalized = tag.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped[:8]


def detect_capabilities(repo: Repository) -> list[str]:
    blob = repo.as_text_blob()
    matched = []
    for capability, keywords in CAPABILITY_MAP.items():
        if any(keyword in blob for keyword in keywords):
            matched.append(capability)
    if not matched:
        matched.append("多模态工具链")
    return matched[:5]


def build_overview(repo: Repository, capabilities: list[str], directions: list[str]) -> str:
    primary = " / ".join(capabilities[:2])
    description = clean_sentence(repo.description)
    if description:
        return f"一个偏 {primary} 的开源项目，核心定位是：{description}"
    return f"一个偏 {primary} 的开源项目，适合关注 {'、'.join(directions[:2])} 方向的最新能力演进。"


def build_detail(repo: Repository, capabilities: list[str], directions: list[str]) -> str:
    use_case = build_use_case(directions, capabilities)
    readme_summary = summarize_readme(repo.readme)
    sentences = [
        f"从 README 和主题信息看，它主要覆盖 {', '.join(capabilities[:3])} 等能力。",
        f"更适合用在 {use_case} 这类场景，尤其适合需要把模型能力和实际生产链路接起来的团队。",
    ]
    if readme_summary:
        sentences.append(readme_summary)
    return " ".join(sentences[:3])


def build_use_case(directions: list[str], capabilities: list[str]) -> str:
    if "视频" in directions:
        return "视频生成、视频增强、数字人或口型同步"
    if "图片" in directions:
        return "图像生成、修复、超分、分割或风格化处理"
    if "多模态理解" in directions:
        return "图文/视频理解、检索和视觉语言应用"
    if "模型训练 / 推理 / 部署" in directions:
        return "训练、推理加速和服务部署"
    if "生产工作流" in directions:
        return "创作编排、节点化工作流和自动化内容生产"
    if "3D/4D" in directions:
        return "3D/4D 资产生成与空间内容制作"
    return "多模态应用落地"


def summarize_readme(readme: str) -> str:
    if not readme:
        return ""
    cleaned = re.sub(r"`+", "", readme)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"\[[^\]]+\]\([^)]+\)", "", cleaned)
    lines = []
    for line in cleaned.splitlines():
        stripped = line.strip(" -#>*\t")
        if len(stripped) < 30:
            continue
        if stripped.lower().startswith(("installation", "usage", "license", "citation")):
            continue
        lines.append(stripped)
        if len(lines) >= 2:
            break
    if not lines:
        return ""
    snippet = " ".join(lines)
    snippet = re.sub(r"\s+", " ", snippet)
    return f"README 里强调的重点包括：{snippet[:180]}。"


def build_recommendation_reason(
    repo: Repository,
    directions: list[str],
    capabilities: list[str],
    *,
    today: date,
) -> str:
    reasons = []
    primary_direction = " / ".join(directions[:2])
    reasons.append(f"它和你的工作方向高度相关，核心落在 {primary_direction}。")
    if repo.stars >= 500:
        reasons.append(f"目前已有 {repo.stars} Star，说明社区已经有一定验证。")
    else:
        reasons.append(f"虽然当前 Star 只有 {repo.stars}，但更新很近，适合提前观察潜力。")
    days_since_push = max((today - repo.pushed_at.date()).days, 0)
    reasons.append(f"最近一次推送距今约 {days_since_push} 天，仍保持活跃。")
    if "工作流 / Agent" in capabilities or "推理 / 部署" in capabilities:
        reasons.append("它不只是模型本身，也更贴近生产工作流和落地链路。")
    return " ".join(reasons)


def assess_usage_barrier(repo: Repository) -> str:
    blob = repo.as_text_blob()
    if any(marker in blob for marker in ("demo", "gradio", "streamlit", "space", "huggingface")):
        return "开箱即用度较好，通常可以先通过 Demo 或示例快速体验。"
    if any(marker in blob for marker in ("docker", "api", "sdk", "cli")):
        return "需要一定部署能力，但工程接入路径相对清晰。"
    if any(marker in blob for marker in ("a100", "multi-gpu", "cuda", "training")):
        return "需要较强 GPU 或训练环境，更适合团队验证和深度试验。"
    return "偏研究或开发者向，需要自行准备环境并阅读文档。"


def assess_maturity(repo: Repository) -> str:
    blob = repo.as_text_blob()
    engineering_markers = ("api", "docker", "demo", "workflow", "deploy", "sdk", "serving")
    if repo.stars >= 1500 and any(marker in blob for marker in engineering_markers):
        return "可进生产参考"
    if repo.stars >= 3000 and len(repo.readme) >= 500 and any(
        marker in blob for marker in engineering_markers
    ):
        return "可进生产参考"
    if repo.stars >= 500 or (repo.stars >= 300 and len(repo.readme) >= 200):
        return "可试用"
    return "研究原型"


def assess_commercial_reference(repo: Repository) -> str:
    if repo.license_name in PERMISSIVE_LICENSES:
        return f"{repo.license_name} 许可证，通常可做商用参考，但仍建议按实际场景复核。"
    if repo.license_name in COPYLEFT_LICENSES:
        return f"{repo.license_name} 许可证，商用前建议重点评估 copyleft 约束。"
    if repo.license_name:
        return f"许可证为 {repo.license_name}，商用前建议先做条款确认。"
    return "未发现明确开源许可证，商用前需要先确认授权。"


def detect_demo_info(repo: Repository) -> str:
    blob = repo.as_text_blob()
    if "huggingface.co/spaces" in blob:
        return "有 Hugging Face Space，可直接在线体验。"
    if any(marker in blob for marker in ("demo", "gradio", "streamlit", "replicate")):
        return "README 中提到了 Demo 或在线体验入口，适合先快速试用。"
    if repo.homepage:
        return f"有项目主页：{repo.homepage}"
    return "未看到明确在线体验入口。"


def detect_paper_info(repo: Repository) -> str:
    blob = repo.as_text_blob()
    if "arxiv.org" in blob or "citation" in blob or "paper" in blob:
        return "大概率附带论文或引用信息，可进一步追原始方法。"
    return "未明显看到论文入口。"


def update_history(history: dict, recommendations: list[Recommendation], *, today: date) -> dict:
    recommended = history.setdefault("recommended", {})
    reports = history.setdefault("reports", [])
    for item in recommendations:
        recommended[item.repo.full_name] = {
            "last_recommended_at": today.isoformat(),
            "stars": item.repo.stars,
            "forks": item.repo.forks,
            "pushed_at": item.repo.pushed_at.isoformat(),
        }
    reports.append(
        {
            "date": today.isoformat(),
            "items": [item.repo.full_name for item in recommendations],
        }
    )
    history["reports"] = reports[-30:]
    return history


def format_report(recommendations: list[Recommendation], *, today: date) -> str:
    overview = build_overview_block(recommendations)
    top3 = recommendations[:3]
    lines = [
        f"# GitHub AI 工具日报 | {today.isoformat()}",
        "",
    ]
    trend_note = build_trend_note(recommendations)
    if trend_note:
        lines.extend(["## 今日趋势提醒", trend_note, ""])
    lines.extend(
        [
            "## 今日概览",
            overview,
            "",
            "今天最值得优先看的 3 个项目：",
        ]
    )
    for index, item in enumerate(top3, start=1):
        lines.append(f"{index}. **{item.repo.full_name}**：{item.overview}")
    lines.extend(["", "## 项目清单（按推荐优先级排序）", ""])

    for index, item in enumerate(recommendations, start=1):
        lines.extend(format_project_section(index, item))

    lines.extend(["## 最后总结", build_final_summary(recommendations)])
    return "\n".join(lines).strip() + "\n"


def build_trend_note(recommendations: list[Recommendation]) -> str:
    direction_counts = count_directions(recommendations)
    if not direction_counts:
        return ""
    top_direction, count = max(direction_counts.items(), key=lambda item: item[1])
    if count < 3:
        return ""
    if top_direction == "视频":
        return "今天视频相关项目明显更活跃，尤其是“生成 + 增强 + 数字人”一体化链路，值得重点跟进。"
    if top_direction == "生产工作流":
        return "今天工作流和 Agent 方向存在感很强，说明行业关注点正在从单点模型能力转向可复用的生产链路。"
    if top_direction == "多模态理解":
        return "今天多模态理解项目占比偏高，尤其适合关注 VLM、检索与视觉问答落地的人。"
    return f"今天 {top_direction} 方向更活跃，说明这个细分赛道近期值得持续盯盘。"


def build_overview_block(recommendations: list[Recommendation]) -> str:
    direction_counts = count_directions(recommendations)
    direction_summary = "，".join(
        f"{direction} {count} 个" for direction, count in sorted(direction_counts.items(), key=lambda item: item[1], reverse=True)
    )
    immediate = "；".join(item.repo.full_name for item in recommendations[:3])
    return (
        f"今天推荐的 {len(recommendations)} 个项目覆盖了 {direction_summary}。"
        f" 优先建议先看：{immediate}。"
    )


def count_directions(recommendations: list[Recommendation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in recommendations:
        for direction in item.directions:
            counts[direction] = counts.get(direction, 0) + 1
    return counts


def format_project_section(index: int, item: Recommendation) -> list[str]:
    repo = item.repo
    lines = [
        f"### {index}. {repo.full_name}",
        f"GitHub：[{repo.full_name}]({repo.html_url})",
        f"方向：{' / '.join(item.directions)}",
        f"Star：{repo.stars}",
        f"Fork：{repo.forks}",
        f"最近更新：{repo.pushed_at.date().isoformat()}",
        f"技术标签：{' / '.join(item.tags)}",
    ]
    if item.is_revisit and item.revisit_reason:
        lines.append(f"标记：{item.revisit_reason}")
    lines.extend(
        [
            f"功能概述：{item.overview}",
            f"详细说明：{item.detail}",
            f"推荐理由：{item.recommendation_reason}",
            f"使用门槛：{item.usage_barrier}",
            f"成熟度：{item.maturity}",
            f"商用参考：{item.commercial_reference}",
            f"Demo / 在线体验：{item.demo_info}",
            f"论文：{item.paper_info}",
            "",
        ]
    )
    return lines


def build_final_summary(recommendations: list[Recommendation]) -> str:
    ready_now = [item.repo.full_name for item in recommendations if item.maturity == "可进生产参考"][:4]
    watchlist = [
        item.repo.full_name
        for item in recommendations
        if item.maturity == "可试用" and item.repo.stars >= 200
    ][:4]
    research = [item.repo.full_name for item in recommendations if item.maturity == "研究原型"][:4]
    parts = []
    if ready_now:
        parts.append(f"更适合立即上手的有：{'、'.join(ready_now)}。")
    if watchlist:
        parts.append(f"更适合持续关注的有：{'、'.join(watchlist)}。")
    if research:
        parts.append(f"偏研究但值得收藏的有：{'、'.join(research)}。")
    return " ".join(parts)


def clean_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip().rstrip(".")
    return cleaned
