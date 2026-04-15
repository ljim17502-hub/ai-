import base64
import hashlib
import hmac
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_PATH = DATA_DIR / "history.json"
REPORT_PATH = DATA_DIR / "last_report.md"

TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Shanghai")
TODAY = datetime.now(ZoneInfo(TIMEZONE_NAME)).date()
GITHUB_TOKEN = (os.getenv("GITHUB_TOKEN") or "").strip()
FEISHU_WEBHOOK_URL = (os.getenv("FEISHU_WEBHOOK_URL") or "").strip()
FEISHU_BOT_SECRET = (os.getenv("FEISHU_BOT_SECRET") or "").strip()
FEISHU_KEYWORD = (os.getenv("FEISHU_KEYWORD") or "").strip()
MAX_RECOMMENDATIONS = int(os.getenv("MAX_RECOMMENDATIONS", "10"))
GITHUB_SEARCH_DAYS = int(os.getenv("GITHUB_SEARCH_DAYS", "240"))
SEARCH_PER_QUERY = 12
README_FETCH_LIMIT = 20

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-ai-daily-push",
        "X-GitHub-Api-Version": "2022-11-28",
    }
)
if GITHUB_TOKEN:
    SESSION.headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

DIRECTION_KEYWORDS = {
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
        "image restoration",
    ],
    "视频": [
        "text-to-video",
        "image-to-video",
        "video generation",
        "video editing",
        "frame interpolation",
        "video super resolution",
        "video denoise",
        "lip sync",
        "lipsync",
        "motion",
        "avatar",
        "video understanding",
    ],
    "多模态理解": [
        "multimodal",
        "vision language",
        "vlm",
        "retrieval",
        "grounding",
        "ocr",
        "document understanding",
        "visual question",
    ],
    "生产工作流": [
        "workflow",
        "agent",
        "automation",
        "pipeline",
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
        "quantization",
        "accelerat",
        "tensorrt",
        "onnx",
    ],
    "3D/4D": ["3d", "4d", "gaussian", "nerf", "mesh"],
}

CAPABILITY_KEYWORDS = {
    "文生图": ["text-to-image", "txt2img", "diffusion"],
    "图生图": ["image-to-image", "img2img"],
    "图像编辑 / 修复": ["image editing", "inpainting", "restoration"],
    "超分辨率": ["upscaling", "super-resolution", "super resolution"],
    "抠图 / 分割": ["segmentation", "matting", "mask"],
    "风格迁移": ["style transfer"],
    "文生视频": ["text-to-video", "video generation"],
    "图生视频": ["image-to-video"],
    "视频编辑": ["video editing"],
    "补帧": ["frame interpolation"],
    "视频超分": ["video super resolution"],
    "视频去噪": ["video denoise", "denoise"],
    "VLM / 视觉语言理解": ["vision language", "vision-language", "vlm", "llava"],
    "图文/多模态检索": ["retrieval", "grounding", "search"],
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


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def github_get(path: str, *, params=None, ok_statuses=(200,)):
    response = SESSION.get(f"https://api.github.com/{path.lstrip('/')}", params=params, timeout=30)
    if response.status_code in ok_statuses:
        return response
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        reset_at = response.headers.get("X-RateLimit-Reset", "unknown")
        raise RuntimeError(f"GitHub API 触发限流，请稍后再试。重置时间：{reset_at}")
    raise RuntimeError(f"GitHub API 请求失败：{response.status_code} {response.text[:300]}")


def build_queries():
    cutoff = TODAY - timedelta(days=GITHUB_SEARCH_DAYS)
    base = f"archived:false is:public mirror:false pushed:>={cutoff.isoformat()} stars:>=10"
    return [
        f'"text-to-image" OR diffusion {base}',
        f'"image editing" OR inpainting OR upscaling OR segmentation {base}',
        f'"video generation" OR "text-to-video" OR "image-to-video" {base}',
        f'"video editing" OR "frame interpolation" OR "video super resolution" OR denoise {base}',
        f'"vision language model" OR VLM OR "multimodal understanding" {base}',
        f'multimodal image video vision {base}',
        f'"digital human" OR "virtual human" OR "lip sync" OR "motion drive" {base}',
        f'"3D generation" OR gaussian OR NeRF OR "4D generation" {base}',
        f'workflow agent pipeline image video multimodal {base}',
        f'training inference deployment acceleration diffusion vlm multimodal {base}',
    ]


def search_repositories(query: str):
    response = github_get(
        "/search/repositories",
        params={"q": query, "sort": "updated", "order": "desc", "per_page": SEARCH_PER_QUERY},
    )
    repos = []
    for item in response.json().get("items", []):
        repos.append(
            {
                "full_name": item["full_name"],
                "name": item["name"],
                "html_url": item["html_url"],
                "description": (item.get("description") or "").strip(),
                "stars": int(item.get("stargazers_count", 0)),
                "forks": int(item.get("forks_count", 0)),
                "topics": item.get("topics") or [],
                "homepage": item.get("homepage") or "",
                "language": item.get("language") or "",
                "license_name": ((item.get("license") or {}).get("spdx_id") or ""),
                "created_at": parse_dt(item["created_at"]),
                "pushed_at": parse_dt(item["pushed_at"]),
                "readme": "",
            }
        )
    time.sleep(0.3)
    return repos


def fetch_readme(full_name: str) -> str:
    response = github_get(f"/repos/{full_name}/readme", ok_statuses=(200, 404))
    if response.status_code == 404:
        return ""
    content = response.json().get("content") or ""
    if not content:
        return ""
    try:
        decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
    except Exception:
        return ""
    time.sleep(0.15)
    return decoded[:12000]


def text_blob(repo: dict) -> str:
    return "\n".join(
        [
            repo.get("name", ""),
            repo.get("description", ""),
            " ".join(repo.get("topics", [])),
            repo.get("readme", ""),
        ]
    ).lower()


def detect_directions(repo: dict):
    text = text_blob(repo)
    matched = [name for name, words in DIRECTION_KEYWORDS.items() if any(word in text for word in words)]
    return matched or ["多模态理解"]


def detect_capabilities(repo: dict):
    text = text_blob(repo)
    matched = [name for name, words in CAPABILITY_KEYWORDS.items() if any(word in text for word in words)]
    return matched[:5] or ["多模态工具链"]


def extract_tags(repo: dict):
    values = list(repo.get("topics", [])) + [value.lower() for value in detect_capabilities(repo)]
    if repo.get("language"):
        values.append(repo["language"].lower())
    result = []
    seen = set()
    for value in values:
        norm = value.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result[:8]


def score_repo(repo: dict):
    text = text_blob(repo)
    relevance = 0.0
    for words in DIRECTION_KEYWORDS.values():
        relevance += min(sum(1 for word in words if word in text) * 1.5, 6.0)
    days_since_push = max((TODAY - repo["pushed_at"].date()).days, 0)
    activity = max(0.0, 16.0 - min(days_since_push, 120) / 8)
    community = min(18.0, math.log10(repo["stars"] + 1) * 6.5 + math.log10(repo["forks"] + 1) * 2.2)
    readme_bonus = 3.0 if len(repo.get("readme", "")) >= 800 else 1.0 if len(repo.get("readme", "")) >= 200 else 0.0
    production_bonus = min(6.0, sum(1.0 for key in ["docker", "api", "sdk", "demo", "gradio", "streamlit", "workflow", "deploy"] if key in text))
    freshness_bonus = 4.0 if (TODAY - repo["created_at"].date()).days <= 180 and repo["stars"] >= 50 else 0.0
    return relevance + activity + community + readme_bonus + production_bonus + freshness_bonus


def load_history():
    if not HISTORY_PATH.exists():
        return {"recommended": {}, "reports": []}
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def save_history(history: dict):
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def revisit_state(repo: dict, history: dict):
    previous = history.get("recommended", {}).get(repo["full_name"])
    if not previous:
        return {"skip": False, "is_revisit": False, "reason": ""}
    last_date = datetime.fromisoformat(previous["last_recommended_at"]).date()
    days_since_last = (TODAY - last_date).days
    previous_stars = int(previous.get("stars", 0))
    star_delta = repo["stars"] - previous_stars
    if days_since_last >= 14 and star_delta >= max(100, int(previous_stars * 0.15)):
        return {
            "skip": False,
            "is_revisit": True,
            "reason": f"这是回访项目：较上次新增 {star_delta} Star，社区热度继续抬升。",
        }
    return {"skip": True, "is_revisit": False, "reason": ""}


def summarize_readme(readme: str):
    if not readme:
        return ""
    cleaned = re.sub(r"`+", "", readme)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"\[[^\]]+\]\([^)]+\)", "", cleaned)
    lines = []
    for line in cleaned.splitlines():
        line = line.strip(" -#>*\t")
        if len(line) < 30:
            continue
        if line.lower().startswith(("installation", "usage", "license", "citation")):
            continue
        lines.append(line)
        if len(lines) >= 2:
            break
    return re.sub(r"\s+", " ", " ".join(lines))[:180]


def commercial_reference(repo: dict):
    license_name = repo.get("license_name") or ""
    if license_name in PERMISSIVE_LICENSES:
        return f"{license_name} 许可证，通常可做商用参考，但仍建议按实际场景复核。"
    if license_name in COPYLEFT_LICENSES:
        return f"{license_name} 许可证，商用前建议重点评估 copyleft 约束。"
    if license_name:
        return f"许可证为 {license_name}，商用前建议先确认具体条款。"
    return "未发现明确开源许可证，商用前需要先确认授权。"


def demo_info(repo: dict):
    text = text_blob(repo)
    if "huggingface.co/spaces" in text:
        return "有 Hugging Face Space，可直接在线体验。"
    if any(key in text for key in ["demo", "gradio", "streamlit", "replicate"]):
        return "README 中提到了 Demo 或在线体验入口。"
    if repo.get("homepage"):
        return f"有项目主页：{repo['homepage']}"
    return "未看到明确在线体验入口。"


def paper_info(repo: dict):
    text = text_blob(repo)
    if "arxiv.org" in text or "paper" in text or "citation" in text:
        return "大概率附带论文或引用信息，可进一步追原始方法。"
    return "未明显看到论文入口。"


def usage_barrier(repo: dict):
    text = text_blob(repo)
    if any(key in text for key in ["demo", "gradio", "streamlit", "space", "huggingface"]):
        return "开箱即用度较好，通常可以先通过 Demo 或示例快速体验。"
    if any(key in text for key in ["docker", "api", "sdk", "cli"]):
        return "需要一定部署能力，但工程接入路径相对清晰。"
    if any(key in text for key in ["a100", "multi-gpu", "cuda", "training"]):
        return "需要较强 GPU 或训练环境，更适合团队验证和深度试验。"
    return "偏研究或开发者向，需要自行准备环境并阅读文档。"


def maturity(repo: dict):
    text = text_blob(repo)
    if repo["stars"] >= 1500 and any(key in text for key in ["api", "docker", "demo", "workflow", "deploy", "sdk", "serving"]):
        return "可进生产参考"
    if repo["stars"] >= 500 or (repo["stars"] >= 300 and len(repo.get("readme", "")) >= 200):
        return "可试用"
    return "研究原型"


def build_item(repo: dict, revisit: dict):
    directions = detect_directions(repo)
    capabilities = detect_capabilities(repo)
    description = (repo.get("description") or "").strip().rstrip(".")
    if description:
        overview = f"一个偏 {' / '.join(capabilities[:2])} 的开源项目，核心定位是：{description}"
    else:
        overview = f"一个偏 {' / '.join(capabilities[:2])} 的开源项目，适合关注 {'、'.join(directions[:2])} 方向的最新能力演进。"

    if "视频" in directions:
        scene = "视频生成、视频增强、数字人或口型同步"
    elif "图片" in directions:
        scene = "图像生成、修复、超分、分割或风格化处理"
    elif "多模态理解" in directions:
        scene = "图文/视频理解、检索和视觉语言应用"
    elif "模型训练 / 推理 / 部署" in directions:
        scene = "训练、推理加速和服务部署"
    elif "生产工作流" in directions:
        scene = "创作编排、节点化工作流和自动化内容生产"
    else:
        scene = "多模态应用落地"

    details = [
        f"从 README 和主题信息看，它主要覆盖 {', '.join(capabilities[:3])} 等能力。",
        f"更适合用在 {scene} 这类场景，尤其适合需要把模型能力和实际生产链路接起来的团队。",
    ]
    summary = summarize_readme(repo.get("readme", ""))
    if summary:
        details.append(f"README 里强调的重点包括：{summary}。")

    reasons = [
        f"它和你的工作方向高度相关，核心落在 {' / '.join(directions[:2])}。",
        f"{repo['stars']} Star，社区已经有一定关注度。",
        f"最近更新是 {repo['pushed_at'].date().isoformat()}，仍保持活跃。",
    ]
    if "工作流 / Agent" in capabilities or "推理 / 部署" in capabilities:
        reasons.append("它不只是模型本身，也更贴近生产工作流和落地链路。")

    item = {
        "repo": repo,
        "score": score_repo(repo),
        "directions": directions,
        "tags": extract_tags(repo),
        "is_revisit": revisit["is_revisit"],
        "revisit_reason": revisit["reason"],
        "overview": overview,
        "detail": " ".join(details[:3]),
        "recommend_reason": " ".join(reasons),
        "usage_barrier": usage_barrier(repo),
        "maturity": maturity(repo),
        "commercial_reference": commercial_reference(repo),
        "demo_info": demo_info(repo),
        "paper_info": paper_info(repo),
    }
    if item["is_revisit"]:
        item["score"] += 2.0
    return item


def select_items(repos, history):
    primary = []
    for repo in repos:
        revisit = revisit_state(repo, history)
        if revisit["skip"]:
            continue
        item = build_item(repo, revisit)
        if item["score"] >= 14:
            primary.append(item)

    primary.sort(key=lambda item: item["score"], reverse=True)
    selected = primary[:MAX_RECOMMENDATIONS]
    if len(selected) >= MAX_RECOMMENDATIONS:
        return selected

    seen = {item["repo"]["full_name"] for item in selected}
    fallback = []
    for repo in repos:
        if repo["full_name"] in seen:
            continue
        revisit = revisit_state(repo, history)
        if revisit["skip"]:
            continue
        fallback.append(build_item(repo, revisit))
    fallback.sort(key=lambda item: item["score"], reverse=True)
    return (selected + fallback)[:MAX_RECOMMENDATIONS]


def count_directions(items):
    counts = {}
    for item in items:
        for direction in item["directions"]:
            counts[direction] = counts.get(direction, 0) + 1
    return counts


def build_trend_note(items):
    counts = count_directions(items)
    if not counts:
        return ""
    direction, count = max(counts.items(), key=lambda pair: pair[1])
    if count < 3:
        return ""
    if direction == "视频":
        return "今天视频相关项目明显更活跃，尤其是“生成 + 增强 + 数字人”一体化链路，值得重点跟进。"
    if direction == "生产工作流":
        return "今天工作流和 Agent 方向存在感很强，说明行业关注点正在从单点模型能力转向可复用的生产链路。"
    if direction == "多模态理解":
        return "今天多模态理解项目占比偏高，尤其适合关注 VLM、检索与视觉问答落地的人。"
    return f"今天 {direction} 方向更活跃，说明这个细分赛道近期值得持续盯盘。"


def format_report(items):
    counts = count_directions(items)
    overview = "，".join(f"{name} {count} 个" for name, count in sorted(counts.items(), key=lambda pair: pair[1], reverse=True))
    top_names = "；".join(item["repo"]["full_name"] for item in items[:3])

    lines = [f"# GitHub AI 工具日报 | {TODAY.isoformat()}", ""]
    trend = build_trend_note(items)
    if trend:
        lines.extend(["## 今日趋势提醒", trend, ""])

    lines.extend(
        [
            "## 今日概览",
            f"今天推荐的 {len(items)} 个项目覆盖了 {overview}。 优先建议先看：{top_names}。",
            "",
            "今天最值得优先看的 3 个项目：",
        ]
    )
    for index, item in enumerate(items[:3], start=1):
        lines.append(f"{index}. **{item['repo']['full_name']}**：{item['overview']}")

    lines.extend(["", "## 项目清单（按推荐优先级排序）", ""])
    for index, item in enumerate(items, start=1):
        repo = item["repo"]
        lines.extend(
            [
                f"### {index}. {repo['full_name']}",
                f"GitHub：{repo['html_url']}",
                f"方向：{' / '.join(item['directions'])}",
                f"Star：{repo['stars']}",
                f"Fork：{repo['forks']}",
                f"最近更新：{repo['pushed_at'].date().isoformat()}",
                f"技术标签：{' / '.join(item['tags'])}",
            ]
        )
        if item["is_revisit"] and item["revisit_reason"]:
            lines.append(f"标记：{item['revisit_reason']}")
        lines.extend(
            [
                f"功能概述：{item['overview']}",
                f"详细说明：{item['detail']}",
                f"推荐理由：{item['recommend_reason']}",
                f"使用门槛：{item['usage_barrier']}",
                f"成熟度：{item['maturity']}",
                f"商用参考：{item['commercial_reference']}",
                f"Demo / 在线体验：{item['demo_info']}",
                f"论文：{item['paper_info']}",
                "",
            ]
        )

    immediate = [item["repo"]["full_name"] for item in items if item["maturity"] == "可进生产参考"][:4]
    watch = [item["repo"]["full_name"] for item in items if item["maturity"] == "可试用"][:4]
    research = [item["repo"]["full_name"] for item in items if item["maturity"] == "研究原型"][:4]

    summary = []
    if immediate:
        summary.append(f"更适合立即上手的有：{'、'.join(immediate)}。")
    if watch:
        summary.append(f"更适合持续关注的有：{'、'.join(watch)}。")
    if research:
        summary.append(f"偏研究但值得收藏的有：{'、'.join(research)}。")

    lines.extend(["## 最后总结", " ".join(summary)])
    return "\n".join(lines).strip() + "\n"


def chunk_text(text: str, limit: int = 2600):
    parts = text.split("\n### ")
    chunks = [parts[0]]
    for part in parts[1:]:
        piece = f"\n### {part}"
        if len(chunks[-1]) + len(piece) <= limit:
            chunks[-1] += piece
        else:
            chunks.append(piece.lstrip("\n"))
    return chunks


def build_feishu_payload(text: str):
    content = f"{FEISHU_KEYWORD}\n{text}" if FEISHU_KEYWORD else text
    payload = {"msg_type": "text", "content": {"text": content}}
    if FEISHU_BOT_SECRET:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{FEISHU_BOT_SECRET}"
        sign = base64.b64encode(
            hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    return payload


def send_to_feishu(report: str):
    if not FEISHU_WEBHOOK_URL:
        raise RuntimeError("缺少 FEISHU_WEBHOOK_URL，无法推送到飞书。")
    for chunk in chunk_text(report):
        response = requests.post(
            FEISHU_WEBHOOK_URL,
            json=build_feishu_payload(chunk),
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(f"飞书推送失败：{response.status_code} {response.text[:300]}")
        data = response.json()
        if data.get("code") not in (0, None):
            raise RuntimeError(
                "飞书推送失败："
                f"code={data.get('code')} msg={data.get('msg') or data.get('message') or data}"
            )


def update_history(history: dict, items):
    recommended = history.setdefault("recommended", {})
    reports = history.setdefault("reports", [])
    for item in items:
        repo = item["repo"]
        recommended[repo["full_name"]] = {
            "last_recommended_at": TODAY.isoformat(),
            "stars": repo["stars"],
            "forks": repo["forks"],
            "pushed_at": repo["pushed_at"].isoformat(),
        }
    reports.append({"date": TODAY.isoformat(), "items": [item["repo"]["full_name"] for item in items]})
    history["reports"] = reports[-30:]
    return history


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_candidates = {}
    queries = build_queries()
    if not GITHUB_TOKEN:
        queries = queries[:6]

    for query in queries:
        for repo in search_repositories(query):
            current = all_candidates.get(repo["full_name"])
            if not current or repo["stars"] > current["stars"]:
                all_candidates[repo["full_name"]] = repo

    candidates = sorted(
        all_candidates.values(),
        key=lambda repo: (
            repo["stars"] * 1.5 + repo["forks"] * 0.4 + max(0, 180 - (TODAY - repo["pushed_at"].date()).days)
        ),
        reverse=True,
    )

    for repo in candidates[:README_FETCH_LIMIT]:
        try:
            repo["readme"] = fetch_readme(repo["full_name"])
        except Exception:
            break

    history = load_history()
    items = select_items(candidates, history)
    if not items:
        raise RuntimeError("没有筛到可用项目，请检查 GitHub API 配额或搜索条件。")

    report = format_report(items)
    REPORT_PATH.write_text(report, encoding="utf-8")

    if "--dry-run" in sys.argv:
        print("已生成日报：data/last_report.md")
        return

    send_to_feishu(report)
    save_history(update_history(history, items))
    print("日报已推送到飞书，并更新历史记录。")


if __name__ == "__main__":
    main()
