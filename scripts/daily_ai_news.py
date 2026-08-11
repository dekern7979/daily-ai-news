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
    TOPIC_FOCUS: list[str] = ["ai coding", "coding agent", "code generation",
                              "embodied intelligence", "embodied ai", "humanoid robot",
                              "robotics", "具身智能", "人形机器人", "代码生成", "编程助手"]


# ---------- RSS Sources ----------
RSS_FEEDS = [
    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/"},
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml"},
    {"name": "Anthropic News", "url": "https://www.anthropic.com/news/rss.xml"},
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

    for entry in entries[:15]:  # limit per feed
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
            summary = (entry.findtext("atom:summary", namespaces=ns) or "").strip()

        # Strip HTML tags from summary
        summary = re.sub(r"<[^>]+>", "", summary)
        summary = re.sub(r"\s+", " ", summary).strip()[:400]

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
    return any(kw.lower() in text for kw in Config.TOPIC_FOCUS)


# ---------- LLM summarization ----------
def build_prompt(articles: list[dict[str, str]]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. [{a['source']}] {a['title']}\n   {a['summary']}\n   {a['link']}")
    articles_text = "\n".join(lines)

    return (
        "你是一位 AI 领域编辑。请从下面候选新闻中，筛选 3-5 条当天最有价值的信息，"
        "重点侧重「AI coding / 编程智能体」和「具身智能 / 机器人」两个方向。"
        "对每条信息用中文简要说明：1）事件内容；2）值得关注的原因。"
        "输出 markdown 格式，标题为「AI 日报 - YYYY-MM-DD」。不要包含原文全部内容。\n\n"
        f"候选新闻：\n{articles_text}"
    )


def call_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={Config.LLM_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048},
    }
    resp = http_post(url, payload, timeout=60)
    try:
        return resp["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini response parse error: {e}\n{json.dumps(resp, ensure_ascii=False)}")


def call_siliconflow(prompt: str) -> str:
    url = "https://api.siliconflow.cn/v1/chat/completions"
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 2048,
    }
    headers = {"Authorization": f"Bearer {Config.LLM_API_KEY}"}
    resp = http_post(url, payload, headers, timeout=60)
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"SiliconFlow response parse error: {e}\n{json.dumps(resp, ensure_ascii=False)}")


def summarize(articles: list[dict[str, str]]) -> str:
    prompt = build_prompt(articles)
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


def send_lark_markdown(token: str, content: str) -> dict[str, Any]:
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    params = urllib.parse.urlencode({"receive_id_type": "open_id"})
    full_url = f"{url}?{params}"
    payload = {
        "receive_id": Config.LARK_USER_OPEN_ID,
        "msg_type": "interactive",
        "content": json.dumps({
            "config": {"wide_screen_mode": True},
            "elements": [{
                "tag": "markdown",
                "content": content,
            }],
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
    digest = summarize(filtered[:30])

    print("[INFO] Sending Lark message...")
    token = get_lark_token()
    result = send_lark_markdown(token, digest)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("code") != 0:
        raise RuntimeError(f"Lark send failed: {result}")

    print("[INFO] Done.")


if __name__ == "__main__":
    main()
