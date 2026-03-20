"""
Simple Bitcoin Order Block Strategy

Strategy: Use 15-minute order blocks to predict 5-minute Bitcoin direction.
- Fetch 15m candles from Binance
- Run order block detection
- If last order block(s) are bullish → bet UP
- If last order block(s) are bearish → bet DOWN
- Confidence scales with successive count and recommended/pico flags

Position sizing: $5 per bet
Frequency: One bet every 5 minutes
"""
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orderblock import (
    calculate_order_blocks,
    FILTER_FRACTAL_LENGTH,
    CANDLE_LINE_HEIGHT,
    PICO_LINE_LENGTH,
    PICO_LOOKBACK,
)

# Strategy config
BET_SIZE = 5.0
TIMEFRAME_CANDLES = "15m"  # Candle timeframe for OB detection
MIN_CANDLES = 50           # Minimum candles needed for OB detection


def _ohlcv_to_dataframe(ohlcv_raw):
    """Convert ccxt OHLCV list to DataFrame with expected columns."""
    df = pd.DataFrame(ohlcv_raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["open_time"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def generate_signal(coin, timeframe, current_price, ohlcv):
    """
    Strategy entry point.

    Returns:
        (direction, confidence, reasoning) or None to skip.
    """
    import price as price_mod

    symbol = price_mod.symbol_for_coin(coin)
    candles_15m = price_mod.get_ohlcv(symbol, TIMEFRAME_CANDLES, limit=100)

    if len(candles_15m) < MIN_CANDLES:
        return None

    df = _ohlcv_to_dataframe(candles_15m)

    order_blocks, fractals, h_lines = calculate_order_blocks(
        df,
        FILTER_FRACTAL_LENGTH,
        CANDLE_LINE_HEIGHT,
        PICO_LINE_LENGTH,
        PICO_LOOKBACK,
    )

    if not order_blocks:
        return None

    order_blocks.sort(key=lambda x: x["time"])

    last_ob = order_blocks[-1]
    second_last_ob = order_blocks[-2] if len(order_blocks) >= 2 else None

    direction = None
    confidence = 0.0
    reasons = []

    # Base signal from last order block
    if last_ob["type"] == "bullish":
        direction = "UP"
        confidence = 0.55
        reasons.append(f"Last OB: bullish @ ${last_ob['price']:,.2f} ({last_ob['time'].strftime('%H:%M')})")
    elif last_ob["type"] == "bearish":
        direction = "DOWN"
        confidence = 0.55
        reasons.append(f"Last OB: bearish @ ${last_ob['price']:,.2f} ({last_ob['time'].strftime('%H:%M')})")

    if direction is None:
        return None

    # Last two OBs agree — strong signal
    if second_last_ob and last_ob["type"] == second_last_ob["type"]:
        confidence += 0.10
        reasons.append(f"Last 2 OBs both {last_ob['type']} (+0.10)")

    # Successive count — very strong signal
    successive = last_ob.get("successive_count", 0)
    if successive >= 3:
        confidence += 0.20
        reasons.append(f"Successive: {successive} in a row (+0.20)")
    elif successive >= 2:
        confidence += 0.15
        reasons.append(f"Successive: {successive} in a row (+0.15)")

    # Pico — good signal
    if last_ob.get("pico") == "true":
        confidence += 0.05
        reasons.append("Pico OB (+0.05)")

    # FVG (fair value gap) — good signal
    if last_ob.get("fvg") == "true":
        confidence += 0.05
        reasons.append("FVG present (+0.05)")

    confidence = min(confidence, 0.95)

    # Summary
    total_obs = len(order_blocks)
    bullish_count = sum(1 for ob in order_blocks if ob["type"] == "bullish")
    bearish_count = sum(1 for ob in order_blocks if ob["type"] == "bearish")
    reasons.append(f"Total OBs: {total_obs} ({bullish_count} bullish, {bearish_count} bearish)")

    reasoning = " | ".join(reasons)
    return direction, confidence, reasoning
