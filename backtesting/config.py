"""
Backtesting configuration — all tunable parameters in one place.
"""

# Account
INITIAL_BALANCE = 100.0

# Position sizing
DEFAULT_BET_SIZE = 2.0      # USD per bet
MIN_BET_SIZE = 0.50         # Minimum bet
MAX_BET_SIZE = 10.0         # Maximum bet
MAX_CONCURRENT_BETS = 10    # Max open positions at once

# Market assumptions
DEFAULT_ENTRY_PRICE = 0.50  # Up/Down markets typically priced ~50/50
FEE_RATE = 0.10             # 10% fee on winnings

# Risk
DAILY_LOSS_LIMIT = 10.0     # Stop trading after this much daily loss
DRAWDOWN_HALT_PCT = 0.20    # Pause if account drops 20% from peak

# Strategy defaults
MIN_CONFIDENCE = 0.60       # Only trade if confidence > this
KELLY_FRACTION = 0.5        # Half-Kelly for safety

# Markets
DEFAULT_COIN = "bitcoin"
DEFAULT_TIMEFRAME = "5m"
MIN_LIQUIDITY = 5000
