# Stock Dashboard

Wheel Strategy 選擇權輔助工具，整合 Streamlit dashboard、LINE Bot 推播與 GitHub Actions 自動化。

## 系統架構

```
GitHub repo (allenkcchu/stock-dashboard)
├── app.py                          # Streamlit dashboard → Streamlit Cloud
├── watchlist.json                  # 監控清單（依主題分組）
├── indicators/compute.py           # RSI / MACD / Bollinger Bands
├── signals/rules.py                # Wheel Strategy 訊號邏輯
├── scripts/send_line_push.py       # 每日文字推播腳本
├── bot/
│   ├── main.py                     # FastAPI webhook → Railway
│   ├── requirements.txt
│   └── Procfile
└── .github/workflows/
    ├── daily_notify.yml            # 9:30 AM ET Mon-Fri
    └── update_watchlist.yml        # Mon/Thu 14:00 UTC
```

## 外部服務

| 服務 | 用途 |
|------|------|
| [Streamlit Cloud](https://gold-riching.streamlit.app) | Dashboard 主介面 |
| Railway | LINE Bot webhook server |
| LINE Messaging API (`@400vlzrw`) | 每日推播 + 互動查詢 |

## 環境變數

| 位置 | 變數 |
|------|------|
| Streamlit Cloud Secrets | `ANTHROPIC_API_KEY` |
| Railway Variables | `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`, `ANTHROPIC_API_KEY` |
| GitHub Actions Secrets | `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID` |

## 工作日誌

詳細開發紀錄請見 [`logs/`](logs/) 目錄：

- [2026-05-11](logs/2026-05-11.md) — 修正 GitHub Actions cron 延遲導致推播被時間檢查擋掉
- [2026-05-10](logs/2026-05-10.md) — 初始建置：Dashboard、LINE Bot、推播系統、新聞分析
