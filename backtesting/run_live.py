#!/usr/bin/env python3
"""
Live front-testing runner — monitors 5-minute up/down markets continuously.

Each strategy gets its own DB and log file for full isolation.
Managed by the `backtester` CLI script.

Key optimization: signal is pre-computed during the wait between windows,
so when a new window opens we only need to fetch market + place bet (~1-2s).
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

MAX_ENTRY_DELAY = 45
MAX_RUNTIME_SECONDS = 8 * 24 * 3600  # 8 days

TIMEFRAME_SECONDS = {"5m": 300, "15m": 900, "4h": 14400}

running = True
_db_path = None
_timeframe = "5m"
_ohlcv_limit = 120


def signal_handler(sig, frame):
    global running
    log.info("Shutting down gracefully...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

log = logging.getLogger("live")


def setup_logging(log_path=None):
    if log_path:
        handlers = [logging.FileHandler(log_path)]
    else:
        handlers = [logging.StreamHandler()]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def load_strategy(name):
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "strategies", f"{name}.py")
    if not os.path.exists(path):
        log.error(f"Strategy not found: {path}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    timeframe = getattr(mod, "TIMEFRAME", "5m")
    ohlcv_limit = getattr(mod, "OHLCV_LIMIT", 120)
    return mod.generate_signal, timeframe, ohlcv_limit


def get_bet_size(coin):
    """Dynamic position sizing — scales up as balance grows relative to starting capital.

    < 2x starting: 2%
    < 4x starting: 3%
    >= 4x starting: 4% (cap)
    """
    conn = db.get_db(_db_path)
    row = conn.execute("SELECT balance, initial_balance FROM account WHERE id = 1").fetchone()
    conn.close()
    balance = row["balance"]
    initial = row["initial_balance"]

    if balance >= initial * 4:
        pct = 0.04
    elif balance >= initial * 2:
        pct = 0.03
    else:
        pct = 0.02

    bet = balance * pct
    bet = max(bet, 0)
    bet = min(bet, balance)
    return round(bet, 2)


def coin_slug(coin):
    """Convert coin name to Polymarket slug prefix."""
    mapping = {
        "bitcoin": "btc",
        "ethereum": "eth",
        "solana": "sol",
        "dogecoin": "doge",
        "xrp": "xrp",
        "bnb": "bnb",
    }
    return mapping.get(coin, coin)


def resolve_pending(coin):
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
            end_price = price.get_current_price(price.symbol_for_coin(coin))
        except Exception:
            end_price = 0

        db.resolve_trade(trade["id"], outcome, end_price, config.FEE_RATE, _db_path)
        log.info(f"Trade #{trade['id']}: market resolved {winner}, we bet {trade['direction']} → {outcome}")

    db.take_snapshot(_db_path)


def precompute_signal(strategy_fn, coin="dogecoin"):
    """Pre-compute signal during wait time."""
    try:
        symbol = price.symbol_for_coin(coin)
        current_price = price.get_current_price(symbol)
        ohlcv = price.get_ohlcv(symbol, "1m", limit=_ohlcv_limit)

        result = strategy_fn(coin, _timeframe, current_price, ohlcv)
        if result is None:
            return None

        if len(result) == 3:
            direction, confidence, reasoning = result
        else:
            direction, confidence = result
            reasoning = ""

        return direction, confidence, current_price, reasoning
    except Exception as e:
        log.error(f"Error precomputing signal: {e}")
        return None


def place_bet_fast(cached_signal, strategy_name, coin="dogecoin"):
    """Place bet using pre-computed signal. Only fetches market (1 API call)."""
    balance = db.get_balance(_db_path)
    open_pos = db.get_open_positions(_db_path)

    bet_size = get_bet_size(coin)

    if bet_size < config.MIN_BET_SIZE:
        log.warning(f"Bet too small: ${bet_size:.2f} (balance: ${balance:.2f})")
        return False

    if open_pos >= config.MAX_CONCURRENT_BETS:
        log.info(f"Max concurrent bets: {open_pos}")
        return False

    slug_prefix = coin_slug(coin)
    mkt = market.get_current_market(slug_prefix, _timeframe)
    if not mkt:
        log.warning(f"No active market found for {slug_prefix}")
        return False

    log.info(
        f"Market: {mkt['title']} | "
        f"UP: {mkt['up_price']:.3f} DOWN: {mkt['down_price']:.3f} | "
        f"Elapsed: {mkt['elapsed_seconds']}s"
    )

    if mkt["elapsed_seconds"] > MAX_ENTRY_DELAY:
        log.info(f"Too late in window ({mkt['elapsed_seconds']}s > {MAX_ENTRY_DELAY}s)")
        return False

    direction, confidence, coin_price, reasoning = cached_signal

    if confidence < config.MIN_CONFIDENCE:
        log.info(f"Confidence {confidence:.2f} < {config.MIN_CONFIDENCE}, skipping")
        return False

    entry_price = mkt["up_price"] if direction == "UP" else mkt["down_price"]

    log.info(f"Signal: {direction} (conf: {confidence:.2f}) | Price: ${coin_price:,.4f} | Bet: ${bet_size:.2f} ({bet_size/balance*100:.1f}% of ${balance:.2f})")
    if reasoning:
        log.info(f"Reasoning: {reasoning}")

    trade_id = db.place_bet(
        strategy=strategy_name,
        market_slug=mkt["slug"],
        coin=coin,
        timeframe=_timeframe,
        direction=direction,
        confidence=confidence,
        entry_price=entry_price,
        bet_size_usd=bet_size,
        start_price=coin_price,
        db_path=_db_path,
    )
    if trade_id:
        log.info(f"*** BET *** #{trade_id}: {direction} ${bet_size:.2f} @ {entry_price:.3f} on {mkt['title']}")
        return True
    return False


def print_stats(strategy=None):
    stats = db.get_stats(strategy=strategy, db_path=_db_path)
    log.info(
        f"Stats | Balance: ${stats['balance']:.2f} | "
        f"Trades: {stats['total_trades']} | "
        f"W/L: {stats['wins']}/{stats['losses']} | "
        f"Win Rate: {stats['win_rate']:.1f}% | "
        f"PnL: ${stats['total_pnl']:+.2f}"
    )


def wait_for_next_window_with_precompute(strategy_fn, strategy_name, coin="dogecoin"):
    """Wait for the next window. Pre-compute signal ~30s before."""
    window_secs = TIMEFRAME_SECONDS[_timeframe]
    now = int(time.time())
    next_window = ((now // window_secs) + 1) * window_secs
    wait = next_window - now
    precompute_at = next_window - 30

    log.info(f"Waiting {wait}s for next window. Will precompute signal in {precompute_at - now}s...")

    resolve_pending(coin)
    print_stats(strategy_name)

    cached_signal = None
    precomputed = False

    while running:
        now = int(time.time())
        if now >= next_window:
            break

        if not precomputed and now >= precompute_at:
            log.info("Pre-computing signal for next window...")
            cached_signal = precompute_signal(strategy_fn, coin)
            precomputed = True
            if cached_signal:
                d, c, p, r = cached_signal
                log.info(f"Cached signal: {d} (confidence: {c:.2f}) | Price: ${p:,.4f}")
                if r:
                    log.info(f"Reasoning: {r}")
            else:
                log.info("No signal — market is choppy or no pattern detected")

        time.sleep(1)

    return cached_signal


def main():
    global _db_path, _ohlcv_limit

    parser = argparse.ArgumentParser(description="Live front-testing runner")
    parser.add_argument("--strategy", default="momentum_v2")
    parser.add_argument("--coin", default="dogecoin")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--db", default=None)
    parser.add_argument("--log", default=None)
    args = parser.parse_args()

    global _timeframe
    _db_path = args.db
    setup_logging(args.log)

    db.init_db(args.balance, _db_path)
    if args.reset:
        db.reset_account(args.balance, _db_path)
    strategy_fn, _timeframe, _ohlcv_limit = load_strategy(args.strategy)

    log.info(f"=== Starting front-tester ===")
    log.info(f"Strategy: {args.strategy} | Coin: {args.coin} | Timeframe: {_timeframe}")
    log.info(f"Signal history: {_ohlcv_limit} x 1m candles")
    log.info(f"Sizing: 2% (<2x) → 3% (<4x) → 4% (4x+) of starting balance")
    log.info(f"Fee rate: {config.FEE_RATE*100:.2f}% | Min confidence: {config.MIN_CONFIDENCE}")
    log.info(f"DB: {_db_path or 'default'}")
    print_stats()

    cached_signal = wait_for_next_window_with_precompute(
        strategy_fn, args.strategy, args.coin
    )

    while running:
        try:
            # Heartbeat + runtime check
            created, now, runtime = db.heartbeat(_db_path)
            if runtime >= MAX_RUNTIME_SECONDS:
                days = runtime / 86400
                log.info(f"=== FRONT-TEST COMPLETE — {days:.1f} days reached ===")
                print_stats(args.strategy)
                # Mark as finished in DB
                conn = db.get_db(_db_path)
                try:
                    conn.execute("ALTER TABLE account ADD COLUMN status TEXT DEFAULT 'running'")
                except Exception:
                    pass
                conn.execute("UPDATE account SET status = 'finished' WHERE id = 1")
                conn.commit()
                conn.close()
                break

            if cached_signal:
                place_bet_fast(cached_signal, args.strategy, args.coin)
            else:
                log.info("No signal cached, skipping this window")

            cached_signal = wait_for_next_window_with_precompute(
                strategy_fn, args.strategy, args.coin
            )

        except Exception as e:
            log.error(f"Error in cycle: {e}", exc_info=True)
            time.sleep(30)

    log.info("Shutdown complete")
    print_stats()


if __name__ == "__main__":
    main()
