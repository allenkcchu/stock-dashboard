import json
import math
from datetime import datetime
import pytz
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from config import NO_SIGNAL_TICKERS, WATCHLIST_FILE
from data.fetcher import get_history, get_info, get_financials, get_news, get_atm_iv, batch_last_price
from indicators.compute import compute_indicators, last_values
from signals.rules import evaluate
from ai.analyzer import analyze_news

st.set_page_config(page_title="Stock Dashboard", layout="wide", page_icon="📈")

ET = pytz.timezone("America/New_York")

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


def market_status() -> tuple[str, str]:
    now = datetime.now(ET)
    time_str = now.strftime("%m/%d %H:%M ET")
    if now.weekday() >= 5:
        return "closed", time_str
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if open_t <= now <= close_t:
        return "open", time_str
    elif now < open_t:
        return "pre", time_str
    return "after", time_str


def news_time(n: dict) -> str:
    ts = n.get("providerPublishTime")
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=pytz.utc).astimezone(ET)
        return dt.strftime("%m/%d %H:%M ET")
    pub = n.get("content", {}).get("pubDate", "")
    return pub[:16] if pub else ""


SIGNAL_EMOJI = {"green": "🟢", "red": "🔴", "orange": "🟡", "gray": "⚪"}
SENTIMENT_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}


def _dark_layout(fig, height: int = 300):
    fig.update_layout(
        height=height, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        font=dict(color="#fafafa"), margin=dict(l=0, r=0, t=20, b=0),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor="#1e2130")
    fig.update_yaxes(gridcolor="#1e2130")

# ---------- pages ----------

def page_overview(wl: dict):
    st.title("📈 Stock Dashboard")

    # market status bar
    status, time_str = market_status()
    status_map = {
        "open":  ("🟢 市場開盤中", "#1a9e5c"),
        "pre":   ("🟡 盤前", "#e07b00"),
        "after": ("🔴 盤後", "#555"),
        "closed":("⚫ 週末休市", "#555"),
    }
    label, color = status_map[status]
    st.markdown(
        f'<div style="background:{color};padding:6px 14px;border-radius:6px;'
        f'color:white;font-size:0.85rem;display:inline-block">'
        f'{label} &nbsp;·&nbsp; {time_str}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("")

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
                    "Trail PE": "—",
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
            info = get_info(ticker)

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
                "Trail PE": fmt_val(info.get("trailingPE"), 1),
                "RSI": fmt_val(rsi, 1),
                "MACD": "金叉" if macd_diff and macd_diff > 0 else ("死叉" if macd_diff else "—"),
                "布林位置": bb_pos(close, bb_upper, bb_lower),
                "IV": f"{iv:.0%}" if iv else "—",
                "訊號": f"{SIGNAL_EMOJI[sig.color]} {sig.label}",
                "理由": " / ".join(sig.reasons) if sig.reasons else "—",
            })

        df_table = pd.DataFrame(rows).set_index("Ticker")
        st.dataframe(df_table, use_container_width=True)

    st.caption("報價快取 15 分鐘 · IV 快取 30 分鐘 · PE 快取 1 小時 · LINE 推播於每交易日 9:30 AM ET")


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

    # signal banner
    if ticker not in NO_SIGNAL_TICKERS:
        sig = evaluate(vals, iv)
        colors = {"green": "#1a9e5c", "red": "#d63333", "orange": "#e07b00", "gray": "#666"}
        st.markdown(
            f'<div style="background:{colors[sig.color]};padding:10px 16px;border-radius:8px;color:white;font-weight:600">'
            f'{SIGNAL_EMOJI[sig.color]} {sig.label} &nbsp;|&nbsp; {" / ".join(sig.reasons) or "無特別訊號"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("")

    # price chart
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

    # fundamentals
    st.subheader("基本面")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Trailing PE", fmt_val(info.get("trailingPE"), 1))
    col2.metric("Forward PE",  fmt_val(info.get("forwardPE"), 1))
    col3.metric("EPS (TTM)",   fmt_val(info.get("trailingEps"), 2))
    mktcap = info.get("marketCap")
    col4.metric("市值", f"${mktcap/1e9:.1f}B" if mktcap else "—")
    col5.metric("Current IV", f"{iv:.0%}" if iv else "—")

    fin = get_financials(ticker)
    rev_row = None
    for row_name in ("Total Revenue", "TotalRevenue", "Revenue"):
        if not fin.empty and row_name in fin.index:
            rev_row = fin.loc[row_name].dropna().sort_index()
            break
    if rev_row is not None and not rev_row.empty:
        rev_df = pd.DataFrame({"Revenue ($B)": rev_row / 1e9})
        st.area_chart(rev_df, color="#6495ed")

    # news + sentiment
    st.subheader("最新新聞")

    def _news_title(n: dict) -> str:
        return n.get("title") or n.get("content", {}).get("title", "")

    def _news_url(n: dict) -> str:
        return (n.get("link") or n.get("url")
                or n.get("content", {}).get("url", "")
                or n.get("content", {}).get("canonicalUrl", {}).get("url", ""))

    valid_news = [n for n in news_raw if _news_title(n)]

    if valid_news:
        headlines = tuple(_news_title(n) for n in valid_news[:5])
        headlines_key = "|".join(headlines)
        with st.spinner("Claude 分析新聞中..."):
            analyzed = analyze_news(ticker, headlines_key, headlines)

        for item, raw in zip(analyzed, valid_news[:5]):
            sentiment = item.get("sentiment", "neutral")
            emoji = SENTIMENT_EMOJI.get(sentiment, "⚪")
            title = item.get("title", "") or _news_title(raw)
            summary = item.get("summary", "")
            reason = item.get("reason", "")
            url = _news_url(raw)
            t_str = news_time(raw)
            header = f"{emoji} [{title}]({url})" if url else f"{emoji} {title}"
            if t_str:
                header += f"  `{t_str}`"

            sentiment_label = {"bullish": "偏多", "bearish": "偏空", "neutral": "中立"}.get(sentiment, "中立")
            with st.expander(header, expanded=True):
                if summary:
                    st.markdown(summary)
                st.markdown(f"**市場看法：{emoji} {sentiment_label}** — {reason}")
    else:
        st.info("暫無新聞")


def page_taiwan():
    from data.taiwan import load_market_data, get_tw_price_history

    st.title("台灣大盤總覽")
    mkt = load_market_data()

    # --- 頂部指標 ---
    twii_df = get_tw_price_history("^TWII", period="5d")
    c1, c2, c3, c4 = st.columns(4)

    if not twii_df.empty and len(twii_df) >= 2:
        last = float(twii_df["Close"].iloc[-1])
        prev = float(twii_df["Close"].iloc[-2])
        chg = (last - prev) / prev * 100
        c1.metric("加權指數", f"{last:,.0f}", f"{chg:+.2f}%")
    else:
        c1.metric("加權指數", "—")

    if not mkt.empty:
        lr = mkt.iloc[-1]
        fini = lr.get("fini_net")
        c2.metric("外資買賣超", f"{fini/1e8:+.1f}億" if fini is not None else "—")
        fut = lr.get("futures_fini_net")
        c3.metric("外資期貨淨口", f"{int(fut):+,}口" if fut is not None else "—")
        pcr = lr.get("pcr_oi")
        if pcr is not None:
            label = "偏空" if pcr > 1.3 else ("偏多" if pcr < 0.7 else "中性")
            c4.metric("PCR (OI)", f"{pcr:.2f}", label)
        else:
            c4.metric("PCR (OI)", "—")
    else:
        c2.metric("外資買賣超", "—")
        c3.metric("外資期貨淨口", "—")
        c4.metric("PCR (OI)", "—")

    st.divider()

    # --- 加權指數 5年走勢 ---
    st.subheader("加權指數 (5年)")
    twii = get_tw_price_history("^TWII", period="5y")
    if not twii.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=twii.index, y=twii["Close"],
            fill="tozeroy", fillcolor="rgba(100,149,237,0.08)",
            line=dict(color="#6495ed", width=1.5), name="TWII",
        ))
        for window, color in [(20, "#f4a261"), (60, "#e07b00"), (240, "#ff6b6b")]:
            ma = twii["Close"].rolling(window).mean()
            fig.add_trace(go.Scatter(x=twii.index, y=ma, name=f"MA{window}",
                                     line=dict(width=1, color=color)))
        _dark_layout(fig, 350)
        st.plotly_chart(fig, use_container_width=True)

    # --- 外部環境 ---
    st.subheader("外部環境")
    col_sox, col_vix = st.columns(2)

    with col_sox:
        st.caption("費半 SOX (5年)")
        sox = get_tw_price_history("^SOX", period="5y")
        if not sox.empty:
            fig = go.Figure(go.Scatter(
                x=sox.index, y=sox["Close"],
                fill="tozeroy", fillcolor="rgba(52,211,153,0.08)",
                line=dict(color="#34d399", width=1.5), name="SOX",
            ))
            _dark_layout(fig, 260)
            st.plotly_chart(fig, use_container_width=True)

    with col_vix:
        st.caption("VIX 波動率 (5年)")
        vix = get_tw_price_history("^VIX", period="5y")
        if not vix.empty:
            bar_colors = [
                "#d63333" if v > 30 else "#f4a261" if v > 20 else "#1a9e5c"
                for v in vix["Close"]
            ]
            fig = go.Figure(go.Bar(x=vix.index, y=vix["Close"],
                                   marker_color=bar_colors, name="VIX"))
            fig.add_hline(y=20, line_dash="dash", line_color="#f4a261", line_width=0.8)
            fig.add_hline(y=30, line_dash="dash", line_color="#d63333", line_width=0.8)
            _dark_layout(fig, 260)
            st.plotly_chart(fig, use_container_width=True)

    # --- 台積電 ---
    st.subheader("台積電 2330.TW (5年)")
    tsmc = get_tw_price_history("2330.TW", period="5y")
    if not tsmc.empty:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            vertical_spacing=0.02, row_heights=[0.75, 0.25])
        fig.add_trace(go.Candlestick(
            x=tsmc.index, open=tsmc["Open"], high=tsmc["High"],
            low=tsmc["Low"], close=tsmc["Close"], name="TSMC",
            increasing_line_color="#1a9e5c", decreasing_line_color="#d63333",
        ), row=1, col=1)
        vol_colors = ["#1a9e5c" if c >= o else "#d63333"
                      for c, o in zip(tsmc["Close"], tsmc["Open"])]
        fig.add_trace(go.Bar(x=tsmc.index, y=tsmc["Volume"],
                             marker_color=vol_colors, showlegend=False), row=2, col=1)
        _dark_layout(fig, 420)
        fig.update_layout(xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    # --- 籌碼資料（需先執行 init 腳本）---
    if mkt.empty or mkt.dropna(how="all").empty:
        st.info(
            "籌碼歷史資料尚未初始化。\n\n"
            "請在本機執行：\n```\ncd stock_dashboard\npython scripts/init_taiwan_data.py\n```\n\n"
            "執行約 15-20 分鐘，之後 GitHub Actions 每日自動更新。"
        )
        return

    # --- 三大法人買賣超 ---
    st.subheader("三大法人買賣超（億元）")
    inst = mkt[["fini_net", "trust_net", "dealer_net"]].dropna(how="all") / 1e8
    if not inst.empty:
        fig = go.Figure()
        for col, name, color in [
            ("fini_net",    "外資",    "#6495ed"),
            ("trust_net",   "投信",    "#1a9e5c"),
            ("dealer_net",  "自營商",  "#f4a261"),
        ]:
            if col in inst.columns:
                fig.add_trace(go.Bar(
                    x=inst.index, y=inst[col], name=name,
                    marker_color=color, opacity=0.85,
                ))
        fig.update_layout(barmode="relative")
        _dark_layout(fig, 300)
        st.plotly_chart(fig, use_container_width=True)

    # --- 外資期貨淨部位 ---
    st.subheader("外資台指期淨部位（口）")
    fut_s = mkt["futures_fini_net"].dropna()
    if not fut_s.empty:
        ma20 = fut_s.rolling(20).mean()
        bar_colors = ["#1a9e5c" if v >= 0 else "#d63333" for v in fut_s]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=fut_s.index, y=fut_s, marker_color=bar_colors,
                             name="淨部位", opacity=0.75))
        fig.add_trace(go.Scatter(x=ma20.index, y=ma20, name="MA20",
                                 line=dict(color="#f4a261", width=1.5)))
        fig.add_hline(y=0, line_color="#ffffff", line_width=0.5)
        _dark_layout(fig, 280)
        st.plotly_chart(fig, use_container_width=True)

    # --- PCR ---
    st.subheader("Put/Call Ratio（未平倉口數）")
    pcr_s = mkt["pcr_oi"].dropna()
    if not pcr_s.empty:
        ma20 = pcr_s.rolling(20).mean()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=pcr_s.index, y=pcr_s, name="PCR OI",
                                 line=dict(color="#a78bfa", width=1.5)))
        fig.add_trace(go.Scatter(x=ma20.index, y=ma20, name="MA20",
                                 line=dict(color="#f4a261", width=1.5, dash="dot")))
        fig.add_hline(y=1.3, line_dash="dash", line_color="#d63333", line_width=1,
                      annotation_text="偏空極端 1.3", annotation_position="right")
        fig.add_hline(y=0.7, line_dash="dash", line_color="#1a9e5c", line_width=1,
                      annotation_text="偏多極端 0.7", annotation_position="right")
        _dark_layout(fig, 280)
        st.plotly_chart(fig, use_container_width=True)

    st.caption("TWSE 三大法人來源：twse.com.tw · TAIFEX 期貨/PCR：taifex.com.tw · 每交易日 18:00 後更新")


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
        ["總覽 Dashboard", "個股詳細", "台灣大盤", "更新紀錄"],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    st.sidebar.caption("資料來源：Yahoo Finance · TWSE · TAIFEX\nAI 分析：Claude Haiku")

    if page == "總覽 Dashboard":
        page_overview(wl)
    elif page == "個股詳細":
        page_detail(wl)
    elif page == "台灣大盤":
        page_taiwan()
    elif page == "更新紀錄":
        page_history(wl)


if __name__ == "__main__":
    main()
