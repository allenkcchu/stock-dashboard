"""
每日更新腳本：抓取最新一個交易日的台灣市場籌碼資料。
由 GitHub Actions 在台灣時間 18:00 後自動觸發。
"""

import sys
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from data.taiwan import fetch_all, COLUMNS, DATA_PATH


def last_trading_day(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def main():
    target = last_trading_day(date.today() - timedelta(days=1))
    date_str = target.strftime("%Y%m%d")
    iso = target.isoformat()

    DATA_PATH.parent.mkdir(exist_ok=True)

    existing = set()
    if DATA_PATH.exists():
        try:
            df = pd.read_csv(DATA_PATH)
            existing = set(df["date"].astype(str))
        except Exception:
            pass

    if iso in existing:
        print(f"{iso} 已存在，略過。")
        return

    row = fetch_all(date_str)
    vals = [row.get(k) for k in COLUMNS[1:]]
    if all(v is None for v in vals):
        print(f"{iso} 無資料（假日或 API 錯誤）。")
        return

    frames = []
    if DATA_PATH.exists():
        try:
            frames.append(pd.read_csv(DATA_PATH))
        except Exception:
            pass
    frames.append(pd.DataFrame([row], columns=COLUMNS))
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["date"]).sort_values("date")
    df.to_csv(DATA_PATH, index=False)

    print(
        f"更新 {iso}：外資={row.get('fini_net')} 千元  "
        f"期貨淨口={row.get('futures_fini_net')}  "
        f"PCR={row.get('pcr_oi')}"
    )


if __name__ == "__main__":
    main()
