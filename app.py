import json
import math
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from config import NO_SIGNAL_TICKERS, WATCHLIST_FILE
from data.fetcher import get_history, get_info, get_news, get_atm_iv, batch_last_price
from indicators.compute import compute_indicators, last_values
from signals.rules import evaluate
from ai.analyzer import analyze_news

st.set_page_config(page_title="Stock Dashboard", layout="wide", page_icon="📈")

# ---------- helpers ----------

def load_watchlist():
    with open(WATCHLIST_FILE, encoding="utf-8") as f:
        return json.load(f)


def all_tickers(wl: dict) -> list:
    return [t for tickers in wl["watchlist"].values() for t in tickers]


def fmt_pct(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:+.2f}%"


def fmt_val(v, decimals=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.{decimals}f}"


SIGNAL_EMOJI = {
    "green": "🟢",
    "red": "🔴",
    "orange": "🟡",
    "gray": "⚪",
}

SENTIMENT_EMOJI = {
    "bullish": "🟢",
    "bearish": "🔴",
    "neutral": "⚪",
}

# ---------- pages ----------

def page_overview(wl: dict):
    st.title("📈 Stock Dashboard")

    tickers_tuple = tuple(all_tickers(wl))
    with st.spinner("載入報價中..."):
        prices = batch_last_price(tickers_tuple)

    for theme, tickers in wl["watchlist"].items():
        st.subheader(theme)
        rows = []
        for ticker in tickers:
            p = prices.get(ticker, {})
            price = p.get("price")
            chg = p.get("chg_pct")

            if ticker in NO_SIGNAL_TICKERS:
                rows.append({
                    "Ticker": ticker,
                    "價格": fmt_val(price),
                    "漲跌%": fmt_pct(chg),
                    "RSI": "—",
                    "MACD": "—",
                    "布林位置": "—",
                    "IV": "—",
                    "訊號": "⚪ ETF",
                    "理由": "無訊號分析",
                })
                continue

            df = get_history(ticker)
            df = compute_indicators(df)
            vals = last_values(df)
            iv = get_atm_iv(ticker)
            sig = evaluate(vals, iv)

            rsi = vals.get("rsi")
            macd_diff = vals.get("macd_diff")
            close = vals.get("close")
            bb_upper = vals.get("bb_upper")
            bb_lower = vals.get("bb_lower")

            def bb_pos(c, u, l):
                if not all([c, u, l]):
                    return "—"
                if c >= u * 0.98:
                    return "上軌附近"
                elif c <= l * 1.02:
                    return "下軌附近"
                return "中間"

            rows.append({
                "Ticker": ticker,
                "價格": fmt_val(price),
                "漲跌%": fmt_pct(chg),
                "RSI": fmt_val(rsi, 1),
                "MACD": "金叉" if macd_diff and macd_diff > 0 else ("死叉" if macd_diff else "—"),
                "布林位置": bb_pos(close, bb_upper, bb_lower),
                "IV": f"{iv:.0%}" if iv else "—",
                "訊號": f"{SIGNAL_EMOJI[sig.color]} {sig.label}",
                "理由": " / ".join(sig.reasons) if sig.reasons else "—",
            })

        df_table = pd.DataFrame(rows).set_index("Ticker")
        st.dataframe(df_table, use_container_width=True)

    st.caption(f"資料每 15 分鐘更新一次 · IV 每 30 分鐘更新")

    st.divider()
    if st.button("查看個股詳細 →", help="在側邊欄選擇頁面"):
        st.info("請從左側選單切換到「個股詳細」")


def page_detail(wl: dict):
    st.title("個股詳細分析")

    tickers = all_tickers(wl)
    ticker = st.selectbox("選擇股票", tickers)
    if not ticker:
        return

    with st.spinner(f"載入 {ticker} 資料..."):
        df = get_history(ticker, period="1y")
        df = compute_indicators(df)
        info = get_info(ticker)
        news_raw = get_news(ticker)
        iv = None if ticker in NO_SIGNAL_TICKERS else get_atm_iv(ticker)

    if df.empty:
        st.error("無法取得資料")
        return

    vals = last_values(df)

    # --- signal banner ---
    if ticker not in NO_SIGNAL_TICKERS:
        sig = evaluate(vals, iv)
        colors = {"green": "#1a9e5c", "red": "#d63333", "orange": "#e07b00", "gray": "#666"}
        st.markdown(
            f'<div style="background:{colors[sig.color]};padding:10px 16px;border-radius:8px;color:white;font-weight:600">'
            f'{SIGNAL_EMOJI[sig.color]} {sig.label} &nbsp;|&nbsp; {" / ".join(sig.reasons) or "無特別訊號"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("")

    # --- price chart ---
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.50, 0.15, 0.175, 0.175],
        subplot_titles=("價格 + 布林帶", "成交量", "RSI (14)", "MACD"),
    )

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="K線",
        increasing_line_color="#1a9e5c", decreasing_line_color="#d63333",
    ), row=1, col=1)

    for col, color, fill in [
        ("bb_upper", "rgba(100,149,237,0.3)", None),
        ("bb_mid",   "rgba(100,149,237,0.6)", None),
        ("bb_lower", "rgba(100,149,237,0.3)", "tonexty"),
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col], name=col,
                line=dict(color=color, width=1),
                fill=fill, fillcolor="rgba(100,149,237,0.05)",
                showlegend=False,
            ), row=1, col=1)

    colors_vol = ["#1a9e5c" if c >= o else "#d63333" for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume",
                         marker_color=colors_vol, showlegend=False), row=2, col=1)

    if "rsi" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["rsi"], name="RSI",
                                 line=dict(color="#f4a261", width=1.5)), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", line_width=0.8, row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", line_width=0.8, row=3, col=1)

    if "macd" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["macd"], name="MACD",
                                 line=dict(color="#6495ed", width=1.5)), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["macd_signal"], name="Signal",
                                 line=dict(color="#f4a261", width=1.5)), row=4, col=1)
        hist_colors = ["#1a9e5c" if v >= 0 else "#d63333" for v in df["macd_diff"].fillna(0)]
        fig.add_trace(go.Bar(x=df.index, y=df["macd_diff"], name="Histogram",
                             marker_color=hist_colors, showlegend=False), row=4, col=1)

    fig.update_layout(
        height=700, xaxis_rangeslider_visible=False,
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        font=dict(color="#fafafa"), margin=dict(l=0, r=0, t=30, b=0),
    )
    fig.update_xaxes(gridcolor="#1e2130")
    fig.update_yaxes(gridcolor="#1e2130")
    st.plotly_chart(fig, use_container_width=True)

    # --- fundamentals ---
    st.subheader("基本面")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Trailing PE", fmt_val(info.get("trailingPE"), 1))
    col2.metric("Forward PE",  fmt_val(info.get("forwardPE"), 1))
    col3.metric("EPS (TTM)",   fmt_val(info.get("trailingEps"), 2))
    mktcap = info.get("marketCap")
    col4.metric("市值", f"${mktcap/1e9:.1f}B" if mktcap else "—")
    col5.metric("Current IV", f"{iv:.0%}" if iv else "—")

    # revenue trend
    try:
        t_obj = __import__("yfinance").Ticker(ticker)
        fin = t_obj.financials
        if fin is not None and not fin.empty and "Total Revenue" in fin.index:
            rev = fin.loc["Total Revenue"].dropna().sort_index()
            rev_df = pd.DataFrame({"Revenue ($B)": rev / 1e9})
            st.area_chart(rev_df, color="#6495ed")
    except Exception:
        pass

    # --- news + sentiment ---
    st.subheader("最新新聞")
    if news_raw:
        headlines = tuple(n.get("title", "") for n in news_raw[:5] if n.get("title"))
        headlines_key = "|".join(headlines)
        with st.spinner("Gemini 分析新聞情緒中..."):
            analyzed = analyze_news(ticker, headlines_key, headlines)

        for item in analyzed:
            emoji = SENTIMENT_EMOJI.get(item.get("sentiment", "neutral"), "⚪")
            title = item.get("title", "")
            reason = item.get("reason", "")
            url = next((n.get("link", "") for n in news_raw if n.get("title") == title), "")
            link = f"[{title}]({url})" if url else title
            st.markdown(f"{emoji} {link}  \n&nbsp;&nbsp;&nbsp;&nbsp;_{reason}_")
    else:
        st.info("暫無新聞")


def page_history(wl: dict):
    st.title("追蹤清單更新紀錄")
    history = wl.get("history", [])
    if not history:
        st.info("尚無更新紀錄")
        return

    for entry in reversed(history):
        date = entry.get("date", "")
        action = entry.get("action", "")
        reasoning = entry.get("reasoning", "")
        changes = entry.get("changes", {})

        with st.expander(f"{date}  ·  {'初始建立' if action == 'init' else '更新'}", expanded=(action == "init")):
            st.markdown(f"**理由：** {reasoning}")
            added = changes.get("added", {})
            removed = changes.get("removed", {})
            if added:
                st.markdown("**新增：**")
                for theme, tickers in added.items():
                    st.markdown(f"- {theme}: {', '.join(tickers)}")
            if removed:
                st.markdown("**移除：**")
                for theme, tickers in removed.items():
                    st.markdown(f"- {theme}: {', '.join(tickers)}")


# ---------- main ----------

def main():
    wl = load_watchlist()

    page = st.sidebar.radio(
        "選單",
        ["總覽 Dashboard", "個股詳細", "更新紀錄"],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    st.sidebar.caption("資料來源：Yahoo Finance\nAI 分析：Google Gemini")

    if page == "總覽 Dashboard":
        page_overview(wl)
    elif page == "個股詳細":
        page_detail(wl)
    elif page == "更新紀錄":
        page_history(wl)


if __name__ == "__main__":
    main()
