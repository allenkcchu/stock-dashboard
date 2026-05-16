"""
一次性初始化腳本：抓取近 5 年的台灣市場籌碼資料。
- TWSE 三大法人：逐日抓取（~1250 次 API，約 8-10 分鐘）
- TAIFEX 期貨/PCR：按季批次下載（~20 次 API，約 2 分鐘）
支援中斷後繼續：已存在的日期自動跳過。

用法：
    cd stock_dashboard
    python scripts/init_taiwan_data.py
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from data.taiwan import (
    fetch_twse_institutional,
    _taifex_futures_csv_bulk,
    _taifex_pcr_csv_bulk,
    COLUMNS, DATA_PATH,
)

CHUNK_DAYS = 90


def weekdays_range(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def save_records(new_records: list):
    frames = []
    if DATA_PATH.exists():
        existing = pd.read_csv(DATA_PATH)
        if not existing.empty:
            frames.append(existing)
    if new_records:
        frames.append(pd.DataFrame(new_records, columns=COLUMNS))
    if not frames:
        return
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["date"]).sort_values("date")
    combined.to_csv(DATA_PATH, index=False)


def main():
    DATA_PATH.parent.mkdir(exist_ok=True)

    end_date   = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=365 * 5 + 2)

    existing_dates = set()
    if DATA_PATH.exists():
        try:
            df_ex = pd.read_csv(DATA_PATH)
            existing_dates = set(df_ex["date"].astype(str))
        except Exception:
            pass

    # ── Step 1: TAIFEX bulk download ──────────────────────────
    print("=== Step 1: TAIFEX 批次下載（期貨＋PCR）===")
    taifex_data: dict[str, dict] = {}
    current = start_date
    chunk_count = 0

    while current <= end_date:
        chunk_end = min(current + timedelta(days=CHUNK_DAYS), end_date)
        s = current.strftime("%Y%m%d")
        e = chunk_end.strftime("%Y%m%d")
        chunk_count += 1
        print(f"  [{chunk_count}] {current} ~ {chunk_end} ...", end=" ", flush=True)

        fut_df = _taifex_futures_csv_bulk(s, e)
        pcr_df = _taifex_pcr_csv_bulk(s, e)

        for dt_idx in set(list(fut_df.index) + list(pcr_df.index)):
            iso = dt_idx.strftime("%Y-%m-%d")
            taifex_data.setdefault(iso, {})
            if not fut_df.empty and dt_idx in fut_df.index:
                row = fut_df.loc[dt_idx]
                taifex_data[iso]["futures_fini_long"]  = float(row.get("futures_fini_long",  pd.NA) or pd.NA) if pd.notna(row.get("futures_fini_long"))  else None
                taifex_data[iso]["futures_fini_short"] = float(row.get("futures_fini_short", pd.NA) or pd.NA) if pd.notna(row.get("futures_fini_short")) else None
                taifex_data[iso]["futures_fini_net"]   = float(row.get("futures_fini_net",   pd.NA) or pd.NA) if pd.notna(row.get("futures_fini_net"))   else None
            if not pcr_df.empty and dt_idx in pcr_df.index:
                row = pcr_df.loc[dt_idx]
                taifex_data[iso]["pcr_oi"]  = float(row.get("pcr_oi",  pd.NA) or pd.NA) if pd.notna(row.get("pcr_oi"))  else None
                taifex_data[iso]["pcr_vol"] = float(row.get("pcr_vol", pd.NA) or pd.NA) if pd.notna(row.get("pcr_vol")) else None

        print(f"fut={len(fut_df)}  pcr={len(pcr_df)}")
        current = chunk_end + timedelta(days=1)
        time.sleep(1.5)

    print(f"TAIFEX 批次完成，共 {len(taifex_data)} 個日期。\n")

    # ── Step 2: TWSE 逐日抓取 ────────────────────────────────
    print("=== Step 2: TWSE 三大法人逐日抓取 ===")
    days = list(weekdays_range(start_date, end_date))
    total = len(days)
    records = []
    skipped = 0

    for i, d in enumerate(days):
        date_str = d.strftime("%Y%m%d")
        iso = d.isoformat()

        if iso in existing_dates:
            skipped += 1
            continue

        twse = fetch_twse_institutional(date_str)
        taifex = taifex_data.get(iso, {})

        row = {
            "date":               iso,
            "fini_net":           twse.get("fini_net"),
            "trust_net":          twse.get("trust_net"),
            "dealer_net":         twse.get("dealer_net"),
            "futures_fini_long":  taifex.get("futures_fini_long"),
            "futures_fini_short": taifex.get("futures_fini_short"),
            "futures_fini_net":   taifex.get("futures_fini_net"),
            "pcr_oi":             taifex.get("pcr_oi"),
            "pcr_vol":            taifex.get("pcr_vol"),
        }

        vals = [v for k, v in row.items() if k != "date"]
        if all(v is None for v in vals):
            time.sleep(0.15)
            continue

        records.append(row)
        has_twse   = twse.get("fini_net") is not None
        has_taifex = taifex.get("futures_fini_net") is not None
        has_pcr    = taifex.get("pcr_oi") is not None

        if (i + 1) % 20 == 0 or i == total - 1:
            print(f"  [{i+1:4d}/{total}] {iso}  "
                  f"TWSE={'ok' if has_twse else '--'}  "
                  f"期貨={'ok' if has_taifex else '--'}  "
                  f"PCR={'ok' if has_pcr else '--'}")

        if len(records) >= 100:
            save_records(records)
            existing_dates.update(r["date"] for r in records)
            records = []
            print("    -> 已儲存進度")

        time.sleep(0.35)

    if records:
        save_records(records)

    print(f"\n完成。已略過 {skipped} 筆（已存在）。")
    print(f"資料儲存於：{DATA_PATH}")


if __name__ == "__main__":
    main()
