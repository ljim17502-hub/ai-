# GitHub AI 工具日报自动推送

这是一个不依赖本地电脑常驻运行的日报工具：用 GitHub Actions 每天自动抓取 GitHub 上近期活跃的 AI 工具项目，做去重、筛选、生成中文日报，并通过飞书机器人推送到群里。

## 适用场景

- 每天自动挖掘 10 个新的 GitHub AI 工具
- 重点关注图片、视频、多模态理解、VLM、AIGC 工作流、训练/推理/部署相关项目
- 避免和前几天的推送重复，必要时用“回访项目”形式追踪明显变化
- 无需本地电脑开机，只依赖 GitHub 仓库 + GitHub Actions + 飞书机器人

## 当前实现

- 多组 GitHub 搜索词并行覆盖图片、视频、多模态、3D/4D、工作流、部署等方向
- 根据相关性、近期活跃度、Star/Fork、README 完整度、工程化信号进行综合打分
- 用 `data/history.json` 记录历史推荐，默认避免重复
- 每次生成完整日报到 `data/last_report.md`
- 成功推送后自动把最新历史记录提交回仓库

## 目录说明

- `src/github_ai_daily/main.py`：主入口，负责拉取候选、生成日报、推送飞书
- `src/github_ai_daily/github_api.py`：GitHub REST API 封装
- `src/github_ai_daily/reporting.py`：筛选、评分、去重、日报格式化
- `src/github_ai_daily/feishu.py`：飞书机器人消息发送
- `.github/workflows/daily_push.yml`：定时任务
- `data/history.json`：历史推送去重状态
- `data/last_report.md`：最近一次生成的日报

## 需要配置的 Secrets

在 GitHub 仓库的 `Settings > Secrets and variables > Actions` 里添加：

- `FEISHU_WEBHOOK_URL`：飞书自定义机器人的 webhook 地址
- `FEISHU_BOT_SECRET`：如果机器人启用了签名校验就填写；没开可以留空

说明：

- 工作流里的 `GITHUB_TOKEN` 直接使用 GitHub Actions 自带的内置 token，不需要你手动新建
- 如果你想在本地预览日报，建议额外在本地环境里设置 `GITHUB_TOKEN`，否则容易触发 GitHub 匿名访问限流

## 定时任务

当前工作流配置为每天北京时间 `09:00` 自动执行一次：

```yaml
schedule:
  - cron: "0 1 * * *"
```

如果你想改时间，只需要调整 `.github/workflows/daily_push.yml` 里的 cron。

## 本地预览

先安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

然后预览当天日报，不会推送飞书，也不会写入历史：

```bash
PYTHONPATH=src python -m github_ai_daily.main --dry-run
```

生成结果会写到：

- `data/last_report.md`

## 推送逻辑说明

1. 从 GitHub 搜索近期活跃且和图片/视频/多模态强相关的候选项目
2. 合并去重后抓取 README，进一步识别能力标签和工程化信号
3. 跳过历史已推送项目，除非出现明显增长或持续活跃，才作为“回访项目”再次出现
4. 输出中文日报结构：
   - 今日趋势提醒
   - 今日概览
   - 最值得优先看的 3 个项目
   - 10 个项目详细清单
   - 最后总结
5. 通过飞书机器人分片推送，避免单条消息过长

## 可继续增强的方向

- 接入 LLM，把 README 和 Release Notes 进一步总结得更像人工编辑日报
- 接入 GitHub Release / Commit Diff，做更准确的“回访项目变化点”
- 给不同方向设置配额，例如每天至少覆盖 2 个视频、2 个图片、2 个多模态项目
- 支持同时推送飞书 + 邮件 + Notion
