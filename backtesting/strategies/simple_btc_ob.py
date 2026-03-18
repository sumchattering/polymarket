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

    Args:
        coin: "bitcoin"
        timeframe: "5m"
        current_price: current BTC price
        ohlcv: 1m candles from runner (not used — we fetch 15m ourselves)

    Returns:
        (direction, confidence) or None to skip
    """
    import price as price_mod

    symbol = price_mod.symbol_for_coin(coin)

    # Fetch 15-minute candles for order block detection
    candles_15m = price_mod.get_ohlcv(symbol, TIMEFRAME_CANDLES, limit=100)

    if len(candles_15m) < MIN_CANDLES:
        return None

    df = _ohlcv_to_dataframe(candles_15m)

    # Run order block detection
    order_blocks, fractals, h_lines = calculate_order_blocks(
        df,
        FILTER_FRACTAL_LENGTH,
        CANDLE_LINE_HEIGHT,
        PICO_LINE_LENGTH,
        PICO_LOOKBACK,
    )

    if not order_blocks:
        return None

    # Sort by time, most recent last
    order_blocks.sort(key=lambda x: x["time"])

    # Analyze the most recent order blocks
    last_ob = order_blocks[-1]
    second_last_ob = order_blocks[-2] if len(order_blocks) >= 2 else None

    direction = None
    confidence = 0.0

    # Base signal from last order block
    if last_ob["type"] == "bullish":
        direction = "UP"
        confidence = 0.55
    elif last_ob["type"] == "bearish":
        direction = "DOWN"
        confidence = 0.55

    if direction is None:
        return None

    # Boost confidence if second-to-last agrees
    if second_last_ob:
        if last_ob["type"] == "bullish" and second_last_ob["type"] == "bullish":
            confidence += 0.10
        elif last_ob["type"] == "bearish" and second_last_ob["type"] == "bearish":
            confidence += 0.10

    # Boost for successive order blocks
    successive = last_ob.get("successive_count", 0)
    if successive >= 3:
        confidence += 0.15
    elif successive >= 2:
        confidence += 0.10

    # Boost for recommended (pico) order blocks
    if last_ob.get("recommended") == "true":
        confidence += 0.05
    if last_ob.get("pico") == "true":
        confidence += 0.03

    # Boost for FVG (fair value gap)
    if last_ob.get("fvg") == "true":
        confidence += 0.03

    # Cap at 0.95
    confidence = min(confidence, 0.95)

    return direction, confidence
