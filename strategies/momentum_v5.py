"""
Momentum V5 — RSI(21) 35/65 + ADX/CHOP filter + time-of-day filter.

Change from V4: skip consistently bad UTC hours.
Hours where WR < 50% across 3+ months of 90-day backtest.

Backtested 90 days (Dec 18 - Mar 18):
  DOGE: 56.2% WR, ~52 trades/day (skip hours 6, 10, 14 UTC)
  XRP:  56.3% WR, ~45 trades/day (skip hours 3, 5, 8, 9, 10, 14 UTC)

Signal: RSI(21) on 1m < 35 → UP, > 65 → DOWN
Filter: ADX(14) > 25 AND CHOP(14) < 50
Time:   Skip bad hours per coin
"""
TIMEFRAME = "5m"

import numpy as np
import pandas as pd
from datetime import datetime, timezone


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


# Hours to skip per coin (UTC) — consistently below 50% WR across 3+ months
SKIP_HOURS = {
    "dogecoin": {6, 10, 14},
    "xrp":      {3, 5, 8, 9, 10, 14},
}


def generate_signal(coin, timeframe, current_price, ohlcv):
    """
    Generate trading signal from 1m OHLCV data.
    RSI-only: oversold → UP, overbought → DOWN.
    Filtered by ADX/CHOP for trending markets + time-of-day filter.
    """
    if not ohlcv or len(ohlcv) < 30:
        return None

    # Time-of-day filter
    utc_hour = datetime.now(timezone.utc).hour
    skip = SKIP_HOURS.get(coin, set())
    if utc_hour in skip:
        return None

    highs = [c[2] for c in ohlcv]
    lows = [c[3] for c in ohlcv]
    closes = [c[4] for c in ohlcv]

    # Filter: trending market only
    adx = calc_adx(highs, lows, closes)
    chop = calc_chop(highs, lows, closes)

    if pd.isna(adx) or pd.isna(chop):
        return None
    if adx < 25 or chop > 50:
        return None

    # Signal: RSI extremes
    rsi = calc_rsi(closes, period=21)
    if pd.isna(rsi):
        return None

    if rsi < 35:
        return ("UP", 0.60, f"RSI(21)={rsi:.0f} oversold | ADX={adx:.0f} CHOP={chop:.0f} | hour={utc_hour}")
    elif rsi > 65:
        return ("DOWN", 0.60, f"RSI(21)={rsi:.0f} overbought | ADX={adx:.0f} CHOP={chop:.0f} | hour={utc_hour}")

    return None
