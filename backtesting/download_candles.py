#!/usr/bin/env python3
"""
Download historical 1m candles for all coins and save to SQLite.
This avoids re-fetching from Binance every time we run a backtest.

Usage:
    python backtesting/download_candles.py          # default 30 days
    python backtesting/download_candles.py --days 60
"""
import sys
import os
import time
import sqlite3
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))
import price as price_mod

COINS = {
    "btc": "BTC/USDT",
    "eth": "ETH/USDT",
    "sol": "SOL/USDT",
    "doge": "DOGE/USDT",
    "xrp": "XRP/USDT",
    "bnb": "BNB/USDT",
}

DB_PATH = os.path.join(os.path.dirname(__file__), "candles.db")


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles_1m (
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (symbol, timestamp)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_symbol_ts ON candles_1m(symbol, timestamp)")
    conn.commit()
    return conn


def get_latest_ts(conn, symbol):
    """Get the latest timestamp we have for a symbol."""
    row = conn.execute(
        "SELECT MAX(timestamp) FROM candles_1m WHERE symbol = ?", (symbol,)
    ).fetchone()
    return row[0] if row[0] else None


def fetch_all_candles(symbol, since_ms, limit_per_batch=1000):
    """Fetch all 1m candles from Binance since a timestamp."""
    all_candles = []
    current_since = since_ms
    while True:
        try:
            batch = price_mod.get_ohlcv(symbol, "1m", since=current_since, limit=limit_per_batch)
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
            break
        if not batch:
            break
        all_candles.extend(batch)
        current_since = batch[-1][0] + 1
        if len(batch) < limit_per_batch:
            break
        # Rate limit
        time.sleep(0.1)
    return all_candles


def download_coin(coin, symbol, days, db_path):
    """Download candles for one coin."""
    conn = sqlite3.connect(db_path)

    # Check what we already have
    latest = get_latest_ts(conn, coin)
    if latest:
        # Only fetch new data
        since_ms = latest + 60000  # 1 minute after last
        existing_count = conn.execute(
            "SELECT COUNT(*) FROM candles_1m WHERE symbol = ?", (coin,)
        ).fetchone()[0]
        print(f"  {coin}: {existing_count} existing candles, fetching new since {time.strftime('%Y-%m-%d %H:%M', time.gmtime(since_ms/1000))}")
    else:
        since_ms = int((time.time() - days * 86400) * 1000)
        print(f"  {coin}: fresh download, {days} days back")

    candles = fetch_all_candles(symbol, since_ms)
    if not candles:
        print(f"  {coin}: no new candles")
        conn.close()
        return 0

    # Insert into DB
    conn.executemany(
        "INSERT OR REPLACE INTO candles_1m (symbol, timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(coin, c[0], c[1], c[2], c[3], c[4], c[5]) for c in candles],
    )
    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) FROM candles_1m WHERE symbol = ?", (coin,)
    ).fetchone()[0]
    first_ts = conn.execute(
        "SELECT MIN(timestamp) FROM candles_1m WHERE symbol = ?", (coin,)
    ).fetchone()[0]
    last_ts = conn.execute(
        "SELECT MAX(timestamp) FROM candles_1m WHERE symbol = ?", (coin,)
    ).fetchone()[0]

    days_covered = (last_ts - first_ts) / 1000 / 86400
    print(f"  {coin}: +{len(candles)} new, {total} total, {days_covered:.1f} days ({time.strftime('%m/%d', time.gmtime(first_ts/1000))} - {time.strftime('%m/%d', time.gmtime(last_ts/1000))})")
    conn.close()
    return len(candles)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--coins", nargs="+", default=list(COINS.keys()))
    args = parser.parse_args()

    print(f"Downloading {args.days} days of 1m candles for: {', '.join(args.coins)}")
    print(f"DB: {DB_PATH}\n")

    conn = init_db(DB_PATH)
    conn.close()

    total_new = 0
    for coin in args.coins:
        symbol = COINS.get(coin)
        if not symbol:
            print(f"  {coin}: unknown coin, skipping")
            continue
        n = download_coin(coin, symbol, args.days, DB_PATH)
        total_new += n

    # Summary
    conn = sqlite3.connect(DB_PATH)
    print(f"\n{'='*60}")
    print(f"  DOWNLOAD COMPLETE — {total_new} new candles")
    print(f"{'='*60}")
    for coin in args.coins:
        row = conn.execute(
            "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM candles_1m WHERE symbol = ?",
            (coin,),
        ).fetchone()
        if row[0]:
            days_c = (row[2] - row[1]) / 1000 / 86400
            print(f"  {coin:5s}: {row[0]:>6,} candles, {days_c:.1f} days")
    conn.close()


if __name__ == "__main__":
    main()
