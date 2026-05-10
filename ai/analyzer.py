import json
import streamlit as st
import google.generativeai as genai
from config import GEMINI_MODEL, NEWS_LIMIT


def _model():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel(GEMINI_MODEL)


def _parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
    return json.loads(text)


@st.cache_data(ttl=3600, show_spinner=False)
def analyze_news(ticker: str, headlines_key: str, headlines: tuple) -> list:
    if not headlines:
        return []
    model = _model()
    bullet = "\n".join(f"- {h}" for h in headlines[:NEWS_LIMIT])
    prompt = f"""你是股票分析師。針對股票 {ticker}，分析以下新聞標題，判斷每則對股價是偏多、偏空還是中立。

新聞標題：
{bullet}

請回傳 JSON 陣列，每個元素包含：
- "title": 原始標題
- "sentiment": "bullish" | "bearish" | "neutral"
- "reason": 一句繁體中文說明理由

只回傳 JSON，不要其他文字。"""
    try:
        resp = model.generate_content(prompt)
        return _parse_json(resp.text)
    except Exception:
        return [{"title": h, "sentiment": "neutral", "reason": "分析暫時無法取得"} for h in headlines[:NEWS_LIMIT]]
