# Polymarket Automated Trading

## What This Is
Automated trading system for Polymarket's 5-minute crypto Up/Down prediction markets. The goal is to make money by betting on whether DOGE and XRP will go up or down in 5-minute windows.

## Current Strategy: Momentum V2-V5 (front-testing)
- **V2**: Consec5 + RSI(14) 30/70 + ADX/CHOP filter
- **V3**: RSI(14) 30/70 only (dropped Consec5 — it's a coin flip)
- **V4**: RSI(21) 35/65 + ADX/CHOP filter (best WR/volume balance)
- **V5**: V4 + time-of-day filter (skip bad UTC hours)
- Position sizing: 2% (<$200) → 3% (<$400) → 4% ($400+)
- Front-testing on DOGE and XRP with $100 simulated balance each

## How to Run
```bash
./fronttester start momentum_v4 dogecoin   # start strategy on coin
./fronttester start momentum_v4 xrp        # start on XRP
./fronttester status                        # check all balances
./fronttester follow momentum_v4_dogecoin   # live logs
./fronttester stop momentum_v4_dogecoin     # stop
```

## Key Files
- `backtesting/strategies/momentum_v{2,3,4,5}.py` — strategy signals
- `backtesting/run_live.py` — main runner loop
- `backtesting/market.py` — Polymarket API (gamma)
- `backtesting/price.py` — Binance candle data (ccxt)
- `backtesting/config.py` — sizing, fees, thresholds
- `backtesting/db.py` — SQLite simulation
- `backtesting/backtest_filtered.py` — historical backtester with filters
- `backtesting/backtest_sizing.py` — position sizing analysis
- `backtesting/download_candles.py` — download historical 1m candles
- `backtesting/candles.db` — 90 days of 1m candle data for 6 coins

## Important Numbers
- Fee: ~1.56% (not 10%). Breakeven: 50.8% win rate
- 90-day backtest V4: DOGE 55.1% WR, XRP 54.2% WR
- 90-day backtest V5: DOGE 56.2% WR, XRP 56.3% WR
- Markets: `{coin}-updown-5m-{floor(unix_ts/300)*300}`
- 6 coins available: BTC, ETH, SOL, DOGE, XRP, BNB (only trading DOGE/XRP)

## Download More Data
```bash
source backtesting/.venv/bin/activate
python backtesting/download_candles.py --days 120
```
