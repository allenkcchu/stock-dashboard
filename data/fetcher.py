import yfinance as yf
import streamlit as st
import pandas as pd


@st.cache_data(ttl=900)
def get_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    try:
        df = yf.Ticker(ticker).history(period=period)
        df.index = df.index.tz_localize(None)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=900)
def get_info(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # fast_info 補充缺失的欄位
        try:
            fi = t.fast_info
            if not info.get("marketCap"):
                info["marketCap"] = getattr(fi, "market_cap", None)
            if not info.get("currentPrice"):
                info["currentPrice"] = getattr(fi, "last_price", None)
        except Exception:
            pass

        return info
    except Exception:
        return {}


@st.cache_data(ttl=900)
def get_financials(ticker: str) -> pd.DataFrame:
    t = yf.Ticker(ticker)
    for attr in ("income_stmt", "financials"):
        try:
            df = getattr(t, attr)
            if df is not None and not df.empty:
                return df
        except Exception:
            continue
    return pd.DataFrame()


@st.cache_data(ttl=900)
def get_news(ticker: str) -> list:
    try:
        return yf.Ticker(ticker).news or []
    except Exception:
        return []


@st.cache_data(ttl=1800)
def get_atm_iv(ticker: str) -> float | None:
    try:
        t = yf.Ticker(ticker)
        exps = t.options
        if not exps:
            return None
        chain = t.option_chain(exps[0])
        fi = t.fast_info
        price = getattr(fi, "last_price", None)
        if not price:
            info = t.info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price:
            return None
        calls = chain.calls.dropna(subset=["impliedVolatility"])
        if calls.empty:
            return None
        idx = (calls["strike"] - price).abs().idxmin()
        return float(calls.loc[idx, "impliedVolatility"])
    except Exception:
        return None


@st.cache_data(ttl=900)
def batch_last_price(tickers: tuple) -> dict:
    result = {}
    try:
        data = yf.download(list(tickers), period="2d", auto_adjust=True, progress=False)
        close = data["Close"] if "Close" in data.columns else data.xs("Close", axis=1, level=0)
        for t in tickers:
            try:
                series = close[t].dropna()
                if len(series) >= 2:
                    result[t] = {
                        "price": float(series.iloc[-1]),
                        "prev": float(series.iloc[-2]),
                        "chg_pct": float((series.iloc[-1] - series.iloc[-2]) / series.iloc[-2] * 100),
                    }
            except Exception:
                pass
    except Exception:
        pass
    return result
