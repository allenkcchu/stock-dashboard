import pandas as pd
import yfinance as yf
import requests
import streamlit as st
from pathlib import Path
from io import StringIO

DATA_PATH = Path(__file__).parent.parent / "taiwan_data" / "market_data.csv"

COLUMNS = [
    "date", "fini_net", "trust_net", "dealer_net",
    "futures_fini_long", "futures_fini_short", "futures_fini_net",
    "pcr_oi", "pcr_vol",
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


@st.cache_data(ttl=3600)
def load_market_data() -> pd.DataFrame:
    if not DATA_PATH.exists():
        return pd.DataFrame(columns=COLUMNS).set_index("date")
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    return df.set_index("date").sort_index()


@st.cache_data(ttl=900)
def get_tw_price_history(ticker: str, period: str = "5y") -> pd.DataFrame:
    try:
        df = yf.Ticker(ticker).history(period=period)
        df.index = df.index.tz_localize(None)
        return df
    except Exception:
        return pd.DataFrame()


def _num(s) -> float | None:
    try:
        return float(str(s).replace(",", "").replace("+", "").strip())
    except Exception:
        return None


def _decode(content: bytes) -> str:
    for enc in ("big5", "cp950", "utf-8-sig", "utf-8"):
        try:
            return content.decode(enc)
        except Exception:
            continue
    return content.decode("big5", errors="ignore")


# ──────────────────────────────────────────────────────────────
# TWSE 三大法人
# ──────────────────────────────────────────────────────────────

def fetch_twse_institutional(date_str: str) -> dict:
    """TWSE BFI82U 三大法人買賣超. date_str: YYYYMMDD. 單位：元.
    外資 = 外資及陸資(不含外資自營商) + 外資自營商.
    """
    result = dict(fini_net=None, trust_net=None, dealer_net=None)
    try:
        r = requests.get(
            "https://www.twse.com.tw/rwd/zh/fund/BFI82U",
            params={"type": "day", "dayDate": date_str, "response": "json"},
            timeout=10, headers=_HEADERS,
        )
        j = r.json()
        if j.get("stat") != "OK" or not j.get("data"):
            return result

        name_net = {}
        for row in j["data"]:
            name = str(row[0]).strip()
            net = _num(row[-1])
            name_net[name] = net

        if "外資及陸資" in name_net:
            result["fini_net"] = name_net["外資及陸資"]
        else:
            fini_sum = sum(v for k, v in name_net.items()
                           if "外資" in k and v is not None)
            result["fini_net"] = fini_sum or None

        result["trust_net"] = name_net.get("投信")

        dealer_sum = sum(v for k, v in name_net.items()
                         if k.startswith("自營商") and v is not None)
        result["dealer_net"] = dealer_sum or None

    except Exception:
        pass
    return result


# ──────────────────────────────────────────────────────────────
# TAIFEX – bulk CSV download (支援歷史日期查詢)
# ──────────────────────────────────────────────────────────────

def _taifex_futures_csv_bulk(start_str: str, end_str: str) -> pd.DataFrame:
    """下載 TAIFEX 台指期三大法人未平倉量 CSV (DateDown endpoint).
    date_str: YYYYMMDD. 回傳 DataFrame indexed by date,
    columns: futures_fini_long, futures_fini_short, futures_fini_net.
    """
    s = f"{start_str[:4]}/{start_str[4:6]}/{start_str[6:8]}"
    e = f"{end_str[:4]}/{end_str[4:6]}/{end_str[6:8]}"
    try:
        r = requests.post(
            "https://www.taifex.com.tw/cht/3/futContractsDateDown",
            data={"queryStartDate": s, "queryEndDate": e, "commodityId": "TXF"},
            timeout=30, headers=_HEADERS,
        )
        content = _decode(r.content)
        df = pd.read_csv(StringIO(content))
        df.columns = [str(c).strip() for c in df.columns]

        fini_mask = (df["商品名稱"].astype(str).str.contains("臺股期貨") &
                     df["身份別"].astype(str).str.contains("外資"))
        df_f = df[fini_mask].copy()
        if df_f.empty:
            return pd.DataFrame()

        df_f["date"] = pd.to_datetime(df_f["日期"].astype(str).str.strip())
        df_f = df_f.set_index("date")

        result = pd.DataFrame(index=df_f.index)
        result["futures_fini_long"]  = pd.to_numeric(df_f["多方未平倉口數"],    errors="coerce")
        result["futures_fini_short"] = pd.to_numeric(df_f["空方未平倉口數"],    errors="coerce")
        result["futures_fini_net"]   = pd.to_numeric(df_f["多空未平倉口數淨額"], errors="coerce")
        return result
    except Exception:
        return pd.DataFrame()


def _taifex_pcr_csv_bulk(start_str: str, end_str: str) -> pd.DataFrame:
    """下載 TAIFEX TXO 選擇權 Put/Call Ratio CSV (DateDown endpoint).
    PCR = 臺指選擇權全機構 賣權買方OI / 買權買方OI.
    回傳 DataFrame indexed by date, columns: pcr_oi, pcr_vol.
    """
    s = f"{start_str[:4]}/{start_str[4:6]}/{start_str[6:8]}"
    e = f"{end_str[:4]}/{end_str[4:6]}/{end_str[6:8]}"
    try:
        r = requests.post(
            "https://www.taifex.com.tw/cht/3/callsAndPutsDateDown",
            data={"queryStartDate": s, "queryEndDate": e},
            timeout=30, headers=_HEADERS,
        )
        content = _decode(r.content)
        df = pd.read_csv(StringIO(content))
        df.columns = [str(c).strip() for c in df.columns]

        df["日期"] = pd.to_datetime(df["日期"].astype(str).str.strip())
        df["買賣權別"] = df["買賣權別"].astype(str).str.strip().str.upper()

        tXO = df[df["商品名稱"].astype(str).str.contains("臺指選擇權")].copy()
        if tXO.empty:
            return pd.DataFrame()

        oi_grp  = tXO.groupby(["日期", "買賣權別"])["買方未平倉口數"].sum()
        vol_grp = tXO.groupby(["日期", "買賣權別"])["買方交易口數"].sum()

        records = []
        for d in oi_grp.index.get_level_values(0).unique():
            call_oi  = oi_grp.get((d, "CALL"),  0) or 0
            put_oi   = oi_grp.get((d, "PUT"),   0) or 0
            call_vol = vol_grp.get((d, "CALL"), 0) or 0
            put_vol  = vol_grp.get((d, "PUT"),  0) or 0
            records.append({
                "date":    d,
                "pcr_oi":  round(put_oi  / call_oi,  4) if call_oi  > 0 else None,
                "pcr_vol": round(put_vol / call_vol, 4) if call_vol > 0 else None,
            })

        return pd.DataFrame(records).set_index("date")
    except Exception:
        return pd.DataFrame()


# ──────────────────────────────────────────────────────────────
# 單日查詢（供 update_taiwan_daily.py 使用）
# ──────────────────────────────────────────────────────────────

def fetch_taifex_futures(date_str: str) -> dict:
    df = _taifex_futures_csv_bulk(date_str, date_str)
    if df.empty:
        return dict(futures_fini_long=None, futures_fini_short=None, futures_fini_net=None)
    row = df.iloc[0]
    return {k: (float(row[k]) if pd.notna(row[k]) else None)
            for k in ["futures_fini_long", "futures_fini_short", "futures_fini_net"]}


def fetch_taifex_pcr(date_str: str) -> dict:
    df = _taifex_pcr_csv_bulk(date_str, date_str)
    if df.empty:
        return dict(pcr_oi=None, pcr_vol=None)
    row = df.iloc[0]
    return {k: (float(row[k]) if pd.notna(row[k]) else None)
            for k in ["pcr_oi", "pcr_vol"]}


def fetch_all(date_str: str) -> dict:
    """單日抓取所有台灣市場籌碼資料. date_str: YYYYMMDD."""
    data = {"date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"}
    data.update(fetch_twse_institutional(date_str))
    data.update(fetch_taifex_futures(date_str))
    data.update(fetch_taifex_pcr(date_str))
    return data
