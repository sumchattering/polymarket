"""
Backtesting configuration — all tunable parameters in one place.
"""

# Account
INITIAL_BALANCE = 100.0

# Position sizing (dynamic — % of balance)
BET_PCT = 0.02              # Default: 2% of balance per bet (conservative start)
BET_CAP = None              # Optional max bet cap in USD (None = no cap)
MIN_BET_SIZE = 0.50         # Minimum bet
MAX_CONCURRENT_BETS = 10    # Max open positions at once

# Per-coin overrides
COIN_SIZING = {
    "dogecoin": {"pct": 0.02, "cap": None},     # 2% uncapped (conservative start)
    "xrp":      {"pct": 0.02, "cap": None},     # 2% uncapped (conservative start)
}

# Legacy fixed bet (unused by momentum_v2, kept for old strategies)
DEFAULT_BET_SIZE = 5.0

# Market assumptions
DEFAULT_ENTRY_PRICE = 0.50  # Up/Down markets typically priced ~50/50

# Fees — Polymarket crypto markets: ~1.56% effective trading fee
# Formula: fee = shares * price * 0.25 * (price * (1-price))^2
# At 50/50 odds this works out to ~1.56% of bet size
# Breakeven win rate: 50.8%
FEE_RATE = 0.0156

# Risk
DAILY_LOSS_LIMIT = 10.0     # Stop trading after this much daily loss
DRAWDOWN_HALT_PCT = 0.20    # Pause if account drops 20% from peak

# Strategy defaults
MIN_CONFIDENCE = 0.55       # Only trade if confidence > this
KELLY_FRACTION = 0.5        # Half-Kelly for safety

# Markets
DEFAULT_COIN = "dogecoin"
DEFAULT_TIMEFRAME = "5m"
MIN_LIQUIDITY = 5000
