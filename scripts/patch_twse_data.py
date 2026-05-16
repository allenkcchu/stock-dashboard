"""
修補腳本：對 market_data.csv 中 fini_net 為 null 的日期重新從 TWSE 抓取。
只更新 fini_net, trust_net, dealer_net 三欄，不動 TAIFEX 欄位。

用法：
    cd stock_dashboard
    python scripts/patch_twse_data.py [--from YYYY-MM-DD]
"""

import sys
import time
import argparse
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from data.taiwan import fetch_twse_institutional, DATA_PATH

SLEEP_NORMAL   = 2.0   # seconds between requests
SLEEP_COOLDOWN = 60.0  # pause after consecutive failures
FAIL_THRESHOLD = 5     # consecutive failures before cooldown


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", default=None,
                        help="Only patch dates >= YYYY-MM-DD (default: all missing)")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print("market_data.csv 不存在，請先執行 init_taiwan_data.py")
        return

    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.set_index("date").sort_index()

    missing = df[df["fini_net"].isna()].copy()
    if args.from_date:
        missing = missing[missing.index >= args.from_date]

    print(f"現有資料：{len(df)} 列，目標修補：{len(missing)} 列")
    if missing.empty:
        print("無需修補。")
        return

    updated = 0
    consecutive_fails = 0

    for i, (dt, _) in enumerate(missing.iterrows()):
        date_str = dt.strftime("%Y%m%d")
        result = fetch_twse_institutional(date_str)

        if result["fini_net"] is not None:
            df.loc[dt, "fini_net"]   = result["fini_net"]
            df.loc[dt, "trust_net"]  = result["trust_net"]
            df.loc[dt, "dealer_net"] = result["dealer_net"]
            updated += 1
            consecutive_fails = 0
            status = f"fini={result['fini_net']:.0f}"
        else:
            consecutive_fails += 1
            status = "no data"

        print(f"  [{i+1:4d}/{len(missing)}] {dt.date()}  {status}  (已更新 {updated})")

        if (i + 1) % 50 == 0:
            df.to_csv(DATA_PATH)
            print("    -> 已儲存進度")

        # cooldown if rate limited
        if consecutive_fails >= FAIL_THRESHOLD and consecutive_fails % FAIL_THRESHOLD == 0:
            print(f"    -> 連續 {consecutive_fails} 次無資料，暫停 {SLEEP_COOLDOWN:.0f}s ...")
            time.sleep(SLEEP_COOLDOWN)
        else:
            time.sleep(SLEEP_NORMAL)

    df.to_csv(DATA_PATH)
    print(f"\n完成。共更新 {updated}/{len(missing)} 列。")
    print(f"fini_net 有值：{df['fini_net'].notna().sum()}/{len(df)}")


if __name__ == "__main__":
    main()
