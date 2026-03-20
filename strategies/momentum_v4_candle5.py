"""
Momentum V4 candle5 — RSI(21) 35/65 + ADX/CHOP on 5-minute candles.

Same as V4 but aggregates 1m candles into 5m before computing indicators.
Better for BTC and ETH on 15m markets (57.6% and 57.7% WR vs 55.5% and 55.9% on 1m).

Signal: RSI(21) on 5m candles < 35 → UP, > 65 → DOWN
Filter: ADX(14) > 25 AND CHOP(14) < 50 (on 5m candles)
"""
TIMEFRAME = "15m"

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


def _aggregate_to_5m(ohlcv):
    """Aggregate 1m candles into 5m candles."""
    candles_5m = []
    for i in range(0, len(ohlcv) - 4, 5):
        chunk = ohlcv[i:i+5]
        if len(chunk) < 5:
            break
        candles_5m.append([
            chunk[0][0],                          # timestamp
            chunk[0][1],                          # open
            max(c[2] for c in chunk),             # high
            min(c[3] for c in chunk),             # low
            chunk[-1][4],                         # close
            sum(c[5] for c in chunk),             # volume
        ])
    return candles_5m


def generate_signal(coin, timeframe, current_price, ohlcv):
    """
    Generate trading signal from 1m OHLCV data, aggregated to 5m.
    RSI-only: oversold → UP, overbought → DOWN.
    Filtered by ADX/CHOP for trending markets only.
    """
    if not ohlcv or len(ohlcv) < 110:  # need 22 × 5 = 110 candles for RSI(21) on 5m
        return None

    # Aggregate 1m → 5m candles
    ohlcv_5m = _aggregate_to_5m(ohlcv)
    if len(ohlcv_5m) < 22:  # need at least RSI(21) + 1
        return None

    highs = [c[2] for c in ohlcv_5m]
    lows = [c[3] for c in ohlcv_5m]
    closes = [c[4] for c in ohlcv_5m]

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
        return ("UP", 0.60, f"RSI(21)={rsi:.0f} oversold | ADX={adx:.0f} CHOP={chop:.0f}")
    elif rsi > 65:
        return ("DOWN", 0.60, f"RSI(21)={rsi:.0f} overbought | ADX={adx:.0f} CHOP={chop:.0f}")

    return None
