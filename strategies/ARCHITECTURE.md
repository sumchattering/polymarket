# Polymarket Up/Down Trading System — Architecture

## Overview

Automated trading system for Polymarket "Up or Down" 5-minute and 1-hour crypto markets.
Uses order block detection to predict price direction, with backtesting and live trading modes.

## Market Structure

- **5-minute markets**: Resolve via Chainlink data streams. Binary: price at end >= price at beginning.
- **1-hour markets**: Resolve via Binance candle data. Binary: candle close >= candle open.
- Both priced around 0.50/0.50 for Up/Down tokens.
- **Fee: 10% on winnings** (not on trade). Break-even accuracy at 0.50 prices = 52.6%.
- Tick size: $0.01. Two CLOB token IDs per market (index 0 = Up, index 1 = Down).

## Target

- 80% win rate in backtesting before deploying live
- $100 starting capital, $2/bet, max 10 concurrent bets
- Kelly criterion for position sizing

## Folder Structure

```
strategies/
├── config.yaml              # All tunable parameters
├── requirements.txt         # Dependencies
│
├── strategy/                # Core logic (shared between backtest + live)
│   ├── __init__.py
│   ├── order_blocks.py      # Order block detection (code provided by user)
│   ├── signals.py           # Takes OHLCV + OB data → returns UP/DOWN/SKIP
│   └── features.py          # Extra indicators if needed
│
├── market/                  # Polymarket interaction layer
│   ├── __init__.py
│   ├── discovery.py         # Find active up/down markets, parse titles
│   ├── pricing.py           # Get prices, order books, token IDs
│   ├── execution.py         # Place orders via py-clob-client
│   └── models.py            # Dataclasses: Market, Signal, Position, Trade
│
├── data/                    # Data fetching and storage
│   ├── __init__.py
│   ├── ohlcv.py             # Fetch historical candles from Binance via ccxt
│   └── cache.py             # SQLite cache for OHLCV data
│
├── risk/                    # Risk management
│   ├── __init__.py
│   ├── kelly.py             # Kelly criterion position sizing
│   └── rules.py             # Stop rules, drawdown limits, max concurrent bets
│
├── backtest/                # Backtesting engine
│   ├── __init__.py
│   ├── engine.py            # Walk-forward backtesting loop
│   ├── simulator.py         # Simulated fills with fee accounting
│   └── report.py            # Win rate, PnL curve, max drawdown, charts
│
├── live/                    # Live trading daemon
│   ├── __init__.py
│   ├── runner.py            # Main async loop (long-running process)
│   └── monitor.py           # Track open positions, resolution
│
├── store/                   # Persistent storage
│   ├── __init__.py
│   ├── db.py                # SQLite setup, queries
│   └── schema.sql           # Table definitions
│
├── scripts/                 # Entry points
│   ├── run_backtest.py      # python scripts/run_backtest.py
│   ├── run_live.py          # python scripts/run_live.py
│   ├── fetch_history.py     # Download historical candle data
│   └── analyze.py           # Ad-hoc analysis of results
│
├── db/                      # SQLite files (gitignored)
│   ├── trades.db
│   └── ohlcv_cache.db
│
└── logs/                    # Log files (gitignored)
    ├── backtest.log
    └── live.log
```

## Component Design

### Strategy (strategy/)

The critical design principle: strategy code has ZERO knowledge of whether it's
running in backtest or live mode. It's a pure function:

```python
def generate_signal(ohlcv: pd.DataFrame, config: dict) -> Signal:
    # 1. Detect order blocks (using user-provided code)
    # 2. Determine if price is near a fresh OB
    # 3. Return Signal(direction="UP"|"DOWN"|"SKIP", confidence=0.0-1.0)
```

Order block detection code will be provided by the user (they have existing code for this).
It will be integrated into strategy/order_blocks.py.

### Backtesting Flow

```
scripts/run_backtest.py
  → data/ohlcv.py           # Load historical 1m candles from SQLite cache
  → backtest/engine.py      # Iterate over time windows (5m or 1h)
    → strategy/signals.py   # Get signal for each window
    → risk/kelly.py         # Size the position
    → backtest/simulator.py # Simulate trade with fee accounting
  → store/db.py             # Record each simulated trade
  → backtest/report.py      # Print win rate, PnL, Sharpe, etc.
```

Fee accounting: Buy $2 at 0.50, win → get $4 gross, pay 10% on $2 profit = $0.20 fee,
net $3.80 (profit $1.80). Lose → lose $2. Asymmetric.

### Live Trading Flow

```
scripts/run_live.py
  → market/discovery.py    # Find upcoming up/down markets (every ~60s)
  → data/ohlcv.py          # Fetch recent candles from Binance (real-time)
  → strategy/signals.py    # Get signal
  → risk/kelly.py          # Size position ($2 max, Kelly-adjusted)
  → risk/rules.py          # Check constraints (max bets, drawdown, etc.)
  → market/execution.py    # Place order via py-clob-client
  → live/monitor.py        # Track positions, detect resolution
  → store/db.py            # Record entry and exit
```

Single async Python process. No microservices, no message queues.

### Polymarket Integration

Use **py-clob-client** (Python SDK) for trading, NOT CLI subprocesses.
The CLI is still useful for ad-hoc exploration (the scripts in interesting/).

```python
from py_clob_client.client import ClobClient

client = ClobClient(
    host="https://clob.polymarket.com",
    key=private_key,
    chain_id=137,
    signature_type=2,  # proxy
)
```

For market discovery, hit the Gamma API directly:
```python
resp = requests.get("https://gamma-api.polymarket.com/events", params={
    "active": "true", "order": "volume", "limit": 200,
})
```

### Data Sources

Historical OHLCV from Binance via ccxt. Coin mapping:

| Polymarket Coin | Binance Symbol |
|---|---|
| BTC / Bitcoin | BTC/USDT |
| ETH / Ethereum | ETH/USDT |
| SOL / Solana | SOL/USDT |
| DOGE / Dogecoin | DOGE/USDT |
| XRP | XRP/USDT |
| BNB | BNB/USDT |

### Risk Management

- **Kelly criterion**: half-Kelly for safety
- **Max concurrent bets**: 10
- **Bet size**: $2 default, $0.50 minimum
- **Daily loss limit**: $10 (stop trading for the day)
- **Drawdown halt**: Pause 24h if account drops 20% from peak
- **Win rate monitor**: If rolling 50-trade win rate < 55%, reduce to minimum bet
- **Minimum confidence**: Only trade if signal confidence > 0.60

### Database Schema

**trades table:**
- id, timestamp, mode (backtest/live), market_slug, coin, timeframe (5m/1h)
- direction (UP/DOWN), confidence, entry_price, bet_size_usd, shares
- outcome (WIN/LOSS/PENDING), pnl, fees, resolved_at
- order_id (live only), kelly_fraction, notes

**account_snapshots table:**
- id, timestamp, mode, balance, open_positions, total_trades, win_rate, total_pnl

**ohlcv_cache table (separate db):**
- exchange, symbol, timeframe, timestamp, open, high, low, close, volume

## Dependencies

```
ccxt>=4.0
pandas>=2.0
numpy>=1.24
py-clob-client>=0.34
pyyaml>=6.0
tabulate>=0.9
matplotlib>=3.7
```

## Development Phases

1. **Data Pipeline**: Project setup, fetch candles from Binance, SQLite cache
2. **Strategy**: Integrate user's order block code, wire up signal generation
3. **Backtester**: Walk-forward engine, fee-aware simulator, reporting
4. **Risk Management**: Kelly sizing, stop rules, integrate into backtester
5. **Market Discovery + Execution**: Find markets, get prices, place orders via SDK
6. **Live Runner**: Async loop, position monitoring, paper trade 1 week, then go live
