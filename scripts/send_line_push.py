"""
每交易日 9:30 AM ET 透過 LINE Messaging API 推送文字股票總覽。
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
SIGNAL_LABEL = {"green": "賣Put", "red": "賣Call", "orange": "觀察", "gray": "中立"}


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


def build_text_message(watchlist: dict, signals: dict, etf_prices: dict, now: datetime) -> str:
    lines = [f"📈 Stock Dashboard", f"{now.strftime('%Y/%m/%d %H:%M ET')}", ""]

    for theme, tickers in watchlist.items():
        lines.append(f"【{theme}】")
        for ticker in tickers:
            if ticker in NO_SIGNAL_TICKERS:
                p = etf_prices.get(ticker, {})
                price_str = f"${p['price']:.2f}" if p.get("price") else "—"
                chg_str = f"{p['chg']:+.2f}%" if p.get("chg") else ""
                lines.append(f"  ⚪ {ticker}  {price_str} {chg_str}  ETF")
            elif ticker in signals:
                d = signals[ticker]
                sig = d["signal"]
                emoji = SIGNAL_EMOJI[sig.color]
                label = SIGNAL_LABEL[sig.color]
                lines.append(f"  {emoji} {ticker}  ${d['price']:.1f} {d['chg']:+.1f}%  {label}")
        lines.append("")

    lines.append("輸入股票代碼查看新聞分析（例：NVDA）")
    return "\n".join(lines)


def send_text(token: str, user_id: str, text: str) -> bool:
    r = requests.post(
        LINE_PUSH_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"to": user_id, "messages": [{"type": "text", "text": text}]},
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
    text = build_text_message(watchlist, signals, etf_prices, now)
    ok = send_text(token, user_id, text)
    print(f"LINE text push {'✓' if ok else '✗'}")


if __name__ == "__main__":
    main()
