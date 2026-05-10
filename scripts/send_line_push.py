"""
每交易日 9:30 AM ET 透過 LINE Messaging API 推送 Flex Message 股票總覽。
需要環境變數：LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytz
import requests
import yfinance as yf
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from indicators.compute import compute_indicators, last_values
from signals.rules import evaluate
from config import NO_SIGNAL_TICKERS

WATCHLIST_FILE = Path(__file__).parent.parent / "watchlist.json"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
ET = pytz.timezone("America/New_York")

SIGNAL_EMOJI = {"green": "🟢", "red": "🔴", "orange": "🟡", "gray": "⚪"}
THEME_COLORS = {
    "Positions":      "#2d5a8e",
    "AI Chips":       "#6b21a8",
    "Data Center":    "#1a6b4a",
    "Energy/Nuclear": "#92400e",
    "Defense":        "#7f1d1d",
}


def is_market_open_window() -> bool:
    now = datetime.now(ET)
    return now.weekday() < 5 and now.hour == 9 and 20 <= now.minute <= 59


def fetch_signals(tickers: list) -> dict:
    result = {}
    try:
        data = yf.download(tickers, period="3mo", auto_adjust=True, progress=False)
        for ticker in tickers:
            try:
                df = (data.xs(ticker, axis=1, level=1).copy()
                      if isinstance(data.columns, pd.MultiIndex) else data.copy())
                df = compute_indicators(df)
                vals = last_values(df)
                sig = evaluate(vals)
                closes = df["Close"].dropna()
                price = float(closes.iloc[-1])
                chg = float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100)
                result[ticker] = {"signal": sig, "price": price, "chg": chg}
            except Exception as e:
                print(f"  {ticker}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Download error: {e}", file=sys.stderr)
    return result


def build_stock_row(ticker: str, data: dict) -> dict:
    sig = data["signal"]
    emoji = SIGNAL_EMOJI[sig.color]
    price_str = f"${data['price']:.1f}"
    chg_str = f"{data['chg']:+.1f}%"
    label_map = {"green": "賣 Put", "red": "賣 Call", "orange": "觀察", "gray": "中立"}
    label = label_map[sig.color]
    return {
        "type": "box",
        "layout": "horizontal",
        "alignItems": "center",
        "margin": "xs",
        "contents": [
            {
                "type": "text",
                "text": f"{emoji} {ticker}  {price_str} {chg_str}  {label}",
                "size": "xxs",
                "flex": 6,
                "wrap": False,
                "adjustMode": "shrink-to-fit",
                "color": "#ffffff",
            },
            {
                "type": "button",
                "action": {
                    "type": "postback",
                    "label": "新聞",
                    "data": f"ticker={ticker}",
                },
                "height": "sm",
                "style": "secondary",
                "flex": 2,
                "color": "#555555",
            },
        ],
    }


def build_etf_row(ticker: str, data: dict) -> dict:
    price_str = f"${data['price']:.2f}" if data.get("price") else "—"
    chg_str = f"{data['chg']:+.2f}%" if data.get("chg") else ""
    return {
        "type": "text",
        "text": f"⚪ {ticker}  {price_str} {chg_str}  ETF",
        "size": "xxs",
        "color": "#aaaaaa",
        "margin": "xs",
    }


def build_theme_bubble(theme: str, tickers: list, signals: dict, prices: dict) -> dict:
    color = THEME_COLORS.get(theme, "#333333")
    rows = []
    for ticker in tickers:
        if ticker in NO_SIGNAL_TICKERS:
            p = prices.get(ticker, {})
            rows.append(build_etf_row(ticker, p))
        elif ticker in signals:
            rows.append(build_stock_row(ticker, signals[ticker]))

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": color,
            "paddingAll": "sm",
            "contents": [
                {"type": "text", "text": theme, "color": "#ffffff", "weight": "bold", "size": "sm"}
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1e2130",
            "paddingAll": "sm",
            "spacing": "none",
            "contents": rows,
        },
    }


def build_header_bubble(now: datetime) -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0e1117",
            "paddingAll": "md",
            "contents": [
                {"type": "text", "text": "📈 Stock Dashboard", "color": "#ffffff", "weight": "bold", "size": "lg"},
                {"type": "text", "text": now.strftime("%Y/%m/%d %H:%M ET"), "color": "#aaaaaa", "size": "xs", "margin": "sm"},
            ],
        },
    }


def send_flex(token: str, user_id: str, bubbles: list, alt_text: str) -> bool:
    payload = {
        "to": user_id,
        "messages": [{
            "type": "flex",
            "altText": alt_text,
            "contents": {"type": "carousel", "contents": bubbles},
        }],
    }
    r = requests.post(
        LINE_PUSH_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    if r.status_code != 200:
        print(f"LINE push error: {r.status_code} {r.text}", file=sys.stderr)
    return r.status_code == 200


def main():
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    if not token or not user_id:
        print("LINE_CHANNEL_ACCESS_TOKEN or LINE_USER_ID not set", file=sys.stderr)
        sys.exit(1)

    if not is_market_open_window() and os.environ.get("FORCE_SEND") != "true":
        now = datetime.now(ET)
        print(f"Not in market open window ({now.strftime('%H:%M ET')}), skipping")
        sys.exit(0)

    with open(WATCHLIST_FILE, encoding="utf-8") as f:
        wl_data = json.load(f)

    watchlist = wl_data["watchlist"]
    signal_tickers = [t for tickers in watchlist.values() for t in tickers if t not in NO_SIGNAL_TICKERS]
    etf_tickers = list(NO_SIGNAL_TICKERS)

    print(f"Fetching {len(signal_tickers)} tickers...")
    signals = fetch_signals(signal_tickers)

    # fetch ETF prices separately
    etf_prices = {}
    try:
        for t in etf_tickers:
            hist = yf.Ticker(t).history(period="2d")
            if len(hist) >= 2:
                p = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                etf_prices[t] = {"price": p, "chg": (p - prev) / prev * 100}
    except Exception:
        pass

    now = datetime.now(ET)
    bubbles = [build_header_bubble(now)]
    for theme, tickers in watchlist.items():
        all_prices = {**{t: {"price": signals[t]["price"], "chg": signals[t]["chg"]}
                        for t in tickers if t in signals}, **etf_prices}
        bubble = build_theme_bubble(theme, tickers, signals, all_prices)
        bubbles.append(bubble)

    alt = f"Stock Dashboard {now.strftime('%Y/%m/%d')} - 點選個股「新聞」查看詳細分析"
    ok = send_flex(token, user_id, bubbles, alt)
    print(f"LINE Flex push {'✓' if ok else '✗'}")


if __name__ == "__main__":
    main()
