#!/usr/bin/env python3
"""
Backtest Consec5 OR RSI 30/70 strategy with CHOP/ADX filters.
Uses local SQLite candle data (no API calls).

Usage:
    python backtesting/backtest_filtered.py
    python backtesting/backtest_filtered.py --days 30 --coins doge xrp
"""
import sys
import os
import sqlite3
import argparse
import numpy as np
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "candles.db")

# Fee calculation (Polymarket crypto 1.56% effective)
def calc_fee(shares, price):
    return shares * price * 0.25 * (price * (1 - price)) ** 2

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_adx(df, period=14):
    """Average Directional Index — measures trend strength."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.DataFrame({
        "hl": high - low,
        "hc": (high - close.shift()).abs(),
        "lc": (low - close.shift()).abs(),
    }).max(axis=1)

    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()
    return adx

def calc_chop(df, period=14):
    """Choppiness Index — high = choppy, low = trending."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr = pd.DataFrame({
        "hl": high - low,
        "hc": (high - close.shift()).abs(),
        "lc": (low - close.shift()).abs(),
    }).max(axis=1)

    atr_sum = tr.rolling(window=period).sum()
    high_max = high.rolling(window=period).max()
    low_min = low.rolling(window=period).min()

    chop = 100 * np.log10(atr_sum / (high_max - low_min)) / np.log10(period)
    return chop


def load_candles(coin, days=None):
    conn = sqlite3.connect(DB_PATH)
    if days:
        import time
        cutoff = int((time.time() - days * 86400) * 1000)
        df = pd.read_sql_query(
            "SELECT * FROM candles_1m WHERE symbol = ? AND timestamp >= ? ORDER BY timestamp",
            conn, params=(coin, cutoff)
        )
    else:
        df = pd.read_sql_query(
            "SELECT * FROM candles_1m WHERE symbol = ? ORDER BY timestamp",
            conn, params=(coin,)
        )
    conn.close()
    df["open_time"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def build_5m_windows(df_1m):
    """Group 1m candles into 5m windows aligned to 300s boundaries."""
    df_1m = df_1m.copy()
    df_1m["window"] = (df_1m["timestamp"] // 300000) * 300000

    windows = df_1m.groupby("window").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        count=("open", "count"),
    ).reset_index()

    # Only keep complete 5-candle windows
    windows = windows[windows["count"] == 5].copy()
    windows["went_up"] = windows["close"] >= windows["open"]
    windows["open_time"] = pd.to_datetime(windows["window"], unit="ms")
    return windows


def generate_signals(df_1m, df_5m, filter_mode="none"):
    """
    Generate signals using Consec5 OR RSI 30/70 strategy.
    filter_mode: "none", "adx", "chop", "both", "relaxed"
    """
    # Pre-compute indicators on 1m data
    df_1m = df_1m.copy()
    df_1m["rsi_14"] = calc_rsi(df_1m["close"], 14)
    df_1m["adx_14"] = calc_adx(df_1m, 14)
    df_1m["chop_14"] = calc_chop(df_1m, 14)

    signals = []
    skipped_by_filter = 0

    for i in range(len(df_5m)):
        window_ts = df_5m.iloc[i]["window"]

        # Get 1m candles BEFORE this window
        mask = df_1m["timestamp"] < window_ts
        recent = df_1m[mask].tail(20)  # enough for indicators

        if len(recent) < 14:
            continue

        last_row = recent.iloc[-1]

        # Check filter conditions
        adx_val = last_row["adx_14"] if not pd.isna(last_row["adx_14"]) else 0
        chop_val = last_row["chop_14"] if not pd.isna(last_row["chop_14"]) else 100

        if filter_mode == "adx" and adx_val < 25:
            skipped_by_filter += 1
            continue
        elif filter_mode == "chop" and chop_val > 50:
            skipped_by_filter += 1
            continue
        elif filter_mode == "both" and (adx_val < 25 or chop_val > 50):
            skipped_by_filter += 1
            continue
        elif filter_mode == "relaxed" and (adx_val < 20 or chop_val > 55):
            skipped_by_filter += 1
            continue

        direction = None
        reason = ""

        # Signal 1: Consecutive 5 candles same direction → continuation
        last_5 = recent.tail(5)
        if len(last_5) == 5:
            all_up = all(last_5["close"].values > last_5["open"].values)
            all_down = all(last_5["close"].values < last_5["open"].values)
            if all_up:
                direction = "UP"
                reason = "Consec5 UP"
            elif all_down:
                direction = "DOWN"
                reason = "Consec5 DOWN"

        # Signal 2: RSI extreme → reversal (only if no consec signal)
        if direction is None:
            rsi = last_row["rsi_14"]
            if not pd.isna(rsi):
                if rsi < 30:
                    direction = "UP"
                    reason = f"RSI {rsi:.0f} oversold"
                elif rsi > 70:
                    direction = "DOWN"
                    reason = f"RSI {rsi:.0f} overbought"

        if direction:
            signals.append((direction, i, reason, adx_val, chop_val))

    return signals, skipped_by_filter


def run_backtest(coin, days, bet_size=5.0, initial_balance=100.0):
    """Run backtest for one coin with all filter modes."""
    df_1m = load_candles(coin, days)
    if df_1m.empty:
        print(f"  {coin}: no data")
        return None

    df_5m = build_5m_windows(df_1m)

    filter_modes = {
        "No filter": "none",
        "ADX > 25": "adx",
        "CHOP < 50": "chop",
        "ADX>25 & CHOP<50": "both",
        "ADX>20 & CHOP<55": "relaxed",
    }

    results = {}

    for label, mode in filter_modes.items():
        signals, skipped = generate_signals(df_1m, df_5m, mode)

        if not signals:
            results[label] = {"trades": 0, "wr": 0, "pnl": 0, "final": initial_balance, "max_dd_pct": 0, "skipped": skipped}
            continue

        balance = initial_balance
        peak = initial_balance
        min_balance = initial_balance
        wins = 0
        losses = 0

        for direction, idx, reason, adx_val, chop_val in signals:
            if balance < bet_size:
                break

            went_up = df_5m.iloc[idx]["went_up"]
            won = (direction == "UP") == went_up

            entry_price = 0.505
            if won:
                shares = bet_size / entry_price
                fee = calc_fee(shares, entry_price)
                pnl = (shares * 1.0) - bet_size - fee
                wins += 1
            else:
                pnl = -bet_size
                losses += 1

            balance += pnl
            balance = max(balance, 0)
            peak = max(peak, balance)
            min_balance = min(min_balance, balance)

        total = wins + losses
        wr = (wins / total * 100) if total > 0 else 0
        max_dd_pct = ((peak - min_balance) / peak * 100) if peak > 0 else 0
        total_pnl = balance - initial_balance

        results[label] = {
            "trades": total,
            "wins": wins,
            "losses": losses,
            "wr": wr,
            "pnl": total_pnl,
            "final": balance,
            "min_bal": min_balance,
            "max_dd_pct": max_dd_pct,
            "skipped": skipped,
        }

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--coins", nargs="+", default=["btc", "eth", "sol", "doge", "xrp", "bnb"])
    parser.add_argument("--bet", type=float, default=5.0)
    parser.add_argument("--balance", type=float, default=100.0)
    args = parser.parse_args()

    print(f"Backtesting Consec5 OR RSI 30/70 with CHOP/ADX filters")
    print(f"Period: {args.days} days | Bet: ${args.bet} | Start: ${args.balance}")
    print(f"Coins: {', '.join(args.coins)}")
    print()

    all_results = {}
    for coin in args.coins:
        print(f"Running {coin.upper()}...")
        results = run_backtest(coin, args.days, args.bet, args.balance)
        if results:
            all_results[coin] = results

    # Print comparison table
    print()
    print("=" * 120)
    print(f"{'COIN':<6} {'FILTER':<18} {'TRADES':>6} {'WINS':>5} {'WR%':>6} {'PnL':>9} {'FINAL$':>8} {'MIN$':>7} {'DD%':>6} {'SKIP':>5}")
    print("=" * 120)

    for coin in args.coins:
        if coin not in all_results:
            continue
        results = all_results[coin]
        first = True
        for label, r in results.items():
            coin_label = coin.upper() if first else ""
            first = False
            if r["trades"] == 0:
                print(f"{coin_label:<6} {label:<18} {'—no trades—':>6}")
                continue

            wr_str = f"{r['wr']:.1f}%"
            profitable = "***" if r["wr"] > 50.8 else "   "
            print(
                f"{coin_label:<6} {label:<18} {r['trades']:>6} {r['wins']:>5} {wr_str:>6} "
                f"${r['pnl']:>+8.0f} ${r['final']:>7.0f} ${r['min_bal']:>6.0f} {r['max_dd_pct']:>5.0f}% {r['skipped']:>5} {profitable}"
            )
        print("-" * 120)

    # Summary: best filter per coin
    print()
    print("BEST FILTER PER COIN (highest win rate with 50+ trades):")
    print("-" * 70)
    for coin in args.coins:
        if coin not in all_results:
            continue
        best_label = None
        best_wr = 0
        for label, r in all_results[coin].items():
            if r["trades"] >= 50 and r["wr"] > best_wr:
                best_wr = r["wr"]
                best_label = label
        if best_label:
            r = all_results[coin][best_label]
            print(f"  {coin.upper():<5}: {best_label:<18} WR={r['wr']:.1f}% | {r['trades']} trades | ${r['pnl']:+.0f} PnL | {r['max_dd_pct']:.0f}% DD")


if __name__ == "__main__":
    main()
