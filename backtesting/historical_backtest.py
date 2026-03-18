#!/usr/bin/env python3
"""
Historical backtest — test the OB strategy against past 5-minute windows.

Instead of waiting in real-time, we:
1. Fetch 2 days of 15m candles and 5m candles from Binance
2. For each 5-minute window, compute OB signal using 15m candles up to that point
3. Check if BTC went up or down in that 5m window
4. Calculate win rate, PnL, etc.

Usage:
    python backtesting/historical_backtest.py
    python backtesting/historical_backtest.py --days 3
    python backtesting/historical_backtest.py --strategy simple_btc_ob
"""
import sys
import os
import time
import argparse
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from orderblock import (
    calculate_order_blocks,
    FILTER_FRACTAL_LENGTH,
    CANDLE_LINE_HEIGHT,
    PICO_LINE_LENGTH,
    PICO_LOOKBACK,
)
import price as price_mod
import config

# How many 15m candles to use for OB detection at each point
OB_LOOKBACK = 80


def fetch_candles(symbol, timeframe, days):
    """Fetch historical candles from Binance."""
    since = int((time.time() - days * 86400) * 1000)
    all_candles = []
    while True:
        batch = price_mod.get_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        all_candles.extend(batch)
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    return all_candles


def candles_to_df(candles):
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["open_time"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def run_backtest(days=2, symbol="BTC/USDT"):
    print(f"Fetching {days} days of candles...")

    # Fetch 15m candles for OB detection
    candles_15m = fetch_candles(symbol, "15m", days + 1)  # extra day for lookback
    df_15m = candles_to_df(candles_15m)
    print(f"  15m candles: {len(df_15m)}")

    # Fetch 5m candles to determine actual outcomes
    candles_5m = fetch_candles(symbol, "5m", days)
    df_5m = candles_to_df(candles_5m)
    print(f"  5m candles:  {len(df_5m)}")

    # For each 5m window, compute OB signal using 15m candles up to that point
    results = []
    bet_size = config.DEFAULT_BET_SIZE
    balance = 100.0
    peak_balance = 100.0

    print(f"\nRunning backtest over {len(df_5m)} 5-minute windows...\n")

    for i in range(len(df_5m)):
        window = df_5m.iloc[i]
        window_start = window["open_time"]

        # Get 15m candles up to this window's start time
        mask = df_15m["open_time"] < window_start
        available_15m = df_15m[mask].tail(OB_LOOKBACK).reset_index(drop=True)

        if len(available_15m) < 50:
            continue

        # Run OB detection
        try:
            order_blocks, fractals, h_lines = calculate_order_blocks(
                available_15m,
                FILTER_FRACTAL_LENGTH,
                CANDLE_LINE_HEIGHT,
                PICO_LINE_LENGTH,
                PICO_LOOKBACK,
            )
        except Exception:
            continue

        if not order_blocks:
            continue

        order_blocks.sort(key=lambda x: x["time"])
        last_ob = order_blocks[-1]
        second_last_ob = order_blocks[-2] if len(order_blocks) >= 2 else None

        # Compute signal (same logic as simple_btc_ob strategy)
        if last_ob["type"] == "bullish":
            direction = "UP"
            conf = 0.55
        elif last_ob["type"] == "bearish":
            direction = "DOWN"
            conf = 0.55
        else:
            continue

        reasons = [f"Last OB: {last_ob['type']}"]

        if second_last_ob and last_ob["type"] == second_last_ob["type"]:
            conf += 0.10
            reasons.append("Last 2 agree")

        successive = last_ob.get("successive_count", 0)
        if successive >= 3:
            conf += 0.20
            reasons.append(f"Succ: {successive}")
        elif successive >= 2:
            conf += 0.15
            reasons.append(f"Succ: {successive}")

        if last_ob.get("pico") == "true":
            conf += 0.05
            reasons.append("Pico")

        if last_ob.get("fvg") == "true":
            conf += 0.05
            reasons.append("FVG")

        conf = min(conf, 0.95)

        if conf < config.MIN_CONFIDENCE:
            continue

        # Determine actual outcome
        went_up = window["close"] >= window["open"]
        if direction == "UP":
            won = went_up
        else:
            won = not went_up

        # P&L
        entry_price = 0.505  # typical start-of-window price
        if won:
            shares = bet_size / entry_price
            gross = shares * 1.0
            profit = gross - bet_size
            fees = profit * config.FEE_RATE
            pnl = profit - fees
        else:
            pnl = -bet_size
            fees = 0

        if balance + pnl < 0:
            balance = 0
        else:
            balance += pnl

        peak_balance = max(peak_balance, balance)

        results.append({
            "time": window_start,
            "direction": direction,
            "confidence": conf,
            "actual": "UP" if went_up else "DOWN",
            "won": won,
            "pnl": pnl,
            "balance": balance,
            "reasons": " | ".join(reasons),
            "open": window["open"],
            "close": window["close"],
        })

    # Print results
    if not results:
        print("No signals generated!")
        return

    df_results = pd.DataFrame(results)
    total = len(df_results)
    wins = df_results["won"].sum()
    losses = total - wins
    win_rate = wins / total * 100
    total_pnl = df_results["pnl"].sum()
    total_fees = sum(r["pnl"] + bet_size for r in results if r["won"]) * config.FEE_RATE  # approximate

    print("=" * 80)
    print(f"  HISTORICAL BACKTEST RESULTS ({days} days)")
    print("=" * 80)
    print(f"  Total Bets:    {total}")
    print(f"  Wins:          {wins}")
    print(f"  Losses:        {losses}")
    print(f"  Win Rate:      {win_rate:.1f}%")
    print(f"  Total PnL:     ${total_pnl:+.2f}")
    print(f"  Final Balance: ${balance:.2f} (started $100)")
    print(f"  Peak Balance:  ${peak_balance:.2f}")
    print(f"  Max Drawdown:  ${peak_balance - min(r['balance'] for r in results):.2f}")
    print("=" * 80)

    # Show last 20 trades
    print(f"\nLast 20 trades:")
    print(f"{'Time':>20s}  {'Dir':>4s}  {'Conf':>5s}  {'Actual':>6s}  {'Result':>6s}  {'PnL':>8s}  {'Balance':>8s}  Reasoning")
    print("-" * 100)
    for r in results[-20:]:
        result_str = "WIN" if r["won"] else "LOSS"
        print(
            f"{str(r['time']):>20s}  {r['direction']:>4s}  {r['confidence']:>5.2f}  "
            f"{r['actual']:>6s}  {result_str:>6s}  ${r['pnl']:>+7.2f}  ${r['balance']:>7.2f}  {r['reasons']}"
        )

    # Confidence breakdown
    print(f"\nWin rate by confidence level:")
    for threshold in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        subset = [r for r in results if r["confidence"] >= threshold]
        if subset:
            wr = sum(1 for r in subset if r["won"]) / len(subset) * 100
            print(f"  conf >= {threshold:.2f}: {wr:5.1f}% win rate ({len(subset)} trades)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Historical backtest")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--symbol", default="BTC/USDT")
    args = parser.parse_args()

    run_backtest(args.days, args.symbol)
