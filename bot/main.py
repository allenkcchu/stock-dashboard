import asyncio
import base64
import hmac
import hashlib
import json
import os
from datetime import datetime

import anthropic
import httpx
import pandas as pd
import pytz
import ta
import yfinance as yf
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
ET = pytz.timezone("America/New_York")
WATCHLIST_URL = "https://raw.githubusercontent.com/allenkcchu/stock-dashboard/master/watchlist.json"
NO_SIGNAL_TICKERS = {"SGOV"}


def verify_signature(body: bytes, signature: str) -> bool:
    digest = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


async def push_text(user_id: str, text: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            LINE_PUSH_URL,
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            timeout=15,
        )


def _news_title(n: dict) -> str:
    return n.get("title") or n.get("content", {}).get("title", "")


def _news_url(n: dict) -> str:
    return (n.get("link") or n.get("url")
            or n.get("content", {}).get("url", "")
            or n.get("content", {}).get("canonicalUrl", {}).get("url", ""))


def _news_time(n: dict) -> str:
    ts = n.get("providerPublishTime")
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=pytz.utc).astimezone(ET)
        return dt.strftime("%m/%d %H:%M ET")
    return ""


def _simple_signal(closes: pd.Series) -> tuple[str, str]:
    rsi = ta.momentum.RSIIndicator(closes, window=14).rsi().dropna()
    if rsi.empty:
        return "⚪", "中立"
    v = float(rsi.iloc[-1])
    if v < 35:
        return "🟢", "賣Put"
    if v > 65:
        return "🔴", "賣Call"
    return "⚪", "中立"


def build_daily_summary() -> str:
    r = httpx.get(WATCHLIST_URL, timeout=10)
    watchlist = r.json()["watchlist"]

    all_tickers = [t for ts in watchlist.values() for t in ts]
    signal_tickers = [t for t in all_tickers if t not in NO_SIGNAL_TICKERS]

    data = yf.download(all_tickers, period="3mo", auto_adjust=True, progress=False)

    results = {}
    for ticker in all_tickers:
        try:
            closes = (data["Close"][ticker] if isinstance(data.columns, pd.MultiIndex)
                      else data["Close"]).dropna()
            price = float(closes.iloc[-1])
            chg = float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100)
            results[ticker] = {"price": price, "chg": chg, "closes": closes}
        except Exception:
            pass

    now = datetime.now(ET)
    lines = ["📈 Stock Dashboard", now.strftime("%Y/%m/%d %H:%M ET"), ""]

    for theme, tickers in watchlist.items():
        lines.append(f"【{theme}】")
        for ticker in tickers:
            d = results.get(ticker)
            if not d:
                lines.append(f"  ⚪ {ticker}  —")
                continue
            price_str = f"${d['price']:.1f}"
            chg_str = f"{d['chg']:+.1f}%"
            if ticker in NO_SIGNAL_TICKERS:
                lines.append(f"  ⚪ {ticker}  {price_str} {chg_str}  ETF")
            else:
                emoji, label = _simple_signal(d["closes"])
                lines.append(f"  {emoji} {ticker}  {price_str} {chg_str}  {label}")
        lines.append("")

    lines.append("輸入股票代碼查看新聞分析（例：NVDA）")
    return "\n".join(lines)


def get_news_analysis(ticker: str) -> str:
    try:
        news_raw = yf.Ticker(ticker).news or []
        valid = [n for n in news_raw if _news_title(n)][:5]
        if not valid:
            return f"⚠️ {ticker} 暫無新聞資料"

        headlines = [_news_title(n) for n in valid]
        bullet = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = f"""你是股票分析師。針對 {ticker}，分析以下新聞標題：

{bullet}

每則新聞請提供：
1. 3句繁體中文摘要
2. 市場看法（偏多/偏空/中立）及一句理由

只回傳 JSON 陣列（不要其他文字）：
[{{"title":"原標題","summary":"摘要","sentiment":"bullish|bearish|neutral","reason":"理由"}}]"""

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        analyzed = json.loads(text)

        emoji_map = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
        label_map = {"bullish": "偏多", "bearish": "偏空", "neutral": "中立"}

        lines = [f"📰 {ticker} 新聞分析\n"]
        for item, raw in zip(analyzed, valid):
            e = emoji_map.get(item.get("sentiment", "neutral"), "⚪")
            label = label_map.get(item.get("sentiment", "neutral"), "中立")
            t_str = _news_time(raw)
            url = _news_url(raw)
            lines.append(f"▍{item.get('title', '')}")
            if t_str:
                lines.append(f"  🕐 {t_str}")
            lines.append(f"  {item.get('summary', '')}")
            lines.append(f"  {e} {label} — {item.get('reason', '')}")
            if url:
                lines.append(f"  🔗 {url}")
            lines.append("")

        return "\n".join(lines).strip()

    except Exception as e:
        return f"⚠️ {ticker} 分析失敗：{e}"


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    if not verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(body)
    for event in data.get("events", []):
        user_id = event.get("source", {}).get("userId", "")
        ticker = ""

        if event.get("type") == "postback":
            params = dict(x.split("=") for x in event["postback"]["data"].split("&") if "=" in x)
            ticker = params.get("ticker", "").upper()
        elif event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            text = event["message"]["text"].strip()
            if text == "每日摘要":
                summary = await asyncio.to_thread(build_daily_summary)
                await push_text(user_id, summary)
                continue
            upper = text.upper()
            if upper.isalpha() and 1 <= len(upper) <= 6:
                ticker = upper

        if ticker and user_id:
            analysis = await asyncio.to_thread(get_news_analysis, ticker)
            await push_text(user_id, analysis)

    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}
