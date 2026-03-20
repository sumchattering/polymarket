# Polymarket Automated Trading

## What This Is
Automated trading system for Polymarket's crypto Up/Down prediction markets (5m and 15m windows). Front-testing momentum strategies across 6 coins before going live with real money.

## Strategies (front-testing)
- **V2**: Consec5 + RSI(14) 30/70 + ADX/CHOP filter (5m)
- **V3**: RSI(14) 30/70 + ADX/CHOP (5m)
- **V4**: RSI(21) 35/65 + ADX/CHOP (5m)
- **V4_15m**: Same as V4 on 15m markets
- **V4_candle5**: RSI(21) on 5m-aggregated candles + ADX/CHOP (15m, designed for BTC/ETH)
- **V5**: V4 + time-of-day filter (5m)
- Each strategy file declares its own TIMEFRAME
- Position sizing: 2% (<2x) -> 3% (<4x) -> 4% (4x+) of starting balance

## How to Run
```bash
./fronttester start momentum_v4 dogecoin   # start strategy on coin
./fronttester status                        # check all balances + expected WR
./fronttester follow momentum_v4_dogecoin   # live logs
./fronttester stop momentum_v4_dogecoin     # stop
./fronttester reload all                    # reload code without losing data

./backtester                                # run backtests (all strategies, 90d)
./backtester --coins doge xrp btc           # specific coins
./backtester --strategy momentum_v4         # single strategy
./backtester --dynamic                      # 2/3/4% sizing ladder
```

## Key Files
- `strategies/momentum_v{2,3,4,5}.py` — strategy signal files (each declares TIMEFRAME)
- `strategies/momentum_v4_15m.py` — V4 for 15m markets
- `strategies/momentum_v4_candle5.py` — V4 on 5m candles for 15m markets
- `backtesting/run_live.py` — main front-testing runner loop
- `backtesting/backtest_filtered.py` — vectorized historical backtester
- `backtesting/market.py` — Polymarket API (gamma)
- `backtesting/price.py` — Binance candle data (ccxt)
- `backtesting/config.py` — sizing, fees, thresholds
- `backtesting/db.py` — SQLite simulation DB
- `backtesting/download_candles.py` — download historical 1m candles

## Data Storage (outside repo, safe from git clean)
- `~/.polymarket/data/` — all strategy DBs, candles.db, expected_wr.json
- `~/.polymarket/logs/` — all front-test log files

## Important Numbers
- Fee: ~1.56%. Breakeven: 50.8% win rate
- 90-day backtest V4 5m: DOGE 55.1% WR, XRP 54.2% WR
- 90-day backtest V4 15m: DOGE 57.3% WR, XRP 56.2% WR
- Markets: `{coin}-updown-{5m|15m}-{floor(unix_ts/secs)*secs}`
- 6 coins: BTC, ETH, SOL, DOGE, XRP, BNB
- Front-test max runtime: 8 days per strategy

## Download More Data
```bash
source backtesting/.venv/bin/activate
python backtesting/download_candles.py --days 120
```
