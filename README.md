# Daily AI News Digest（云端版）

无需本地 WorkBuddy 开机，GitHub Actions 每天北京时间 9:00 自动采编 AI 领域动态（侧重 AI coding 与具身智能），并通过飞书 bot 推送消息。

## 项目结构

```
.
├── .github/workflows/daily-ai-news.yml   # GitHub Actions 定时工作流
├── scripts/daily_ai_news.py              # 新闻采集 + LLM 总结 + 飞书推送
└── README.md                             # 部署说明
```

## 前置条件

1. 一个 GitHub 仓库（公开/私有均可，私有仓库 Actions 免费额度足够）。
2. 飞书应用已开启「机器人」能力，并拿到：
   - `App ID`
   - `App Secret`
   - 目标用户的 `open_id`
3. 一个免费的 LLM API Key（二选一）：
   - **Gemini 2.0 Flash**（推荐，1500 次/天）：https://aistudio.google.com/app/apikey
   - **SiliconFlow**：https://cloud.siliconflow.cn/

## 部署步骤

### 1. 把代码推送到 GitHub

```bash
git init
git add .
git commit -m "init: daily ai news digest"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

### 2. 配置 GitHub Secrets

进入仓库 → **Settings → Secrets and variables → Actions → New repository secret**，依次添加：

| Secret 名称 | 说明 |
|------------|------|
| `LARK_APP_ID` | 飞书应用 App ID，例如 `cli_aad6da804078dbe3` |
| `LARK_APP_SECRET` | 飞书应用 App Secret |
| `LARK_USER_OPEN_ID` | 接收消息用户的 open_id，例如 `ou_3d9c71e74c4aa75d95aab3971e7b645c` |
| `LLM_PROVIDER` | 填 `gemini` 或 `siliconflow` |
| `LLM_API_KEY` | 对应 LLM 平台的 API Key |
| `MAX_DAYS_OLD`（可选） | 只汇总 N 天内的新闻，默认 `2` |

### 3. 手动触发测试

进入仓库 → **Actions → Daily AI News Digest → Run workflow**，确认飞书能收到消息。

### 4. 停用本地 WorkBuddy 自动化（可选）

测试稳定后，在 WorkBuddy 中暂停原自动化任务，避免重复推送。

## 自定义

- **调整推送时间**：修改 `.github/workflows/daily-ai-news.yml` 中的 `cron`。
- **增删新闻源**：修改 `scripts/daily_ai_news.py` 中的 `RSS_FEEDS`。
- **调整关注方向**：修改 `scripts/daily_ai_news.py` 中的 `TOPIC_FOCUS`。

## 故障排查

| 现象 | 排查方向 |
|------|---------|
| Actions 没有每天运行 | 检查 `cron` 时区；确认仓库 Actions 已启用 |
| 飞书收不到消息 | 检查 Secrets 是否正确；确认飞书应用已开启「机器人」能力 |
| LLM 调用失败 | 检查 `LLM_PROVIDER` 和 `LLM_API_KEY`；查看 Gemini/SiliconFlow 额度 |
| 消息内容为空/错乱 | 查看 Actions 日志中脚本输出，检查 RSS 解析是否正常 |

## 安全说明

- `LARK_APP_SECRET` 和 `LLM_API_KEY` 仅存储在 GitHub Secrets 中，不会出现在代码或日志里。
- 不要将这些密钥提交到仓库。
