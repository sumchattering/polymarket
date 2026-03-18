#!/usr/bin/env python3
"""
Live backtesting runner — monitors BTC 5-minute markets continuously.

Each strategy gets its own DB and log file for full isolation.
Managed by the `backtester` CLI script.

Usage:
    python backtesting/run_live.py --strategy simple_btc_ob --db path/to/db --log path/to/log
"""
import sys
import os
import time
import signal
import argparse
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import db
import config
import price
import market

# Max seconds into a window we'll still enter (buy early for best odds)
MAX_ENTRY_DELAY = 30

running = True
_db_path = None  # Set in main(), used by all functions


def signal_handler(sig, frame):
    global running
    log.info("Shutting down gracefully...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

log = logging.getLogger("live")


def setup_logging(log_path=None):
    """Configure logging to file and stdout."""
    handlers = [logging.StreamHandler()]
    if log_path:
        handlers.append(logging.FileHandler(log_path))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def load_strategy(name):
    """Load a strategy module from strategies/<name>.py"""
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "strategies", f"{name}.py")
    if not os.path.exists(path):
        log.error(f"Strategy not found: {path}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate_signal


def resolve_pending():
    """Resolve pending trades by checking actual Polymarket market results."""
    conn = db.get_db(_db_path)
    pending = conn.execute(
        "SELECT * FROM trades WHERE outcome = 'PENDING'"
    ).fetchall()
    conn.close()

    if not pending:
        return

    for trade in pending:
        slug = trade["market_slug"]
        winner = market.get_market_result(slug)

        if winner is None:
            log.info(f"Trade #{trade['id']} ({slug}): not resolved yet")
            continue

        if trade["direction"] == winner:
            outcome = "WIN"
        else:
            outcome = "LOSS"

        try:
            symbol = price.symbol_for_coin("bitcoin")
            end_price = price.get_current_price(symbol)
        except Exception:
            end_price = 0

        db.resolve_trade(trade["id"], outcome, end_price, config.FEE_RATE, _db_path)
        log.info(f"Trade #{trade['id']}: market resolved {winner}, we bet {trade['direction']} → {outcome}")

    db.take_snapshot(_db_path)


def run_cycle(strategy_fn, strategy_name, coin="bitcoin"):
    """
    Run one 5-minute cycle:
    1. Resolve old pending trades
    2. Get the current market and its odds
    3. Run OB signal
    4. If confident, bet immediately at start-of-window odds
    """
    resolve_pending()

    balance = db.get_balance(_db_path)
    open_pos = db.get_open_positions(_db_path)

    if balance < config.MIN_BET_SIZE:
        log.warning(f"Balance too low: ${balance:.2f}")
        return

    if open_pos >= config.MAX_CONCURRENT_BETS:
        log.info(f"Max concurrent bets: {open_pos}")
        return

    mkt = market.get_current_5m_market("btc")
    if not mkt:
        log.warning("No active market found")
        return

    log.info(
        f"Market: {mkt['title']} | "
        f"UP: {mkt['up_price']:.3f} DOWN: {mkt['down_price']:.3f} | "
        f"Elapsed: {mkt['elapsed_seconds']}s | Remaining: {mkt['remaining_seconds']}s"
    )

    if mkt["elapsed_seconds"] > MAX_ENTRY_DELAY:
        log.info(f"Too late in window ({mkt['elapsed_seconds']}s > {MAX_ENTRY_DELAY}s), waiting for next")
        return

    symbol = price.symbol_for_coin(coin)
    current_price = price.get_current_price(symbol)
    ohlcv = price.get_ohlcv(symbol, "1m", limit=60)

    result = strategy_fn(coin, "5m", current_price, ohlcv)
    if result is None:
        log.info("Signal: SKIP")
        return

    direction, confidence = result
    log.info(f"Signal: {direction} (confidence: {confidence:.2f}) | BTC: ${current_price:,.2f} | Balance: ${balance:.2f}")

    if confidence < config.MIN_CONFIDENCE:
        log.info(f"Confidence {confidence:.2f} < {config.MIN_CONFIDENCE}, skipping")
        return

    if direction == "UP":
        entry_price = mkt["up_price"]
    else:
        entry_price = mkt["down_price"]

    bet_size = min(config.DEFAULT_BET_SIZE, balance)

    trade_id = db.place_bet(
        strategy=strategy_name,
        market_slug=mkt["slug"],
        coin=coin,
        timeframe="5m",
        direction=direction,
        confidence=confidence,
        entry_price=entry_price,
        bet_size_usd=bet_size,
        start_price=current_price,
        db_path=_db_path,
    )
    if trade_id:
        log.info(
            f"*** BET *** #{trade_id}: {direction} ${bet_size:.2f} @ {entry_price:.3f} on {mkt['title']}"
        )


def print_stats(strategy=None):
    """Log current stats."""
    stats = db.get_stats(strategy=strategy, db_path=_db_path)
    log.info(
        f"Stats | Balance: ${stats['balance']:.2f} | "
        f"Trades: {stats['total_trades']} | "
        f"W/L: {stats['wins']}/{stats['losses']} | "
        f"Win Rate: {stats['win_rate']:.1f}% | "
        f"PnL: ${stats['total_pnl']:+.2f}"
    )


def wait_for_next_window():
    """Sleep until the start of the next 5-minute window."""
    now = int(time.time())
    next_window = ((now // 300) + 1) * 300
    wait = next_window - now
    log.info(f"Waiting {wait}s for next 5-min window...")
    for _ in range(wait):
        if not running:
            break
        time.sleep(1)


def main():
    global _db_path

    parser = argparse.ArgumentParser(description="Live backtesting runner")
    parser.add_argument("--strategy", default="simple_btc_ob")
    parser.add_argument("--coin", default="bitcoin")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--db", default=None, help="Path to strategy-specific SQLite DB")
    parser.add_argument("--log", default=None, help="Path to strategy-specific log file")
    args = parser.parse_args()

    # Set up per-strategy paths
    _db_path = args.db
    setup_logging(args.log)

    db.init_db(args.balance, _db_path)
    if args.reset:
        db.reset_account(args.balance, _db_path)
    strategy_fn = load_strategy(args.strategy)

    log.info(f"=== Starting live backtester ===")
    log.info(f"Strategy: {args.strategy} | Coin: {args.coin}")
    log.info(f"Bet size: ${config.DEFAULT_BET_SIZE:.2f} | Max entry delay: {MAX_ENTRY_DELAY}s")
    log.info(f"DB: {_db_path or 'default'}")
    print_stats()

    while running:
        try:
            run_cycle(strategy_fn, args.strategy, args.coin)
            print_stats(args.strategy)
            wait_for_next_window()
        except Exception as e:
            log.error(f"Error in cycle: {e}", exc_info=True)
            time.sleep(30)

    log.info("Shutdown complete")
    print_stats()


if __name__ == "__main__":
    main()
