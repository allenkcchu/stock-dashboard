"""
每週自動更新追蹤清單。由 GitHub Actions 執行。
需要環境變數：ANTHROPIC_API_KEY
"""
import json
import os
import sys
from datetime import datetime, timezone

import anthropic
import feedparser

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "..", "watchlist.json")

RSS_FEEDS = [
    "https://finance.yahoo.com/rss/topstories",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
]


def fetch_headlines(limit: int = 30) -> list[str]:
    headlines = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if entry.get("title"):
                    headlines.append(entry.title)
        except Exception as e:
            print(f"RSS fetch failed for {url}: {e}", file=sys.stderr)
    return headlines[:limit]


def analyze_with_claude(current_watchlist: dict, headlines: list[str]) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    wl_json = json.dumps(current_watchlist, ensure_ascii=False, indent=2)
    headlines_text = "\n".join(f"- {h}" for h in headlines)

    prompt = f"""你是一位資深股票分析師，負責每週審查追蹤清單。

目前追蹤清單：
{wl_json}

本週財經新聞標題（各大媒體 RSS）：
{headlines_text}

請根據新聞判斷：
1. 有哪些新的重要產業趨勢尚未在清單中？需要新增哪些股票？
2. 有哪些股票因趨勢反轉或利空而應移除？
3. 保守原則：只有明確證據才建議調整

回傳格式（只回 JSON，不要任何其他文字）：
{{
  "changes": {{
    "added": {{}},
    "removed": {{}}
  }},
  "reasoning": "繁體中文一段說明，包含本週重要趨勢以及調整理由（若無調整也請說明原因）"
}}

範例（有調整）：
{{
  "changes": {{
    "added": {{"Robotics": ["ABB", "FANUY"]}},
    "removed": {{"Defense": ["NOC"]}}
  }},
  "reasoning": "本週新聞顯示機器人自動化需求激增..."
}}

範例（無調整）：
{{
  "changes": {{"added": {{}}, "removed": {{}}}},
  "reasoning": "本週產業趨勢與現有清單吻合，各主題仍為市場焦點，無需調整。"
}}"""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system="你是專業股票分析師，負責每週審查股票追蹤清單。只輸出 JSON，不要其他文字。",
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
    return json.loads(text)


def apply_changes(wl_data: dict, result: dict) -> bool:
    changes = result.get("changes", {})
    added = changes.get("added", {})
    removed = changes.get("removed", {})
    reasoning = result.get("reasoning", "")
    modified = False

    for theme, tickers in added.items():
        if theme not in wl_data["watchlist"]:
            wl_data["watchlist"][theme] = []
        for t in tickers:
            if t not in wl_data["watchlist"][theme]:
                wl_data["watchlist"][theme].append(t)
                modified = True

    for theme, tickers in removed.items():
        if theme in wl_data["watchlist"]:
            for t in tickers:
                if t in wl_data["watchlist"][theme]:
                    wl_data["watchlist"][theme].remove(t)
                    modified = True
            if not wl_data["watchlist"][theme]:
                del wl_data["watchlist"][theme]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    wl_data["history"].append({
        "date": today,
        "action": "update",
        "changes": {"added": added, "removed": removed},
        "reasoning": reasoning,
    })

    return modified


def main():
    with open(WATCHLIST_FILE, encoding="utf-8") as f:
        wl_data = json.load(f)

    print("抓取新聞標題...")
    headlines = fetch_headlines()
    if not headlines:
        print("無法取得新聞，跳過更新", file=sys.stderr)
        sys.exit(0)

    print(f"取得 {len(headlines)} 則標題，送 Claude 分析...")
    result = analyze_with_claude(wl_data["watchlist"], headlines)

    modified = apply_changes(wl_data, result)

    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(wl_data, f, ensure_ascii=False, indent=2)

    print(f"分析完成：{result.get('reasoning', '')}")
    print(f"清單{'已更新' if modified else '無變動'}，history 已寫入")


if __name__ == "__main__":
    main()
