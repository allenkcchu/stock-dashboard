import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or len(df) < 30:
        return df

    close = df["Close"]

    rsi = RSIIndicator(close=close, window=14)
    df["rsi"] = rsi.rsi()

    macd = MACD(close=close)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_diff"] = macd.macd_diff()

    bb = BollingerBands(close=close, window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_mid"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()

    return df


def last_values(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    row = df.iloc[-1]
    return {
        "rsi": row.get("rsi"),
        "macd_diff": row.get("macd_diff"),
        "bb_upper": row.get("bb_upper"),
        "bb_mid": row.get("bb_mid"),
        "bb_lower": row.get("bb_lower"),
        "close": row.get("Close"),
    }
