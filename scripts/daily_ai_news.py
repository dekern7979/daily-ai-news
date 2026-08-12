#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily AI News Digest for Lark/Feishu
Runs in GitHub Actions, fetches AI news (focus: AI coding & embodied intelligence),
summarizes with a free LLM, and pushes a markdown message via Feishu OpenAPI.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any


# ---------- Config ----------
class Config:
    LARK_APP_ID: str = os.environ["LARK_APP_ID"]
    LARK_APP_SECRET: str = os.environ["LARK_APP_SECRET"]
    LARK_USER_OPEN_ID: str = os.environ["LARK_USER_OPEN_ID"]
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "gemini").lower().strip()
    LLM_API_KEY: str = os.environ["LLM_API_KEY"]
    MAX_DAYS_OLD: int = int(os.environ.get("MAX_DAYS_OLD", "2"))
    TOPIC_FOCUS: list[str] = [
        # 英文核心关键词
        "ai coding", "coding agent", "code generation", "vibe coding",
        "embodied intelligence", "embodied ai", "humanoid robot", "humanoid",
        "robotics", "robot", "anthropic", "claude code", "codex", "cursor",
        "github copilot", "openai", "deepseek", "kimi", "qwen", "llm agent",
        # 中文核心关键词
        "具身智能", "人形机器人", "代码生成", "编程助手", "智能体", "智能编程",
        "机器人", "宇树", "智元", "优必选", "银河通用", "星动纪元", "傅利叶",
        "逐际动力", "原力灵机", "蚂蚁灵波", "商汤", "大晓", "破晓", "西湖机器人",
        "阶跃", "智谱", "通义", "文心", "deepseek v", "claude", "gpt",
        "国产模型", "国产芯片", "算力", "开源", "编程agent",
    ]


# ---------- RSS Sources ----------
RSS_FEEDS = [
    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/"},
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml"},
    {"name": "Anthropic News", "url": "https://www.anthropic.com/news/rss"},
    {"name": "HuggingFace Blog", "url": "https://huggingface.co/blog/feed.xml"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "机器之心", "url": "https://www.jiqizhixin.com/rss"},
    {"name": "量子位", "url": "https://www.qbitai.com/feed/"},
]


# ---------- HTTP helpers ----------
def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_post(url: str, data: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=payload, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------- RSS parsing ----------
def parse_rss_feed(feed_info: dict[str, str]) -> list[dict[str, str]]:
    try:
        raw = http_get(feed_info["url"])
    except Exception as e:
        print(f"[WARN] Failed to fetch {feed_info['name']}: {e}", file=sys.stderr)
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"[WARN] Failed to parse {feed_info['name']}: {e}", file=sys.stderr)
        return []

    # Handle both RSS 2.0 (<channel>/<item>) and Atom (<feed>/<entry>)
    items: list[dict[str, str]] = []
    channel = root.find("channel")
    entries = root.findall("item") if channel is not None else root.findall("{http://www.w3.org/2005/Atom}entry")
    if channel is not None:
        entries = channel.findall("item")

    for entry in entries[:20]:  # limit per feed
        title = ""
        link = ""
        pub_date = ""
        summary = ""

        if channel is not None:
            title = (entry.findtext("title") or "").strip()
            link = (entry.findtext("link") or "").strip()
            pub_date = (entry.findtext("pubDate") or entry.findtext("dc:date") or "").strip()
            summary = (entry.findtext("description") or "").strip()
        else:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
            link_el = entry.find("atom:link", namespaces=ns)
            link = link_el.get("href") if link_el is not None else ""
            pub_date = (entry.findtext("atom:published", namespaces=ns) or
                        entry.findtext("atom:updated", namespaces=ns) or "").strip()
            summary = (entry.findtext("atom:summary", namespaces=ns) or
                       entry.findtext("atom:content", namespaces=ns) or "").strip()

        # Strip HTML tags from summary
        summary = re.sub(r"<[^>]+>", "", summary)
        summary = re.sub(r"\s+", " ", summary).strip()[:500]

        if title and link:
            items.append({
                "source": feed_info["name"],
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "summary": summary,
            })

    return items


def article_is_recent(article: dict[str, str], max_days: int) -> bool:
    """Best-effort date filter; keep article if date parsing fails."""
    if not article["pub_date"]:
        return True
    try:
        # Try common RSS date format
        dt = datetime.strptime(article["pub_date"][:25], "%a, %d %b %Y %H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        try:
            dt = datetime.fromisoformat(article["pub_date"].replace("Z", "+00:00"))
        except Exception:
            return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
    return dt >= cutoff


def article_matches_focus(article: dict[str, str]) -> bool:
    text = f"{article['title']} {article['summary']}".lower()
    # Match any keyword — case-insensitive. Chinese keywords don't need lower().
    return any(kw.lower() in text for kw in Config.TOPIC_FOCUS)


# ---------- LLM summarization ----------
def build_prompt(articles: list[dict[str, str]], today_str: str) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. [{a['source']}] {a['title']}\n   摘要: {a['summary']}\n   链接: {a['link']}")
    articles_text = "\n".join(lines)

    return (
        f"你是一位 AI 行业资深编辑。今天的日期是 {today_str}。"
        "请从下面候选新闻中筛选 3-5 条当天最有价值的信息，"
        "重点侧重「AI coding / 编程智能体」和「具身智能 / 人形机器人」两个方向。\n\n"
        "【严格输出格式要求】\n"
        f"输出必须是纯 Markdown 文本（不要包在 ```markdown``` 代码块里），标题固定为：\n"
        f"# 每日 AI 新闻 · {today_str}\n\n"
        "正文使用如下结构（每条用 emoji 编号开头）：\n\n"
        "**方向**：AI Coding × 具身智能｜今日 N 条聚焦 当天新发生事件\n\n"
        "---\n\n"
        "## 1️⃣ <新闻标题（不超过30字）>\n"
        "<用 2-3 行简要说明事件内容，包含具体公司/产品/数据>\n\n"
        "- 数据点1：xxx\n"
        "- 数据点2：xxx\n"
        "- 对比：xxx vs xxx\n\n"
        "**意义**：<一句话点出值得关注的战略意义>\n\n"
        "---\n\n"
        "## 2️⃣ ... (依此类推到第5条)\n\n"
        "---\n\n"
        "## 🎯 本日核心叙事\n"
        "**AI Coding 侧**：...\n"
        "**具身智能侧**：...\n"
        "**交叉趋势**：...\n\n"
        "【内容质量要求】\n"
        "- 优先选择有具体数据/数字/公司名的硬新闻，避免模糊的\"概念炒作\"\n"
        "- AI Coding 与具身智能各至少 1 条\n"
        "- 每条都要点出\"值得关注的原因\"，不能只罗列事件\n"
        "- 中文输出\n"
        "- 不要超过 4500 字符（飞书 markdown 卡片限制）\n\n"
        f"候选新闻（{len(articles)} 条）：\n{articles_text}"
    )


def call_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={Config.LLM_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 4096,  # 增大避免截断
            "topP": 0.95,
        },
    }
    resp = http_post(url, payload, timeout=90)
    try:
        text = resp["candidates"][0]["content"]["parts"][0]["text"]
        # Gemini 偶尔会输出 ```markdown ... ``` 代码块包装，去掉外层包装
        text = re.sub(r"^```(?:markdown|md)?\s*\n", "", text.strip())
        text = re.sub(r"\n```\s*$", "", text.strip())
        return text
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini response parse error: {e}\n{json.dumps(resp, ensure_ascii=False)}")


def call_siliconflow(prompt: str) -> str:
    url = "https://api.siliconflow.cn/v1/chat/completions"
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 4096,
    }
    headers = {"Authorization": f"Bearer {Config.LLM_API_KEY}"}
    resp = http_post(url, payload, headers, timeout=90)
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"SiliconFlow response parse error: {e}\n{json.dumps(resp, ensure_ascii=False)}")


def summarize(articles: list[dict[str, str]], today_str: str) -> str:
    prompt = build_prompt(articles, today_str)
    if Config.LLM_PROVIDER == "gemini":
        return call_gemini(prompt)
    elif Config.LLM_PROVIDER == "siliconflow":
        return call_siliconflow(prompt)
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {Config.LLM_PROVIDER}")


# ---------- Lark / Feishu ----------
def get_lark_token() -> str:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = http_post(url, {"app_id": Config.LARK_APP_ID, "app_secret": Config.LARK_APP_SECRET})
    if resp.get("code") != 0:
        raise RuntimeError(f"Lark token error: {resp}")
    return resp["tenant_access_token"]


def send_lark_post(token: str, content: str, title: str = None) -> dict[str, Any]:
    """Send a Feishu 'post' message (renders as Markdown card) to a user via P2P."""
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    params = urllib.parse.urlencode({"receive_id_type": "open_id"})
    full_url = f"{url}?{params}"

    # 飞书 post 格式: zh_cn.title + content (二维数组) + 摘要
    lines = content.split("\n")
    content_blocks: list[list[dict[str, Any]]] = []
    current_block: list[dict[str, Any]] = []

    for line in lines:
        if line.strip() == "":
            # 空行 - 当前块结束
            if current_block:
                content_blocks.append(current_block)
                current_block = []
        else:
            current_block.append([{"tag": "text", "text": line}])

    if current_block:
        content_blocks.append(current_block)

    # 兜底：至少有一个块
    if not content_blocks:
        content_blocks = [[[{"tag": "text", "text": content[:4000]}]]]

    post_payload: dict[str, Any] = {
        "title": title or "AI 新闻日报推送",
        "content": content_blocks,
    }

    payload = {
        "receive_id": Config.LARK_USER_OPEN_ID,
        "msg_type": "post",
        "content": json.dumps(post_payload, ensure_ascii=False),
    }
    headers = {"Authorization": f"Bearer {token}"}
    req = urllib.request.Request(
        full_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_lark_markdown_fallback(token: str, content: str, title: str = None) -> dict[str, Any]:
    """Fallback: use msg_type=post with a single markdown element block.
    Used if the line-based post format fails for some reason."""
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    params = urllib.parse.urlencode({"receive_id_type": "open_id"})
    full_url = f"{url}?{params}"
    payload = {
        "receive_id": Config.LARK_USER_OPEN_ID,
        "msg_type": "post",
        "content": json.dumps({
            "title": title or "AI 新闻日报推送",
            "content": [[[{"tag": "text", "text": content[:4000]}]]]
        }, ensure_ascii=False),
    }
    headers = {"Authorization": f"Bearer {token}"}
    req = urllib.request.Request(
        full_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------- Main ----------
def main() -> None:
    # Get today (Asia/Shanghai) for the digest title
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        today = datetime.now(timezone.utc) + timedelta(hours=8)
    today_str = today.strftime("%Y-%m-%d")

    print(f"[INFO] Today (Asia/Shanghai): {today_str}")
    print("[INFO] Fetching RSS feeds...")
    all_articles: list[dict[str, str]] = []
    for feed in RSS_FEEDS:
        articles = parse_rss_feed(feed)
        print(f"[INFO] {feed['name']}: {len(articles)} articles")
        all_articles.extend(articles)

    print(f"[INFO] Total articles: {len(all_articles)}")

    # Filter: recent + topic match
    filtered = [
        a for a in all_articles
        if article_is_recent(a, Config.MAX_DAYS_OLD) and article_matches_focus(a)
    ]
    print(f"[INFO] Focus-matched articles: {len(filtered)}")

    if not filtered:
        print("[WARN] No matching articles found; falling back to recent articles.")
        filtered = [a for a in all_articles if article_is_recent(a, Config.MAX_DAYS_OLD)]

    if not filtered:
        raise RuntimeError("No articles available to summarize.")

    print("[INFO] Summarizing with LLM...")
    digest = summarize(filtered[:30], today_str)
    print(f"[INFO] Digest length: {len(digest)} chars")
    print("=" * 60)
    print(digest)
    print("=" * 60)

    # Save to local file (also written into repo by GH Actions checkout)
    out_path = f"daily_ai_news_{today_str}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(digest + "\n")
    print(f"[INFO] Saved digest to {out_path}")

    print("[INFO] Sending Lark post message...")
    token = get_lark_token()
    title = f"每日 AI 新闻 · {today_str}"
    try:
        result = send_lark_post(token, digest, title=title)
    except Exception as e:
        print(f"[WARN] post format failed: {e}, falling back", file=sys.stderr)
        result = send_lark_markdown_fallback(token, digest, title=title)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("code") != 0:
        raise RuntimeError(f"Lark send failed: {result}")

    print("[INFO] Done.")


if __name__ == "__main__":
    main()