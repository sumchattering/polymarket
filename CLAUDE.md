# Polymarket Automated Trading

## What This Is
Automated trading system for Polymarket's 5-minute crypto Up/Down prediction markets. The goal is to make money by betting on whether DOGE and XRP will go up or down in 5-minute windows.

## Current Strategy: Momentum V2
- **Consec5 OR RSI 30/70** with **ADX/CHOP trending filter**
- Position sizing: 2% of balance (conservative start)
- Front-testing on DOGE and XRP with $100 simulated balance each

## How to Run
```bash
./fronttester start momentum_v2 dogecoin   # start DOGE
./fronttester start momentum_v2 xrp        # start XRP
./fronttester status                        # check all balances
./fronttester follow momentum_v2_dogecoin   # live logs
./fronttester stop momentum_v2_dogecoin     # stop
```

## Key Files
- `backtesting/strategies/momentum_v2.py` — strategy signals
- `backtesting/run_live.py` — main runner loop
- `backtesting/market.py` — Polymarket API (gamma)
- `backtesting/price.py` — Binance candle data (ccxt)
- `backtesting/config.py` — sizing, fees, thresholds
- `backtesting/db.py` — SQLite simulation
- `backtesting/backtest_filtered.py` — historical backtester with filters
- `backtesting/backtest_sizing.py` — position sizing analysis
- `backtesting/candles.db` — 30 days of 1m candle data for all 6 coins

## Important Numbers
- Fee: ~1.56% (not 10%). Breakeven: 50.8% win rate
- DOGE backtest: 55.5% WR with filter
- XRP backtest: 53.7% WR with filter
- Markets: `{coin}-updown-5m-{floor(unix_ts/300)*300}`
