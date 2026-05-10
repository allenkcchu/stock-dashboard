from dataclasses import dataclass, field
import math
from config import SIGNAL_PARAMS


@dataclass
class Signal:
    label: str
    color: str        # "green" | "red" | "orange" | "gray"
    reasons: list[str] = field(default_factory=list)


def _safe(val) -> float | None:
    if val is None:
        return None
    try:
        v = float(val)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def evaluate(vals: dict, iv: float | None = None) -> Signal:
    rsi = _safe(vals.get("rsi"))
    macd_diff = _safe(vals.get("macd_diff"))
    close = _safe(vals.get("close"))
    bb_upper = _safe(vals.get("bb_upper"))
    bb_lower = _safe(vals.get("bb_lower"))

    score = 0
    reasons = []

    if rsi is not None:
        if rsi < SIGNAL_PARAMS["rsi_oversold"]:
            score += 2
            reasons.append(f"RSI {rsi:.1f} 超賣")
        elif rsi > SIGNAL_PARAMS["rsi_overbought"]:
            score -= 2
            reasons.append(f"RSI {rsi:.1f} 超買")

    if macd_diff is not None:
        if macd_diff > 0:
            score += 1
            reasons.append("MACD 金叉")
        else:
            score -= 1
            reasons.append("MACD 死叉")

    if close and bb_lower and bb_upper:
        prox = SIGNAL_PARAMS["bb_proximity"]
        if close <= bb_lower * (1 + prox):
            score += 1
            reasons.append("接近布林下軌")
        elif close >= bb_upper * (1 - prox):
            score -= 1
            reasons.append("接近布林上軌")

    iv_high = iv is not None and iv > SIGNAL_PARAMS["iv_high"]

    if score >= 2:
        label = "CSP 機會" if iv_high else "偏多"
        if iv_high:
            reasons.append(f"IV {iv:.0%}")
        return Signal(label, "green", reasons)
    elif score <= -2:
        label = "CC 機會" if iv_high else "偏空"
        if iv_high:
            reasons.append(f"IV {iv:.0%}")
        return Signal(label, "red", reasons)
    elif score == 1 or score == -1:
        return Signal("觀察", "orange", reasons)
    else:
        return Signal("中立", "gray", reasons)
