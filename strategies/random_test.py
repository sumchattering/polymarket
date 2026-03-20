"""
Random test strategy — for testing the backtesting infrastructure.
Randomly picks UP or DOWN with random confidence.
"""
import random


def generate_signal(coin, timeframe, current_price, ohlcv):
    """
    Strategy interface: every strategy must implement this function.

    Args:
        coin: e.g. "bitcoin"
        timeframe: e.g. "5m"
        current_price: current price of the coin
        ohlcv: list of [timestamp, open, high, low, close, volume] candles

    Returns:
        (direction, confidence) tuple, or None to skip.
        direction: "UP" or "DOWN"
        confidence: 0.0 to 1.0
    """
    direction = random.choice(["UP", "DOWN"])
    confidence = random.uniform(0.5, 0.9)
    return direction, confidence
