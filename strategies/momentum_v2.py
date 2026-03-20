"""
Momentum V2 — Consec5 OR RSI 30/70 + ADX/CHOP trending filter.

Backtested 30 days (Feb 16 - Mar 18, 2026):
  DOGE: 55.5% WR, $100 → $5,309 (3% sizing)
  XRP:  53.7% WR, $100 → $1,882 (5% cap $50 sizing)

Signals:
  1. Consec5: 5 consecutive 1m candles same direction → bet continuation
  2. RSI: RSI(14) on 1m < 30 → UP, > 70 → DOWN (reversal)

Filter: only trade when ADX(14) > 25 AND CHOP(14) < 50 (trending market)

Position sizing: 3% of balance (configurable per coin)
"""
TIMEFRAME = "5m"

import numpy as np
import pandas as pd


def calc_rsi(closes, period=14):
    delta = pd.Series(closes).diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not rsi.empty else 50


def calc_adx(highs, lows, closes, period=14):
    h = pd.Series(highs)
    l = pd.Series(lows)
    c = pd.Series(closes)

    plus_dm = h.diff()
    minus_dm = -l.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.DataFrame({
        "hl": h - l,
        "hc": (h - c.shift()).abs(),
        "lc": (l - c.shift()).abs(),
    }).max(axis=1)

    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()
    return adx.iloc[-1] if not adx.empty else 0


def calc_chop(highs, lows, closes, period=14):
    h = pd.Series(highs)
    l = pd.Series(lows)
    c = pd.Series(closes)

    tr = pd.DataFrame({
        "hl": h - l,
        "hc": (h - c.shift()).abs(),
        "lc": (l - c.shift()).abs(),
    }).max(axis=1)

    atr_sum = tr.rolling(window=period).sum()
    high_max = h.rolling(window=period).max()
    low_min = l.rolling(window=period).min()

    chop = 100 * np.log10(atr_sum / (high_max - low_min)) / np.log10(period)
    return chop.iloc[-1] if not chop.empty else 100


def generate_signal(coin, timeframe, current_price, ohlcv):
    """
    Generate trading signal from 1m OHLCV data.

    Args:
        coin: coin name (e.g., "dogecoin", "xrp")
        timeframe: market timeframe ("5m")
        current_price: current price
        ohlcv: list of [timestamp, open, high, low, close, volume] candles (1m)

    Returns:
        (direction, confidence, reasoning) or None
    """
    if not ohlcv or len(ohlcv) < 30:
        return None

    # Extract arrays
    opens = [c[1] for c in ohlcv]
    highs = [c[2] for c in ohlcv]
    lows = [c[3] for c in ohlcv]
    closes = [c[4] for c in ohlcv]

    # --- FILTER: Check if market is trending ---
    adx = calc_adx(highs, lows, closes)
    chop = calc_chop(highs, lows, closes)

    if pd.isna(adx) or pd.isna(chop):
        return None

    if adx < 25 or chop > 50:
        return None  # Choppy market, skip

    # --- SIGNAL 1: Consecutive 5 candles ---
    last_5_opens = opens[-5:]
    last_5_closes = closes[-5:]

    all_up = all(c > o for o, c in zip(last_5_opens, last_5_closes))
    all_down = all(c < o for o, c in zip(last_5_opens, last_5_closes))

    direction = None
    confidence = 0.60
    reasoning = ""

    if all_up:
        direction = "UP"
        confidence = 0.65
        reasoning = f"Consec5 UP | ADX={adx:.0f} CHOP={chop:.0f}"
    elif all_down:
        direction = "DOWN"
        confidence = 0.65
        reasoning = f"Consec5 DOWN | ADX={adx:.0f} CHOP={chop:.0f}"

    # --- SIGNAL 2: RSI extreme (only if no consec signal) ---
    if direction is None:
        rsi = calc_rsi(closes)
        if not pd.isna(rsi):
            if rsi < 30:
                direction = "UP"
                confidence = 0.60
                reasoning = f"RSI={rsi:.0f} oversold | ADX={adx:.0f} CHOP={chop:.0f}"
            elif rsi > 70:
                direction = "DOWN"
                confidence = 0.60
                reasoning = f"RSI={rsi:.0f} overbought | ADX={adx:.0f} CHOP={chop:.0f}"

    if direction is None:
        return None

    return (direction, confidence, reasoning)
