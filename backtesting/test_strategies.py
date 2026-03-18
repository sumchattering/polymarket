#!/usr/bin/env python3
"""
Test multiple strategies against historical 5-minute data.
Find what actually predicts BTC 5-minute direction.
"""
import sys
import os
import time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import price as price_mod

DAYS = 3


def fetch_candles(symbol, timeframe, days):
    since = int((time.time() - days * 86400) * 1000)
    all_candles = []
    while True:
        batch = price_mod.get_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        all_candles.extend(batch)
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["open_time"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


print(f"Fetching {DAYS} days of data...")
df_1m = fetch_candles("BTC/USDT", "1m", DAYS + 1)
df_5m = fetch_candles("BTC/USDT", "5m", DAYS)
print(f"  1m candles: {len(df_1m)}")
print(f"  5m candles: {len(df_5m)}")

# For each 5m window, determine if it went UP or DOWN
df_5m["went_up"] = df_5m["close"] >= df_5m["open"]
df_5m["change_pct"] = (df_5m["close"] - df_5m["open"]) / df_5m["open"] * 100

total_windows = len(df_5m)
base_up_rate = df_5m["went_up"].mean() * 100
print(f"\nTotal 5m windows: {total_windows}")
print(f"Base rate (UP): {base_up_rate:.1f}%")
print(f"Base rate (DOWN): {100 - base_up_rate:.1f}%")


def test_strategy(name, signals):
    """Test a list of (direction, window_index) signals."""
    if not signals:
        print(f"\n{name}: No signals generated")
        return
    wins = sum(1 for d, i in signals if (d == "UP") == df_5m.iloc[i]["went_up"])
    total = len(signals)
    wr = wins / total * 100
    # PnL assuming $5 bet at 0.505
    pnl = sum(
        4.41 if (d == "UP") == df_5m.iloc[i]["went_up"] else -5.0
        for d, i in signals
    )
    print(f"\n{name}:")
    print(f"  Trades: {total}  Wins: {wins}  Losses: {total-wins}  Win Rate: {wr:.1f}%  PnL: ${pnl:+.2f}")
    if wr > 52.6:
        print(f"  *** PROFITABLE *** (above 52.6% breakeven)")


# ============================================================
# Strategy 1: MOMENTUM — bet in direction of last N minutes
# ============================================================
for lookback in [1, 3, 5, 10, 15]:
    signals = []
    for i in range(len(df_5m)):
        t = df_5m.iloc[i]["open_time"]
        recent = df_1m[df_1m["open_time"] < t].tail(lookback)
        if len(recent) < lookback:
            continue
        change = recent["close"].iloc[-1] - recent["open"].iloc[0]
        if change > 0:
            signals.append(("UP", i))
        elif change < 0:
            signals.append(("DOWN", i))
    test_strategy(f"Momentum (last {lookback}m)", signals)


# ============================================================
# Strategy 2: MEAN REVERSION — bet AGAINST last N minutes
# ============================================================
for lookback in [1, 3, 5, 10, 15]:
    signals = []
    for i in range(len(df_5m)):
        t = df_5m.iloc[i]["open_time"]
        recent = df_1m[df_1m["open_time"] < t].tail(lookback)
        if len(recent) < lookback:
            continue
        change = recent["close"].iloc[-1] - recent["open"].iloc[0]
        if change > 0:
            signals.append(("DOWN", i))  # Bet against
        elif change < 0:
            signals.append(("UP", i))
    test_strategy(f"Mean Reversion (last {lookback}m)", signals)


# ============================================================
# Strategy 3: RSI — overbought/oversold
# ============================================================
def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

df_1m["rsi_14"] = calc_rsi(df_1m["close"], 14)

for threshold in [30, 35, 40]:
    signals = []
    for i in range(len(df_5m)):
        t = df_5m.iloc[i]["open_time"]
        recent = df_1m[df_1m["open_time"] < t].tail(1)
        if recent.empty or pd.isna(recent.iloc[0]["rsi_14"]):
            continue
        rsi = recent.iloc[0]["rsi_14"]
        if rsi < threshold:
            signals.append(("UP", i))  # Oversold → bounce
        elif rsi > (100 - threshold):
            signals.append(("DOWN", i))  # Overbought → drop
    test_strategy(f"RSI reversal (threshold {threshold}/{100-threshold})", signals)


# ============================================================
# Strategy 4: VOLUME SPIKE — high volume predicts continuation
# ============================================================
df_1m["vol_sma"] = df_1m["volume"].rolling(20).mean()
df_1m["vol_ratio"] = df_1m["volume"] / df_1m["vol_sma"]

for vol_mult in [1.5, 2.0, 3.0]:
    signals = []
    for i in range(len(df_5m)):
        t = df_5m.iloc[i]["open_time"]
        recent = df_1m[df_1m["open_time"] < t].tail(3)
        if len(recent) < 3:
            continue
        if recent["vol_ratio"].max() < vol_mult:
            continue
        change = recent["close"].iloc[-1] - recent["open"].iloc[0]
        if change > 0:
            signals.append(("UP", i))
        elif change < 0:
            signals.append(("DOWN", i))
    test_strategy(f"Volume Spike ({vol_mult}x) + Momentum", signals)


# ============================================================
# Strategy 5: EMA CROSSOVER — fast EMA > slow EMA
# ============================================================
df_1m["ema_5"] = df_1m["close"].ewm(span=5).mean()
df_1m["ema_20"] = df_1m["close"].ewm(span=20).mean()

signals = []
for i in range(len(df_5m)):
    t = df_5m.iloc[i]["open_time"]
    recent = df_1m[df_1m["open_time"] < t].tail(1)
    if recent.empty:
        continue
    if recent.iloc[0]["ema_5"] > recent.iloc[0]["ema_20"]:
        signals.append(("UP", i))
    else:
        signals.append(("DOWN", i))
test_strategy("EMA Crossover (5/20)", signals)

df_1m["ema_3"] = df_1m["close"].ewm(span=3).mean()
df_1m["ema_10"] = df_1m["close"].ewm(span=10).mean()

signals = []
for i in range(len(df_5m)):
    t = df_5m.iloc[i]["open_time"]
    recent = df_1m[df_1m["open_time"] < t].tail(1)
    if recent.empty:
        continue
    if recent.iloc[0]["ema_3"] > recent.iloc[0]["ema_10"]:
        signals.append(("UP", i))
    else:
        signals.append(("DOWN", i))
test_strategy("EMA Crossover (3/10)", signals)


# ============================================================
# Strategy 6: BOLLINGER BAND — price at extremes → revert
# ============================================================
df_1m["bb_mid"] = df_1m["close"].rolling(20).mean()
df_1m["bb_std"] = df_1m["close"].rolling(20).std()
df_1m["bb_upper"] = df_1m["bb_mid"] + 2 * df_1m["bb_std"]
df_1m["bb_lower"] = df_1m["bb_mid"] - 2 * df_1m["bb_std"]

signals = []
for i in range(len(df_5m)):
    t = df_5m.iloc[i]["open_time"]
    recent = df_1m[df_1m["open_time"] < t].tail(1)
    if recent.empty or pd.isna(recent.iloc[0]["bb_upper"]):
        continue
    price = recent.iloc[0]["close"]
    if price <= recent.iloc[0]["bb_lower"]:
        signals.append(("UP", i))
    elif price >= recent.iloc[0]["bb_upper"]:
        signals.append(("DOWN", i))
test_strategy("Bollinger Band Reversal", signals)


# ============================================================
# Strategy 7: CONSECUTIVE CANDLES — after N same-direction candles, continue or revert?
# ============================================================
for n_consec in [3, 4, 5]:
    # Continuation
    signals_cont = []
    # Reversal
    signals_rev = []
    for i in range(len(df_5m)):
        t = df_5m.iloc[i]["open_time"]
        recent = df_1m[df_1m["open_time"] < t].tail(n_consec)
        if len(recent) < n_consec:
            continue
        all_up = all(recent["close"].values > recent["open"].values)
        all_down = all(recent["close"].values < recent["open"].values)
        if all_up:
            signals_cont.append(("UP", i))
            signals_rev.append(("DOWN", i))
        elif all_down:
            signals_cont.append(("DOWN", i))
            signals_rev.append(("UP", i))
    test_strategy(f"Consecutive {n_consec} candles (continue)", signals_cont)
    test_strategy(f"Consecutive {n_consec} candles (revert)", signals_rev)


# ============================================================
# Strategy 8: PREVIOUS 5m WINDOW — does the previous window predict the next?
# ============================================================
signals_cont = []
signals_rev = []
for i in range(1, len(df_5m)):
    prev = df_5m.iloc[i - 1]
    if prev["close"] > prev["open"]:
        signals_cont.append(("UP", i))
        signals_rev.append(("DOWN", i))
    else:
        signals_cont.append(("DOWN", i))
        signals_rev.append(("UP", i))
test_strategy("Previous 5m window (continue)", signals_cont)
test_strategy("Previous 5m window (revert)", signals_rev)


# ============================================================
# Strategy 9: BIG MOVE REVERSAL — after a large 5m move, bet reversal
# ============================================================
for pct_threshold in [0.05, 0.10, 0.15]:
    signals = []
    for i in range(1, len(df_5m)):
        prev = df_5m.iloc[i - 1]
        change_pct = abs((prev["close"] - prev["open"]) / prev["open"] * 100)
        if change_pct < pct_threshold:
            continue
        if prev["close"] > prev["open"]:
            signals.append(("DOWN", i))  # Big up → revert
        else:
            signals.append(("UP", i))    # Big down → revert
    test_strategy(f"Big Move Reversal (>{pct_threshold}%)", signals)


print("\n" + "=" * 80)
print("DONE. Strategies above 52.6% win rate are potentially profitable.")
print("=" * 80)
