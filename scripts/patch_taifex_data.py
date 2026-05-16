"""
修補腳本：對現有 market_data.csv 中的 TAIFEX 欄位用 bulk CSV 重新填入。
只更新 futures_fini_* 和 pcr_* 欄位，不動 TWSE 欄位。
用於修正 POST endpoint 無法取得歷史資料的問題。

用法：
    cd stock_dashboard
    python scripts/patch_taifex_data.py
"""

import sys
import time
from datetime import timedelta
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from data.taiwan import _taifex_futures_csv_bulk, _taifex_pcr_csv_bulk, DATA_PATH

CHUNK_DAYS = 90


def main():
    if not DATA_PATH.exists():
        print("market_data.csv 不存在，請先執行 init_taiwan_data.py")
        return

    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.set_index("date").sort_index()
    print(f"現有資料：{len(df)} 列，{df.index.min().date()} ~ {df.index.max().date()}")

    start_dt = df.index.min().date()
    end_dt   = df.index.max().date()
    current  = start_dt
    total_fut = total_pcr = 0

    while current <= end_dt:
        chunk_end = min(current + timedelta(days=CHUNK_DAYS), end_dt)
        s = current.strftime("%Y%m%d")
        e = chunk_end.strftime("%Y%m%d")
        print(f"  {current} ~ {chunk_end} ...", end=" ", flush=True)

        fut_df = _taifex_futures_csv_bulk(s, e)
        pcr_df = _taifex_pcr_csv_bulk(s, e)

        for src_df, cols in [
            (fut_df, ["futures_fini_long", "futures_fini_short", "futures_fini_net"]),
            (pcr_df, ["pcr_oi", "pcr_vol"]),
        ]:
            if src_df.empty:
                continue
            common = df.index.intersection(src_df.index)
            for col in cols:
                if col in src_df.columns:
                    df.loc[common, col] = src_df.loc[common, col].values

        print(f"fut={len(fut_df)}  pcr={len(pcr_df)}")
        total_fut += len(fut_df)
        total_pcr += len(pcr_df)

        current = chunk_end + timedelta(days=1)
        time.sleep(1.5)

    df.to_csv(DATA_PATH)
    print(f"\n完成。futures 更新 {total_fut} 列，PCR 更新 {total_pcr} 列。")
    print(f"futures_fini_net 有值：{df['futures_fini_net'].notna().sum()}/{len(df)}")
    print(f"pcr_oi 有值：{df['pcr_oi'].notna().sum()}/{len(df)}")


if __name__ == "__main__":
    main()
