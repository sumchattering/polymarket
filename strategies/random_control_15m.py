"""
Random control 15m — bets randomly every 15m window.
Expected: ~50% WR, slight losses from 1.56% fee.
Used to validate infrastructure is working correctly.
"""
TIMEFRAME = "15m"

import random


def generate_signal(coin, timeframe, current_price, ohlcv):
    direction = random.choice(["UP", "DOWN"])
    return (direction, 0.60, "random control 15m")
