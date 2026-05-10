import json
import streamlit as st
from google import genai
from config import GEMINI_MODEL, NEWS_LIMIT


def _client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


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
    bullet = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines[:NEWS_LIMIT]))
    prompt = f"""你是一位資深股票分析師，專門分析財經新聞對個股的影響。

針對股票 {ticker}，請分析以下每則新聞標題：

{bullet}

對每則新聞，請提供：
1. 根據標題與你對該公司及產業的背景知識，寫出 3～5 句繁體中文摘要，說明新聞的主要內容與背景
2. 你的市場看法：偏多、偏空或中立
3. 一句話說明你看法的理由

只回傳 JSON 陣列，格式如下（不要其他文字）：
[
  {{
    "title": "原始標題（完整複製）",
    "summary": "3～5句繁體中文摘要",
    "sentiment": "bullish | bearish | neutral",
    "reason": "一句繁體中文理由"
  }}
]"""
    try:
        client = _client()
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return _parse_json(resp.text)
    except Exception as e:
        st.warning(f"Gemini 錯誤：{e}")
        return [{"title": h, "summary": "", "sentiment": "neutral", "reason": "分析暫時無法取得"}
                for h in headlines[:NEWS_LIMIT]]
